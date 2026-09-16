#!/usr/bin/env python3
"""
Look up authoritative chemical formulas for designer-designed materials.

For each material in task100_designer_<TS>_part*.txt, queries a materials database
for the model-stated Chemical_Formula AND the support compound parsed from the
material name (e.g. Pt_SA_MoO4 -> support MoO4), so the ranking can show a
database-verified complete formula instead of the model's shorthand.

Source priority: Materials Project (needs a valid 32-char MATERIALS_PROJECT_API_KEY
in .env) -> PubChem (keyless, always available). Per-query source is recorded.
Raw API responses are saved to outputs/task100_formula_<TS>.txt; the derived
mapping goes to outputs/task100_formula_map_<TS>.json for rank_cda_outputs.py.

Agent outputs are never modified — this is separate tool data.

Usage: python scripts/formula_lookup.py [timestamp]
"""

import io, json, os, re, sys, time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from output_utils import find_run_dir, OUTPUT_ROOT

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

OUTPUT = OUTPUT_ROOT

FORMULA_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
TOKEN_RE = re.compile(r"[A-Z][a-z]?\d*")
ELEMENTS = {"H","He","Li","Be","B","C","N","O","F","Ne","Na","Mg","Al","Si","P","S","Cl","Ar",
            "K","Ca","Sc","Ti","V","Cr","Mn","Fe","Co","Ni","Cu","Zn","Ga","Ge","As","Se","Br","Kr",
            "Rb","Sr","Y","Zr","Nb","Mo","Tc","Ru","Rh","Pd","Ag","Cd","In","Sn","Sb","Te","I","Xe",
            "Cs","Ba","La","Ce","Pr","Nd","Pm","Sm","Eu","Gd","Tb","Dy","Ho","Er","Tm","Yb","Lu",
            "Hf","Ta","W","Re","Os","Ir","Pt","Au","Hg","Tl","Pb","Bi","Po","At","Rn"}
# Organic coatings / functional groups / non-stoichiometric tokens: not queryable compounds
NON_COMPOUND = {"CD", "GSH", "BSA", "PEG", "PVP", "PEI", "TA", "DNA", "HA", "CHA",
                "GA", "Cys", "MPA", "PAMAM", "MOF", "ZIF", "ZIF-8", "CNT", "GO",
                "ND", "NC", "SAC", "DAC", "NP", "NPs", "SA", "Clusters", "N", "C",
                "COOH", "COO", "OH", "NH2", "NO2", "SH", "CN", "CHI", "APTES"}


def formula_like(tok: str) -> bool:
    """Strict check: every token symbol must be a real element AND the symbols
    must cover the whole string (kills SILICA, Tannic, CHITOSAN etc. which only
    LOOK like formulas)."""
    if not FORMULA_RE.match(tok) or len(tok) < 2 or tok in NON_COMPOUND:
        return False
    syms = TOKEN_RE.findall(tok)
    return "".join(syms) == tok and all(s.rstrip("0123456789") in ELEMENTS for s in syms)


def load_records(ts: str):
    parts = sorted(find_run_dir(ts).glob(f"task100_designer_{ts}_part*.txt"))
    if not parts:
        raise SystemExit(f"No task100_designer_{ts}_part*.txt found in {find_run_dir(ts)}")
    records = []
    for p in parts:
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 9:
                records.append(cells)
    return [p.name for p in parts], records


ORGANIC_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9\-() ]*$")


def candidates_for(cells):
    """(query, role) pairs: model-stated inorganic formula, support parsed from
    the material name, and organic ligand (PubChem-name searchable; MP skips)."""
    out = []
    cf = cells[1] if len(cells) >= 10 else ""
    if cf and formula_like(cf):
        out.append((cf, "active_phase"))
    support = cells[0].split("_")[-1]
    if formula_like(support) and support != cf:
        out.append((support, "support"))
    ligand = cells[2] if len(cells) >= 11 else ""
    if ligand:
        if formula_like(ligand):
            if ligand != cf and ligand != support:
                out.append((ligand, "support"))
        elif (ORGANIC_NAME_RE.match(ligand) and len(ligand) > 2
              and not any(w in ligand.lower() for w in ("doped", "carbon", "graphene"))):
            out.append((ligand, "ligand"))
    return out


