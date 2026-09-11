#!/usr/bin/env python3
"""
Batch evaluation: 100 nanomaterials → NADH enzyme activity + size classification.
Uses the Nano-Bio Evaluator server (must be running on localhost:8000).

Phase 4: --set nano|small_molecule|biologic (default nano = the legacy
benchmark below, unchanged). small_molecule/biologic use the eval sets in
scripts/eval_sets/ (built from real ChEMBL/UniProt queries).
"""

import httpx, json, time, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from output_utils import run_dir

TS = int(time.time())
RUN_DIR = run_dir(TS)  # per-run folder: outputs/run_<TS>/

SERVER = "http://localhost:8000/v1/chat/completions"

# ---------------------------------------------------------------------------
# Phase 4: --set nano|small_molecule|biologic (default nano = legacy benchmark,
# unchanged below). small_molecule: EPA judges AD activity vs known_ad_activity
# -> accuracy. biologic: agent must produce a verifiable Target_UniProt ->
# UniProt lookup pass rate. Eval sets live in scripts/eval_sets/ and are built
# from real ChEMBL/UniProt queries (build_*_set.py, re-runnable).
# ---------------------------------------------------------------------------
import argparse, re
from pathlib import Path

EVAL_SETS_DIR = Path(__file__).resolve().parent / "eval_sets"


def _parse_args():
    p = argparse.ArgumentParser(description="Batch evaluation against the Nano-Bio Evaluator server")
    p.add_argument("--set", choices=["nano", "small_molecule", "biologic"], default="nano",
                   help="evaluation set (default: nano — the legacy 100-nanomaterial NADH benchmark)")
    return p.parse_args()


EVAL_SET = _parse_args().set


def _call_agent(agent: str, prompt: str, max_tokens: int = 10240, temperature: float = 0.2,
                timeout: int = 900) -> str:
    r = httpx.post(SERVER, json={
        "model": "nano-bio", "agent": agent,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": temperature,
    }, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def run_small_molecule_eval():
    """EPA judges AD activity per compound; compare with known_ad_activity."""
    entries = json.loads((EVAL_SETS_DIR / "small_molecule_ad.json").read_text(encoding="utf-8"))
    print(f"Eval set: small_molecule ({len(entries)} compounds)")
    batch_size, results = 15, []
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]
        bnum = i // batch_size + 1
        comp_lines = "\n".join(
            f"{j+1}. {e['name']} (SMILES: {e['smiles']}, primary target UniProt: {e['target_uniprot']})"
            for j, e in enumerate(batch))
        prompt = f"""For each small-molecule compound below, decide whether it has KNOWN activity relevant to Alzheimer's disease (AD) — e.g., activity against acetylcholinesterase, BACE1, amyloid/tau pathways, or documented clinical/preclinical AD use. Answer YES or NO with one-line reasoning.

Compounds:
{comp_lines}

Output format (ONE LINE per compound, numbered):
1. [YES/NO] - one-line reasoning
2. [YES/NO] - one-line reasoning
..."""
        print(f"Batch {bnum}: judging AD activity for {len(batch)} compounds...")
        raw = _call_agent("epa", prompt)
        raw_file = RUN_DIR / f"smol_ad_batch{bnum}_raw_{TS}.txt"
        raw_file.write_text(raw, encoding="utf-8")
        print(f"  -> {raw_file}")

        lines = raw.split("\n")
        for idx, e in enumerate(batch):
            judged = "UNKNOWN"
            for line in lines:
                lc = line.strip()
                if lc.startswith(f"{idx+1}.") or lc.startswith(f"{idx+1})"):
                    head = lc[:20].upper()
                    if "YES" in head:
                        judged = "YES"
                    elif "NO" in head:
                        judged = "NO"
                    break
            results.append({**e, "agent_ad_activity": judged,
                            "correct": judged == e["known_ad_activity"]})
        time.sleep(1)

    decided = [r for r in results if r["agent_ad_activity"] in ("YES", "NO")]
    correct = [r for r in decided if r["correct"]]
    tp = [r for r in decided if r["agent_ad_activity"] == "YES" and r["known_ad_activity"] == "YES"]
    fn = [r for r in decided if r["agent_ad_activity"] == "NO" and r["known_ad_activity"] == "YES"]
    tn = [r for r in decided if r["agent_ad_activity"] == "NO" and r["known_ad_activity"] == "NO"]
    fp = [r for r in decided if r["agent_ad_activity"] == "YES" and r["known_ad_activity"] == "NO"]
    summary = {
        "eval_set": "small_molecule",
        "total": len(results), "decided": len(decided),
        "undecided": len(results) - len(decided),
        "accuracy": len(correct) / len(decided) if decided else None,
        "sensitivity": len(tp) / (len(tp) + len(fn)) if (tp or fn) else None,
        "specificity": len(tn) / (len(tn) + len(fp)) if (tn or fp) else None,
        "results": results,
    }
    out_file = RUN_DIR / f"smol_ad_eval_{TS}.json"
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nAccuracy: {summary['accuracy']:.2%} on {len(decided)} decided "
          f"(sensitivity {summary['sensitivity']}, specificity {summary['specificity']})")
    print(f"-> {out_file}")


