#!/usr/bin/env python3
"""
Generalized compound lookup for CDA-designed candidates (Phase 2 Tier 1).

Generalized lookup script — routes by Modality to the corresponding database
to verify the key identifiers of each modality in the agent output (does not
modify the raw agent output; only produces independent verification artifacts):

- Nano modality (nanocluster/nanoparticle/single_atom/dual_atom, including
  values relocated verbatim from legacy records' Material_Category) → reuses
  the candidate extraction and query logic of formula_lookup.py
  (import candidates_for / make_source; MP+PubChem)
- small_molecule → PubChem (name + SMILES) + ChEMBL molecule_by_smiles
  → verification conclusion: SMILES valid/invalid, chembl_id of the
  corresponding known compound
- biologic → UniProt get_entry(Target_UniProt) → validate that the accession exists

Input: task100_cda_<TS>_part*.txt in the run directory (parsed with
schema_v2.normalize_record, compatible with legacy 9/10/11-column records
and 13-column v2 records).
Output (written to the same run directory):
- compound_lookup_raw_<TS>.txt  — raw API responses written to disk
- compound_map_<TS>.json        — {source, ts, materials: {name: {...}}}

Usage:
  python scripts/compound_lookup.py [timestamp]
  python scripts/compound_lookup.py --input-dir outputs/run_<TS>
"""

import argparse, io, json, re, sys, time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from output_utils import find_run_dir, OUTPUT_ROOT
from schema_v2 import normalize_record

# Nano modality set: the four from schema_v2 plus same-named values migrated verbatim from legacy records' Material_Category
NANO_MODALITIES = {"nanocluster", "nanoparticle", "single_atom", "dual_atom"}

# Invalid placeholder values (what agents fill in for not-applicable fields)
NA_VALUES = {"", "NA", "N/A", "None", "none", "null", "-"}


def _is_filled(value) -> bool:
    """Whether a field has substantive content (not an NA placeholder)."""
    return value is not None and str(value).strip() not in NA_VALUES


# ---------------------------------------------------------------------------
# Record loading and parsing
# ---------------------------------------------------------------------------

def load_records(input_dir: Path, ts: str):
    """Read task100_cda_<ts>_part*.txt; v2 is parsed with normalize_record,
    v3 (AD100) with parse_record_v3, mapping Drug_Type to the routing Modality."""
    from schema_v2 import parse_record_v3
    V3_TO_MODALITY = {"nano_formulation": "nanoparticle",
                      "small_molecule": "small_molecule",
                      "biologic": "biologic",
                      "composite": "nanoparticle",  # binary composite: verify as the nano phase first (formula + coating)
                      "other": "other"}
    parts = sorted(input_dir.glob(f"task100_cda_{ts}_part*.txt"))
    if not parts:
        raise SystemExit(f"No task100_cda_{ts}_part*.txt found in {input_dir}")
    records = []
    for p in parts:
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            # v3 FIRST: both v2 and v3 accept 13-col records, but
            # parse_record_v3 discriminates on DRUG_TYPES (cells[1]) while
            # normalize_record would silently misparse v3 rows as v2.
            rec = None
            rec3 = parse_record_v3(cells)
            if rec3 is not None:
                rec3["Modality"] = V3_TO_MODALITY.get(rec3.get("Drug_Type", ""), "other")
                rec = rec3
            if rec is None:
                rec = normalize_record(cells)
            if rec is not None:
                records.append(rec)
    return [p.name for p in parts], records


# ---------------------------------------------------------------------------
# Per-modality verification functions (input: v2 record dict; output: map entry + raw record list)
# ---------------------------------------------------------------------------

def lookup_nano(rec, inorg_fn, organic_fn, raw_lines, sleep_s=1.0):
    """Nano modality: reuse candidates_for + query functions from formula_lookup.py.

    candidates_for expects a legacy cells list ([0] name, [1] formula, [2] ligand);
    here we mechanically rebuild that triple from the v2 record and feed it in.
    """
    # candidates_for expects a legacy cells list ([0] name, [1] formula, [2] ligand, and
    # checks field presence via len(cells)>=10/11); here we rebuild from the v2 record
    # and pad to 11 columns before feeding it in.
    from formula_lookup import candidates_for

    name = rec["Material_Name"]
    cells = [name, rec.get("Chemical_Formula", ""), rec.get("Ligand", "")] + [""] * 8
    cands = candidates_for(cells)

    entry = {"modality": rec["Modality"]}
    ids = []
    for q, role in cands:
        fn = organic_fn if role == "ligand" else inorg_fn
        res = fn(q)
        time.sleep(sleep_s)  # polite rate limiting (tools also enforce their own minimum interval)
        raw_lines.append(f"=== QUERY [{rec['Modality']}:{name}] {q} ({role}) ===\n"
                         f"{json.dumps(res.get('raw'), ensure_ascii=False)[:3000]}\n")
        if res.get("formula"):
            entry[role] = {"query": q, "formula": res["formula"],
                           "id": res["id"], "source": res["source"]}
            if res.get("id"):
                ids.append(res["id"])
        print(f"    {q} ({role}) -> "
              f"{res['formula']} [{res['id']}]" if res.get("formula") else f"    {q} ({role}) -> NO MATCH")

    if len(entry) > 1:  # any hit
        parts = []
        for role in ("active_phase", "support"):
            r = entry.get(role)
            if r and r["formula"] not in parts:
                parts.append(r["formula"])
        entry["combined_formula"] = " + ".join(parts)
        entry["ids"] = ids
    return entry