def make_source():
    """Return (inorganic_fn, organic_fn, source_label).

    Inorganic compounds: Materials Project when a valid key is configured,
    else PubChem. Organic ligands: always PubChem — MP is an inorganic-only DB.
    """
    pc_fn = None
    from src.tools.pubchem_tool import get_pubchem_tool
    pc = get_pubchem_tool()

    def query_pc(q):
        try:
            info = pc.get_compound_info(q)
        except Exception as e:
            return {"source": "PubChem", "formula": None, "id": None, "raw": {"error": str(e)}}
        comp = (info or {}).get("Compound") or {}
        mf = comp.get("MolecularFormula") or comp.get("molecular_formula")
        cid = comp.get("CID")
        return {"source": "PubChem", "formula": mf,
                "id": f"CID:{cid}" if cid else None, "raw": info}

    pc_fn = query_pc

    try:
        from src.tools.materials_project_tool import get_materials_project_tool
        mp = get_materials_project_tool()

        def query_mp(q):
            r = mp.search_materials(formula=q, limit=3)
            data = r.get("data")
            if data:
                return {"source": "MaterialsProject", "formula": data[0].get("formula"),
                        "id": data[0].get("material_id"), "raw": r}
            return {"source": "MaterialsProject", "formula": None, "id": None, "raw": r}

        print("Source: MaterialsProject (inorganic) + PubChem (organic ligands)")
        return query_mp, pc_fn, "MaterialsProject+PubChem"
    except Exception as e:
        print(f"Materials Project unavailable ({type(e).__name__}), PubChem for everything")

    print("Source: PubChem")
    return pc_fn, pc_fn, "PubChem"


def main():
    ts = sys.argv[1] if len(sys.argv) > 1 else None
    if ts is None:
        candidates = (list(OUTPUT.glob("task100_designer_*_part1.txt"))
                      + list(OUTPUT.glob("run_*/task100_designer_*_part1.txt")))
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        ts = re.search(r"task100_designer_(\d+)_part1", latest.name).group(1)

    src_files, records = load_records(ts)
    inorg_fn, organic_fn, source = make_source()

    # Collect unique candidate queries (dedupe across all records)
    per_material = []   # [(name, [(query, role), ...])]
    unique = {}
    for cells in records:
        cands = candidates_for(cells)
        per_material.append((cells[0], cands))
        for q, role in cands:
            unique.setdefault((q, role), None)

    print(f"{len(records)} materials, {len(unique)} unique lookups")

    # Query each unique compound once; save raw responses
    raw_path = find_run_dir(ts) / f"task100_formula_{ts}.txt"
    with io.open(raw_path, "w", encoding="utf-8") as f:
        f.write(f"# Formula lookup raw data — source: {source}, run {ts}\n")
        f.write(f"# {len(unique)} unique queries\n\n")
        for i, (q, role) in enumerate(sorted(unique), 1):
            fn = organic_fn if role == "ligand" else inorg_fn
            res = fn(q)
            time.sleep(1.0)  # be polite to the API
            unique[(q, role)] = res
            f.write(f"=== QUERY: {q} ({role}) ===\n{json.dumps(res['raw'], ensure_ascii=False)[:3000]}\n\n")
            hit = f"{res['formula']} [{res['id']}]" if res["formula"] else "NO MATCH"
            print(f"  {i}/{len(unique)} {q} ({role}) -> {hit}")

    # Build per-material mapping
    mapping = {}
    for name, cands in per_material:
        entry = {}
        for q, role in cands:
            res = unique.get((q, role)) or {}
            if res.get("formula"):
                entry[role] = {"query": q, "formula": res["formula"],
                               "id": res["id"], "source": res["source"]}
        if entry:
            ap = entry.get("active_phase", {})
            sp = entry.get("support", {})
            parts = []
            if ap:
                parts.append(ap["formula"])
            if sp and sp["formula"] not in parts:
                parts.append(sp["formula"])
            ids = [x["id"] for x in (ap, sp) if x and x.get("id")]
            entry["combined_formula"] = " + ".join(parts)
            entry["ids"] = ids
            mapping[name] = entry

    map_path = find_run_dir(ts) / f"task100_formula_map_{ts}.json"
    with io.open(map_path, "w", encoding="utf-8") as f:
        json.dump({"source": source, "ts": ts, "materials": mapping}, f, ensure_ascii=False, indent=2)

    hits = sum(1 for v in unique.values() if v.get("formula"))
    print(f"\nLookup: {hits}/{len(unique)} compounds resolved via {source}")
    print(f"Mapped {len(mapping)}/{len(records)} materials")
    print(f"Raw:  {raw_path}")
    print(f"Map:  {map_path}")


if __name__ == "__main__":
    main()