def run_biologic_eval():
    """Agent must name the primary target's UniProt accession per biologic;
    each returned accession is verified against UniProtKB (查证通过率)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "tools"))
    import uniprot_tool

    entries = json.loads((EVAL_SETS_DIR / "biologic_ad.json").read_text(encoding="utf-8"))
    print(f"Eval set: biologic ({len(entries)} biologics)")
    accession_re = re.compile(r"\b(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9][A-Z][A-Z0-9]{2}[0-9])\b")
    batch_size, results = 10, []
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]
        bnum = i // batch_size + 1
        bio_lines = "\n".join(f"{j+1}. {e['name']}" for j, e in enumerate(batch))
        prompt = f"""For each Alzheimer's-disease biologic below (antibody/peptide), give the UniProt accession of its PRIMARY protein target (human). Answer with the accession and target name.

Biologics:
{bio_lines}

Output format (ONE LINE per biologic, numbered):
1. [UniProt accession] - target name
2. [UniProt accession] - target name
..."""
        print(f"Batch {bnum}: resolving targets for {len(batch)} biologics...")
        raw = _call_agent("epa", prompt)
        raw_file = RUN_DIR / f"biologic_ad_batch{bnum}_raw_{TS}.txt"
        raw_file.write_text(raw, encoding="utf-8")
        print(f"  -> {raw_file}")

        lines = raw.split("\n")
        for idx, e in enumerate(batch):
            acc = None
            for line in lines:
                lc = line.strip()
                if lc.startswith(f"{idx+1}.") or lc.startswith(f"{idx+1})"):
                    m = accession_re.search(lc)
                    acc = m.group(0) if m else None
                    break
            verified = uniprot_tool.get_entry(acc) is not None if acc else False
            results.append({**e, "agent_uniprot": acc, "uniprot_verified": verified,
                            "matches_expected": acc == e["target_uniprot"]})
        time.sleep(1)

    returned = [r for r in results if r["agent_uniprot"]]
    verified = [r for r in returned if r["uniprot_verified"]]
    matched = [r for r in results if r["matches_expected"]]
    summary = {
        "eval_set": "biologic",
        "total": len(results),
        "accession_returned": len(returned),
        "uniprot_verified": len(verified),
        "verification_pass_rate": len(verified) / len(returned) if returned else None,
        "matches_expected_target": len(matched),
        "results": results,
    }
    out_file = RUN_DIR / f"biologic_ad_eval_{TS}.json"
    out_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    rate = summary["verification_pass_rate"]
    print(f"\nUniProt 查证通过率: {len(verified)}/{len(returned)} "
          f"({rate:.2%})" if rate is not None else "\nNo accessions returned")
    print(f"-> {out_file}")


if EVAL_SET == "small_molecule":
    run_small_molecule_eval()
    sys.exit(0)
elif EVAL_SET == "biologic":
    run_biologic_eval()
    sys.exit(0)
# EVAL_SET == "nano": legacy 100-nanomaterial NADH benchmark below, unchanged.

# 100 known nanomaterials from literature reports and databases
# Each has: name, typical_size_nm, size_category
MATERIALS = [
    # === Single-atom catalysts (SACs, <0.3nm) ===
    {"name": "Fe-SAC-NC (Fe single-atom on N-doped carbon)", "size": 0.15, "category": "single_atom"},
    {"name": "Co-SAC-NG (Co single-atom on N-doped graphene)", "size": 0.18, "category": "single_atom"},
    {"name": "Cu-SAC-CN (Cu single-atom on carbon nitride)", "size": 0.16, "category": "single_atom"},
    {"name": "Mn-SAC-NC (Mn single-atom on N-doped carbon)", "size": 0.17, "category": "single_atom"},
    {"name": "Ni-SAC-C (Ni single-atom on carbon)", "size": 0.19, "category": "single_atom"},
    {"name": "Zn-SAC-NC (Zn single-atom on N-doped carbon)", "size": 0.16, "category": "single_atom"},
    {"name": "Fe-N5-SA (Fe-N5 single-atom catalyst)", "size": 0.15, "category": "single_atom"},
    {"name": "Co-N4/C (Co-N4 single-atom on carbon)", "size": 0.17, "category": "single_atom"},
    {"name": "Ru-SAC-TiO2 (Ru single-atom on TiO2)", "size": 0.20, "category": "single_atom"},
    {"name": "Pt-SAC-CeO2 (Pt single-atom on CeO2)", "size": 0.22, "category": "single_atom"},
    {"name": "Ir-SAC-Fe2O3 (Ir single-atom on Fe2O3)", "size": 0.20, "category": "single_atom"},
    {"name": "Fe-SAC-g-C3N4 (Fe single-atom on g-C3N4)", "size": 0.16, "category": "single_atom"},
    {"name": "Co-SAC-MoS2 (Co single-atom on MoS2)", "size": 0.18, "category": "single_atom"},
    {"name": "Cu-N-C-SAC (Cu-N-C single-atom)", "size": 0.15, "category": "single_atom"},
    {"name": "FeNC-SAC (Fe-N-C single-atom catalyst)", "size": 0.16, "category": "single_atom"},

    # === Dual-atom catalysts (DACs, ~0.3-0.6nm) ===
    {"name": "FeCo-DAC-NC (Fe-Co dual-atom on N-doped carbon)", "size": 0.35, "category": "dual_atom"},
    {"name": "FeMn-DAC-C (Fe-Mn dual-atom on carbon)", "size": 0.38, "category": "dual_atom"},
    {"name": "CuCo-DAC-NG (Cu-Co dual-atom on N-doped graphene)", "size": 0.33, "category": "dual_atom"},
    {"name": "FeNi-DAC-CN (Fe-Ni dual-atom on carbon nitride)", "size": 0.36, "category": "dual_atom"},
    {"name": "CoNi-DAC-C (Co-Ni dual-atom on carbon)", "size": 0.40, "category": "dual_atom"},
    {"name": "FeCu-DAC-NC (Fe-Cu dual-atom on N-doped carbon)", "size": 0.34, "category": "dual_atom"},
    {"name": "MnCo-DAC-C (Mn-Co dual-atom on carbon)", "size": 0.37, "category": "dual_atom"},
    {"name": "FeZn-DAC-NG (Fe-Zn dual-atom on N-doped graphene)", "size": 0.39, "category": "dual_atom"},
    {"name": "CoCu-BDC (Co-Cu dual-atom in BDC framework)", "size": 0.42, "category": "dual_atom"},
    {"name": "FePt-DAC-TiO2 (Fe-Pt dual-atom on TiO2)", "size": 0.45, "category": "dual_atom"},
    {"name": "NiCo-DAC-NC (Ni-Co dual-atom on N-doped carbon)", "size": 0.35, "category": "dual_atom"},
    {"name": "CuMn-DAC-C (Cu-Mn dual-atom on carbon)", "size": 0.38, "category": "dual_atom"},
    {"name": "CoPt-DAC-CeO2 (Co-Pt dual-atom on CeO2)", "size": 0.44, "category": "dual_atom"},

    # === Nanoclusters (0.5-3nm) ===
    {"name": "Cu_NC_CD (Cu nanocluster, cyclodextrin-coated)", "size": 2.5, "category": "nanocluster"},
    {"name": "Au_NC_GSH (Au nanocluster, glutathione-capped)", "size": 1.8, "category": "nanocluster"},
    {"name": "Ag_NC_DNA (Ag nanocluster, DNA-templated)", "size": 1.5, "category": "nanocluster"},
    {"name": "Cu_NC_BSA (Cu nanocluster, BSA-capped)", "size": 2.2, "category": "nanocluster"},
    {"name": "Au_NC_MPA (Au nanocluster, mercaptopropionic acid)", "size": 1.6, "category": "nanocluster"},
    {"name": "Pt_NC_PAMAM (Pt nanocluster, PAMAM dendrimer)", "size": 1.2, "category": "nanocluster"},
    {"name": "Fe_NC_CD (Fe nanocluster, cyclodextrin-coated)", "size": 2.8, "category": "nanocluster"},
    {"name": "AgCu_NC_GSH (AgCu bimetallic nanocluster, GSH-capped)", "size": 2.0, "category": "nanocluster"},
    {"name": "AuAg_NC_BSA (AuAg bimetallic nanocluster, BSA-capped)", "size": 1.9, "category": "nanocluster"},
    {"name": "Cu_NC_TA (Cu nanocluster, tannic acid-capped)", "size": 2.3, "category": "nanocluster"},
    {"name": "Au_NC_Cys (Au nanocluster, cysteine-capped)", "size": 1.4, "category": "nanocluster"},
    {"name": "CuPt_NC_PVP (CuPt nanocluster, PVP-capped)", "size": 1.7, "category": "nanocluster"},
    {"name": "Mn_NC_PEI (Mn nanocluster, PEI-coated)", "size": 2.6, "category": "nanocluster"},
    {"name": "Co_NC_CD (Co nanocluster, cyclodextrin-coated)", "size": 2.4, "category": "nanocluster"},
    {"name": "Au_NC_His (Au nanocluster, histidine-capped)", "size": 1.3, "category": "nanocluster"},
    {"name": "Cu_NC_PEI (Cu nanocluster, PEI-coated)", "size": 2.1, "category": "nanocluster"},
    {"name": "PtAu_NC_GSH (PtAu nanocluster, GSH-capped)", "size": 1.5, "category": "nanocluster"},
    {"name": "Ag_NC_PVP (Ag nanocluster, PVP-capped)", "size": 1.8, "category": "nanocluster"},
    {"name": "FeCu_NC_BSA (FeCu bimetallic nanocluster, BSA-capped)", "size": 2.5, "category": "nanocluster"},
    {"name": "Cu_NC_CD_MeIm (Cu NC@CD with 2-methylimidazole)", "size": 2.8, "category": "nanocluster"},

    # === Nanoparticles (3-100nm) ===
    {"name": "Fe3O4_NP (Fe3O4 nanoparticles)", "size": 10, "category": "nanoparticle"},
    {"name": "CeO2_NP (CeO2 nanoparticles, 5nm)", "size": 5, "category": "nanoparticle"},
    {"name": "MnO2_NP (MnO2 nanoparticles)", "size": 15, "category": "nanoparticle"},
    {"name": "Co3O4_NP (Co3O4 nanoparticles)", "size": 12, "category": "nanoparticle"},
    {"name": "CuO_NP (CuO nanoparticles)", "size": 20, "category": "nanoparticle"},
    {"name": "ZnO_NP (ZnO nanoparticles, 15nm)", "size": 15, "category": "nanoparticle"},
    {"name": "TiO2_NP (TiO2 nanoparticles, 25nm)", "size": 25, "category": "nanoparticle"},
    {"name": "Ag_NP (Ag nanoparticles, 10nm)", "size": 10, "category": "nanoparticle"},
    {"name": "Au_NP (Au nanoparticles, 5nm)", "size": 5, "category": "nanoparticle"},
    {"name": "Pt_NP_C (Pt nanoparticles on carbon)", "size": 3.5, "category": "nanoparticle"},
    {"name": "Pd_NP_C (Pd nanoparticles on carbon)", "size": 4, "category": "nanoparticle"},
    {"name": "NiO_NP (NiO nanoparticles)", "size": 18, "category": "nanoparticle"},
    {"name": "V2O5_NP (V2O5 nanoparticles)", "size": 30, "category": "nanoparticle"},
    {"name": "MoS2_NP (MoS2 nanoflakes)", "size": 50, "category": "nanoparticle"},
    {"name": "WS2_NP (WS2 nanoparticles)", "size": 40, "category": "nanoparticle"},
    {"name": "Bi2Se3_NP (Bi2Se3 nanoparticles)", "size": 35, "category": "nanoparticle"},
    {"name": "Fe2O3_NP (Fe2O3 nanoparticles)", "size": 20, "category": "nanoparticle"},
    {"name": "ZrO2_NP (ZrO2 nanoparticles, 8nm)", "size": 8, "category": "nanoparticle"},
    {"name": "MgO_NP (MgO nanoparticles)", "size": 25, "category": "nanoparticle"},
    {"name": "SiO2_NP (SiO2 nanoparticles, mesoporous)", "size": 60, "category": "nanoparticle"},
    {"name": "CdSe_QD (CdSe quantum dots, 3nm)", "size": 3, "category": "nanoparticle"},
    {"name": "PbS_QD (PbS quantum dots)", "size": 4, "category": "nanoparticle"},
    {"name": "Carbon_QD (Carbon quantum dots, 5nm)", "size": 5, "category": "nanoparticle"},
    {"name": "Graphene_QD (Graphene quantum dots)", "size": 3, "category": "nanoparticle"},
    {"name": "MoSe2_NP (MoSe2 nanoparticles)", "size": 45, "category": "nanoparticle"},
    {"name": "CuFe2O4_NP (CuFe2O4 spinel nanoparticles)", "size": 15, "category": "nanoparticle"},
    {"name": "MnFe2O4_NP (MnFe2O4 nanoparticles)", "size": 12, "category": "nanoparticle"},
    {"name": "CoFe2O4_NP (CoFe2O4 nanoparticles)", "size": 10, "category": "nanoparticle"},
    {"name": "ZnFe2O4_NP (ZnFe2O4 nanoparticles)", "size": 14, "category": "nanoparticle"},
    {"name": "NiFe2O4_NP (NiFe2O4 nanoparticles)", "size": 16, "category": "nanoparticle"},
    {"name": "FeNi_NP_C (FeNi alloy nanoparticles on carbon)", "size": 8, "category": "nanoparticle"},
    {"name": "FeCo_NP_NC (FeCo alloy nanoparticles, N-doped carbon)", "size": 10, "category": "nanoparticle"},
    {"name": "Pr6O11_NP (Pr6O11 nanoparticles)", "size": 20, "category": "nanoparticle"},
    {"name": "Nd2O3_NP (Nd2O3 nanoparticles)", "size": 22, "category": "nanoparticle"},
    {"name": "La2O3_NP (La2O3 nanoparticles)", "size": 25, "category": "nanoparticle"},
    {"name": "Y2O3_NP (Y2O3 nanoparticles)", "size": 18, "category": "nanoparticle"},
    {"name": "Gd2O3_NP (Gd2O3 nanoparticles)", "size": 15, "category": "nanoparticle"},
    {"name": "Eu2O3_NP (Eu2O3 nanoparticles)", "size": 20, "category": "nanoparticle"},
    {"name": "Ho2O3_NP (Ho2O3 nanoparticles)", "size": 22, "category": "nanoparticle"},
    {"name": "Er2O3_NP (Er2O3 nanoparticles)", "size": 18, "category": "nanoparticle"},
    {"name": "Yb2O3_NP (Yb2O3 nanoparticles)", "size": 20, "category": "nanoparticle"},
    {"name": "MnO_NP (MnO nanoparticles)", "size": 15, "category": "nanoparticle"},
    {"name": "SnO2_NP (SnO2 nanoparticles)", "size": 30, "category": "nanoparticle"},
    {"name": "WO3_NP (WO3 nanoparticles)", "size": 35, "category": "nanoparticle"},
    {"name": "RuO2_NP (RuO2 nanoparticles)", "size": 5, "category": "nanoparticle"},
    {"name": "IrO2_NP (IrO2 nanoparticles)", "size": 6, "category": "nanoparticle"},
    {"name": "Ag2S_NP (Ag2S nanoparticles)", "size": 10, "category": "nanoparticle"},
    {"name": "Cu2O_NP (Cu2O nanoparticles)", "size": 25, "category": "nanoparticle"},
    {"name": "FeOOH_NP (FeOOH nanorods)", "size": 40, "category": "nanoparticle"},
    {"name": "AlOOH_NP (AlOOH nanoparticles)", "size": 30, "category": "nanoparticle"},
    {"name": "ZnS_QD (ZnS quantum dots)", "size": 3.5, "category": "nanoparticle"},
    {"name": "Ag2Se_QD (Ag2Se quantum dots)", "size": 4, "category": "nanoparticle"},
    {"name": "FeS2_NP (FeS2 nanoparticles)", "size": 20, "category": "nanoparticle"},
]

print(f"Total materials: {len(MATERIALS)}")
print(f"  Single-atom: {sum(1 for m in MATERIALS if m['category']=='single_atom')}")
print(f"  Dual-atom:   {sum(1 for m in MATERIALS if m['category']=='dual_atom')}")
print(f"  Nanocluster: {sum(1 for m in MATERIALS if m['category']=='nanocluster')}")
print(f"  Nanoparticle:{sum(1 for m in MATERIALS if m['category']=='nanoparticle')}")
print()

# Build EPA prompt — send all 100 materials in one call per agent
BATCH_SIZE = 25  # Materials per agent call

results_all = []
start_time = time.time()

for i in range(0, len(MATERIALS), BATCH_SIZE):
    batch = MATERIALS[i:i+BATCH_SIZE]
    batch_num = i // BATCH_SIZE + 1

    # Build material list for this batch
    mat_list = "\n".join(
        f"{j+1}. {m['name']} (size: {m['size']}nm, category: {m['category']})"
        for j, m in enumerate(batch)
    )

    # EPA: NADH oxidase-like activity classification
    epa_prompt = f"""Analyze the following nanomaterials for NADH oxidase-like enzyme activity.