def lookup_small_molecule(rec, pc, raw_lines, sleep_s=1.0):
    """Small-molecule modality: PubChem (name + SMILES) + ChEMBL molecule_by_smiles.

    Produces verification conclusions: SMILES valid/invalid, chembl_id of the known compound.
    """
    from src.tools.chembl_tool import molecule_by_smiles

    name = rec["Material_Name"]
    smiles = (rec.get("SMILES") or "").strip()
    entry = {"modality": rec["Modality"], "smiles": smiles or None}

    # ---- PubChem name lookup ----
    pubchem_name = None
    if _is_filled(name):
        info = pc.get_compound_info(name)
        time.sleep(sleep_s)
        raw_lines.append(f"=== QUERY [small_molecule:{name}] PubChem name ===\n"
                         f"{json.dumps(info, ensure_ascii=False)[:3000]}\n")
        comp = (info or {}).get("Compound") or {}
        if comp.get("CID"):
            pubchem_name = {"formula": comp.get("MolecularFormula") or comp.get("molecular_formula"),
                            "id": f"CID:{comp['CID']}",
                            "canonical_smiles": comp.get("canonical_smiles")}
            entry["pubchem_name"] = pubchem_name
        print(f"    PubChem name '{name}' -> "
              f"{pubchem_name['id']}" if pubchem_name else f"    PubChem name '{name}' -> NO MATCH")

    # ---- SMILES dual-source verification: ChEMBL + PubChem ----
    chembl_hit = None
    pubchem_smiles = None
    if _is_filled(smiles):
        chembl_hit = molecule_by_smiles(smiles)
        time.sleep(sleep_s)
        raw_lines.append(f"=== QUERY [small_molecule:{name}] ChEMBL smiles: {smiles} ===\n"
                         f"{json.dumps(chembl_hit, ensure_ascii=False)}\n")

        try:
            enc = quote(smiles, safe="")
            info = pc._make_request(
                f"compound/smiles/{enc}/property/MolecularFormula,CanonicalSMILES,InChIKey/JSON")
            time.sleep(sleep_s)
            raw_lines.append(f"=== QUERY [small_molecule:{name}] PubChem smiles: {smiles} ===\n"
                             f"{json.dumps(info, ensure_ascii=False)[:3000]}\n")
            props = ((info or {}).get("PropertyTable") or {}).get("Properties") or []
            if props and props[0].get("CID"):
                pubchem_smiles = {"formula": props[0].get("MolecularFormula"),
                                  "id": f"CID:{props[0]['CID']}",
                                  "inchikey": props[0].get("InChIKey")}
                entry["pubchem_smiles"] = pubchem_smiles
        except Exception as e:
            raw_lines.append(f"=== QUERY [small_molecule:{name}] PubChem smiles ERROR: {e} ===\n")

    # ---- Aggregate verification conclusions ----
    smiles_valid = bool(chembl_hit or pubchem_smiles)
    entry["smiles_valid"] = smiles_valid
    entry["chembl"] = chembl_hit
    if smiles_valid:
        cid = chembl_hit["chembl_id"] if chembl_hit else None
        via = f"ChEMBL {cid} ({chembl_hit['match_type']})" if chembl_hit else \
              f"PubChem {pubchem_smiles['id']}"
        entry["conclusion"] = f"SMILES valid; known compound via {via}"
    elif _is_filled(smiles):
        entry["conclusion"] = "SMILES invalid or unknown: no ChEMBL/PubChem structure match"
    else:
        entry["conclusion"] = "no SMILES provided (field NA)"
    print(f"    SMILES -> {entry['conclusion']}")
    return entry


