#!/usr/bin/env python3
"""
Build scripts/eval_sets/small_molecule_ad.json from REAL ChEMBL queries.

Actives: compounds with measured potency (pChEMBL value) against the AD key
targets Acetylcholinesterase (ACHE), Beta-secretase 1 (BACE1) and
Microtubule-associated protein tau (MAPT) — resolved live from ChEMBL
(target -> UniProt accession via target_components; activities -> molecules
-> canonical SMILES). Controls: well-known non-AD compounds resolved by name
via chembl_tool.search_molecule.

Every SMILES is re-verified with chembl_tool.molecule_by_smiles and every
target UniProt accession with uniprot_tool.get_entry; entries failing
verification are dropped and logged (nothing is invented in their place).
Raw API responses are dumped to outputs/run_<TS>/ for audit. Re-runnable.

Usage: python scripts/eval_sets/build_small_molecule_set.py
"""

import json, sys, time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR.parent / "src" / "tools"))

from output_utils import run_dir
import chembl_tool
import uniprot_tool

TS = int(time.time())
RUN_DIR = run_dir(TS)
OUT_FILE = Path(__file__).resolve().parent / "small_molecule_ad.json"

ACTIVES_PER_TARGET = 12
TARGETS = ["Acetylcholinesterase", "Beta-secretase 1", "Microtubule-associated protein tau"]
CONTROL_NAMES = [
    "aspirin", "caffeine", "acetaminophen", "ibuprofen", "metformin",
    "atorvastatin", "omeprazole", "amoxicillin", "lisinopril", "metoprolol",
    "sildenafil", "warfarin",
]

raw_responses = {}  # audit trail -> outputs/run_<TS>/chembl_raw_<TS>.json


def resolve_target(name: str):
    """Human SINGLE PROTEIN target whose pref_name exactly matches `name`
    (case-insensitive) -> (chembl_id, pref_name, uniprot).

    Exact pref_name match only: the fuzzy `q` search is unreliable (queries
    for 'Acetylcholinesterase' and 'Beta-secretase 1' both surfaced the same
    unrelated enzyme), and a verification tool must never silently fall back
    to a wrong target.
    """
    data = chembl_tool._get("target.json", params={"pref_name__iexact": name, "limit": 20})
    raw_responses[f"target_search:{name}"] = data
    targets = [t for t in (data or {}).get("targets") or []
               if t.get("organism") == "Homo sapiens" and t.get("target_type") == "SINGLE PROTEIN"]
    if not targets:
        return None
    pick = targets[0]
    tid = pick.get("target_chembl_id")
    detail = chembl_tool._get(f"target/{tid}.json")
    raw_responses[f"target_detail:{tid}"] = detail
    comps = (detail or {}).get("target_components") or []
    accession = comps[0].get("accession") if comps else None
    return tid, pick.get("pref_name"), accession


def potent_molecules(target_chembl_id: str, limit: int):
    """Distinct molecules with a pChEMBL value against the target."""
    data = chembl_tool._get("activity.json", params={
        "target_chembl_id": target_chembl_id,
        "pchembl_value__isnull": "false",
        "limit": 200,
    })
    raw_responses[f"activities:{target_chembl_id}"] = data
    seen, out = set(), []
    for a in (data or {}).get("activities") or []:
        cid = a.get("molecule_chembl_id")
        if cid and cid not in seen and a.get("pchembl_value") is not None:
            seen.add(cid)
            out.append((cid, a["pchembl_value"]))
            if len(out) >= limit:
                break
    return out


def molecule_detail(chembl_id: str):
    data = chembl_tool._get(f"molecule/{chembl_id}.json")
    raw_responses[f"molecule:{chembl_id}"] = data
    m = data or {}
    structures = m.get("molecule_structures") or {}
    return {
        "chembl_id": m.get("molecule_chembl_id"),
        "pref_name": m.get("pref_name"),
        "smiles": structures.get("canonical_smiles"),
        "max_phase": m.get("max_phase"),
    }


def main():
    entries, dropped = [], []

    # ---- Actives: measured potency against AD key targets ----
    seen_cids = set()
    for tname in TARGETS:
        resolved = resolve_target(tname)
        if not resolved:
            print(f"WARNING: target not resolved: {tname}")
            continue
        tid, pref, uniprot = resolved
        print(f"Target {tname} -> {tid} ({pref}), UniProt {uniprot}")
        for cid, pchembl in potent_molecules(tid, ACTIVES_PER_TARGET):
            if cid in seen_cids:
                continue
            seen_cids.add(cid)
            m = molecule_detail(cid)
            entries.append({
                "name": m["pref_name"] or cid,
                "smiles": m["smiles"],
                "target_uniprot": uniprot,
                "known_ad_activity": "YES",
                "source": f"ChEMBL {tid} activity record (pchembl={pchembl})",
            })

    # ---- Controls: common non-AD compounds ----
    for cname in CONTROL_NAMES:
        hits = chembl_tool.search_molecule(cname, limit=1)
        raw_responses[f"control_search:{cname}"] = hits
        if not hits:
            print(f"WARNING: control not resolved: {cname}")
            continue
        h = hits[0]
        entries.append({
            "name": h["pref_name"] or cname,
            "smiles": h["smiles"],
            "target_uniprot": "NA",
            "known_ad_activity": "NO",
            "source": f"ChEMBL {h['chembl_id']}; common non-AD control (no AD-target activity annotation)",
        })

    # ---- Verification pass: SMILES re-lookup + UniProt entry must exist ----
    verified = []
    for e in entries:
        ok_smiles = bool(e["smiles"]) and chembl_tool.molecule_by_smiles(e["smiles"]) is not None
        ok_uniprot = (e["target_uniprot"] == "NA"
                      or uniprot_tool.get_entry(e["target_uniprot"]) is not None)
        if ok_smiles and ok_uniprot:
            verified.append(e)
        else:
            dropped.append({**e, "smiles_ok": ok_smiles, "uniprot_ok": ok_uniprot})
            print(f"DROPPED (verification failed): {e['name']} smiles_ok={ok_smiles} uniprot_ok={ok_uniprot}")

    n_yes = sum(1 for e in verified if e["known_ad_activity"] == "YES")
    print(f"\nBuilt {len(verified)} entries ({n_yes} YES / {len(verified)-n_yes} NO), {len(dropped)} dropped")

    OUT_FILE.write_text(json.dumps(verified, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"-> {OUT_FILE}")

    raw_file = RUN_DIR / f"chembl_raw_{TS}.json"
    raw_file.write_text(json.dumps(
        {"raw_responses": raw_responses, "dropped": dropped}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"-> {raw_file}")


if __name__ == "__main__":
    main()