For each material, answer YES or NO for NADH oxidase-like activity based on known literature and structure-activity relationships. Give a one-line reasoning.

NADH oxidase-like activity indicators:
- Core elements: Cu, Fe, Mn, Co, Ni, Pt, Au (especially Cu in nanocluster form)
- Ultra-small size (<10nm) favors activity
- Organic coating (cyclodextrin, GSH, BSA) can enhance electron transfer
- Mixed valence states enable redox cycling

Materials to analyze:
{mat_list}

Output format (ONE LINE per material, numbered):
1. [YES/NO] - one-line reasoning
2. [YES/NO] - one-line reasoning
..."""

    print(f"Batch {batch_num}: Evaluating {len(batch)} materials for NADH activity...")

    try:
        r = httpx.post(SERVER, json={
            "model": "nano-bio",
            "agent": "epa",
            "messages": [{"role": "user", "content": epa_prompt}],
            "max_tokens": 10240,
            "temperature": 0.2
        }, timeout=900)

        if r.status_code == 200:
            data = r.json()
            epa_result = data["choices"][0]["message"]["content"]

            # Preserve RAW agent output (project rule: outputs must be saved unmodified)
            raw_file = RUN_DIR / f"nadh_100_batch{batch_num}_raw_{TS}.txt"
            with open(raw_file, "w", encoding="utf-8") as f:
                f.write(epa_result)
            print(f"  -> {raw_file}")

            # Parse EPA results — extract YES/NO per material
            for idx, mat in enumerate(batch):
                # Search for the matching line
                lines = epa_result.split("\n")
                nadh = "UNKNOWN"
                reasoning = ""
                for line in lines:
                    line_clean = line.strip()
                    # Match numbered results
                    if line_clean.startswith(f"{idx+1}.") or line_clean.startswith(f"{idx+1})"):
                        if "YES" in line_clean[:20]:
                            nadh = "YES"
                            reasoning = line_clean.split("-", 1)[-1].strip() if "-" in line_clean else line_clean[20:]
                        elif "NO" in line_clean[:20]:
                            nadh = "NO"
                            reasoning = line_clean.split("-", 1)[-1].strip() if "-" in line_clean else line_clean[20:]
                        break

                results_all.append({
                    "name": mat["name"],
                    "size_nm": mat["size"],
                    "size_category": mat["category"],
                    "nadh_oxidase_like": nadh,
                    "reasoning": reasoning[:200]
                })

            print(f"  Done. {len(batch)} materials processed.")
        else:
            print(f"  Error: HTTP {r.status_code}")
            for m in batch:
                results_all.append({**m, "nadh_oxidase_like": "ERROR", "reasoning": f"HTTP {r.status_code}"})

    except Exception as e:
        print(f"  Failed: {e}")
        for m in batch:
            results_all.append({**m, "nadh_oxidase_like": "ERROR", "reasoning": str(e)})

    time.sleep(1)  # Brief pause between batches

# === RESULTS ===
elapsed = time.time() - start_time
print(f"\n{'='*70}")
print(f"RESULTS: 100 Nanomaterials NADH Oxidase-Like Activity")
print(f"Time: {elapsed:.0f}s")
print(f"{'='*70}")

# Summary by category
from collections import Counter
cat_counts = Counter()
cat_nadh = Counter()
for r in results_all:
    cat = r["size_category"]
    cat_counts[cat] += 1
    if r["nadh_oxidase_like"] == "YES":
        cat_nadh[cat] += 1

print("\n=== BY SIZE CATEGORY ===")
print(f"{'Category':<20} {'Total':<8} {'NADH+':<8} {'Rate'}")
for cat in ["single_atom", "dual_atom", "nanocluster", "nanoparticle"]:
    total = cat_counts.get(cat, 0)
    nadh = cat_nadh.get(cat, 0)
    rate = f"{nadh/total*100:.0f}%" if total > 0 else "N/A"
    print(f"{cat:<20} {total:<8} {nadh:<8} {rate}")

yes_count = sum(1 for r in results_all if r["nadh_oxidase_like"] == "YES")
no_count = sum(1 for r in results_all if r["nadh_oxidase_like"] == "NO")
print(f"\nNADH+: {yes_count}/{len(results_all)} ({yes_count/len(results_all)*100:.0f}%)")
print(f"NADH-: {no_count}/{len(results_all)} ({no_count/len(results_all)*100:.0f}%)")

# Save detailed results
output_file = RUN_DIR / f"nadh_100_batch_{TS}.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump({
        "total": len(results_all),
        "nadh_positive": yes_count,
        "summary_by_category": {cat: {"total": cat_counts[cat], "nadh_positive": cat_nadh[cat]} for cat in cat_counts},
        "results": results_all
    }, f, ensure_ascii=False, indent=2)
print(f"\nDetailed results saved to: {output_file}")

# Print top NADH-positive candidates
print(f"\n=== TOP NADH-POSITIVE CANDIDATES ===")
nadh_pos = [r for r in results_all if r["nadh_oxidase_like"] == "YES"]
for r in nadh_pos[:20]:
    print(f"  {r['name'][:60]}")
    if r["reasoning"]:
        print(f"    → {r['reasoning'][:100]}")