def lookup_biologic(rec, raw_lines, sleep_s=1.0):
    """Biologic modality: validate the accession via UniProt get_entry(Target_UniProt)."""
    from src.tools.uniprot_tool import get_entry

    name = rec["Material_Name"]
    accession = (rec.get("Target_UniProt") or "").strip()
    entry = {"modality": rec["Modality"], "uniprot_accession": accession or None}

    if not _is_filled(accession):
        entry["valid"] = False
        entry["conclusion"] = "no Target_UniProt provided (field NA)"
        print(f"    UniProt -> {entry['conclusion']}")
        return entry

    hit = get_entry(accession)
    time.sleep(sleep_s)
    raw_lines.append(f"=== QUERY [biologic:{name}] UniProt {accession} ===\n"
                     f"{json.dumps(hit, ensure_ascii=False)}\n")
    if hit:
        entry.update({"valid": True, "protein_name": hit.get("protein_name"),
                      "gene": hit.get("gene"), "organism": hit.get("organism")})
        entry["conclusion"] = f"UniProt accession valid: {hit.get('protein_name')} ({hit.get('gene')})"
    else:
        entry["valid"] = False
        entry["conclusion"] = "UniProt accession invalid or network failure"
    print(f"    UniProt {accession} -> {entry['conclusion']}")
    return entry


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Modality-routed compound lookup for CDA outputs")
    ap.add_argument("ts", nargs="?", default=None, help="run timestamp")
    ap.add_argument("--input-dir", default=None,
                    help="historical run directory containing task100_cda_*_part*.txt")
    args = ap.parse_args()

    # ---- Locate the input run directory and timestamp ----
    if args.input_dir:
        input_dir = Path(args.input_dir)
        if not input_dir.is_dir():
            raise SystemExit(f"--input-dir not found: {input_dir}")
        cands = list(input_dir.glob("task100_cda_*_part1.txt"))
        if not cands:
            raise SystemExit(f"No task100_cda_*_part1.txt in {input_dir}")
        ts = re.search(r"task100_cda_(\d+)_part1", cands[0].name).group(1)
    else:
        ts = args.ts
        if ts is None:
            candidates = (list(OUTPUT_ROOT.glob("task100_cda_*_part1.txt"))
                          + list(OUTPUT_ROOT.glob("run_*/task100_cda_*_part1.txt")))
            latest = max(candidates, key=lambda p: p.stat().st_mtime)
            ts = re.search(r"task100_cda_(\d+)_part1", latest.name).group(1)
        input_dir = find_run_dir(ts)

    src_files, records = load_records(input_dir, ts)
    print(f"Run dir: {input_dir}")
    print(f"{len(records)} records from {src_files}")

    # ---- Routing groups ----
    nano_recs, sm_recs, bio_recs = [], [], []
    for rec in records:
        mod = (rec.get("Modality") or "").strip().lower()
        if mod in NANO_MODALITIES:
            nano_recs.append(rec)
        elif mod == "small_molecule":
            sm_recs.append(rec)
        elif mod == "biologic":
            bio_recs.append(rec)
        else:
            print(f"  [skip] unknown modality {rec.get('Modality')!r}: {rec.get('Material_Name')}")
    print(f"Routing: {len(nano_recs)} nano, {len(sm_recs)} small_molecule, {len(bio_recs)} biologic")

    # ---- Prepare per-modality query entry points ----
    from formula_lookup import make_source
    inorg_fn, organic_fn, nano_source = make_source()
    from src.tools.pubchem_tool import get_pubchem_tool
    pc = get_pubchem_tool()

    source_parts = []
    if nano_recs:
        source_parts.append(f"{nano_source}(nano)")
    if sm_recs:
        source_parts.append("PubChem+ChEMBL(small_molecule)")
    if bio_recs:
        source_parts.append("UniProt(biologic)")
    source = "+".join(source_parts) or "none"
    print(f"Sources: {source}")

    # ---- Verify one by one (all raw responses persisted to disk) ----
    raw_lines = [f"# Compound lookup raw data — source: {source}, run {ts}\n",
                 f"# files: {src_files}\n\n"]
    mapping = {}
    for rec in records:
        name = rec["Material_Name"]
        mod = (rec.get("Modality") or "").strip().lower()
        print(f"  [{mod}] {name}")
        if mod in NANO_MODALITIES:
            mapping[name] = lookup_nano(rec, inorg_fn, organic_fn, raw_lines)
        elif mod == "small_molecule":
            mapping[name] = lookup_small_molecule(rec, pc, raw_lines)
        elif mod == "biologic":
            mapping[name] = lookup_biologic(rec, raw_lines)

    # ---- Persist: raw + map (follow the run-directory convention, written back into the input run's directory) ----
    raw_path = input_dir / f"compound_lookup_raw_{ts}.txt"
    with io.open(raw_path, "w", encoding="utf-8") as f:
        f.write("\n".join(raw_lines))
    map_path = input_dir / f"compound_map_{ts}.json"
    with io.open(map_path, "w", encoding="utf-8") as f:
        json.dump({"source": source, "ts": ts, "materials": mapping},
                  f, ensure_ascii=False, indent=2)

    print(f"\nMapped {len(mapping)}/{len(records)} records")
    print(f"Raw:  {raw_path}")
    print(f"Map:  {map_path}")


if __name__ == "__main__":
    main()
