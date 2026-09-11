#!/usr/bin/env python3
"""
Build scripts/eval_sets/biologic_ad.json — AD-related biologics benchmark.

The seed list (approved / investigational AD antibodies and peptides) is
curated benchmark ground truth; the Target_UniProt accession for each entry
is NOT hardcoded — it is resolved live via uniprot_tool.search_gene and then
verified with uniprot_tool.get_entry. Entries whose accession cannot be
verified are dropped and logged (nothing is invented in their place).
Raw UniProt responses are dumped to outputs/run_<TS>/ for audit. Re-runnable.

Usage: python scripts/eval_sets/build_biologic_set.py
"""

import json, sys, time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR.parent / "src" / "tools"))

from output_utils import run_dir
import uniprot_tool

TS = int(time.time())
RUN_DIR = run_dir(TS)
OUT_FILE = Path(__file__).resolve().parent / "biologic_ad.json"

# name, target gene (UniProt accession resolved live), mechanism, status
SEEDS = [
    ("aducanumab",   "APP",  "amyloid_tau_direct", "approved (FDA 2021, withdrawn 2024)"),
    ("lecanemab",    "APP",  "amyloid_tau_direct", "approved (FDA 2023)"),
    ("donanemab",    "APP",  "amyloid_tau_direct", "approved (FDA 2024)"),
    ("gantenerumab", "APP",  "amyloid_tau_direct", "phase 3 (discontinued)"),
    ("crenezumab",   "APP",  "amyloid_tau_direct", "phase 3 (discontinued)"),
    ("bapineuzumab", "APP",  "amyloid_tau_direct", "phase 3 (discontinued)"),
    ("solanezumab",  "APP",  "amyloid_tau_direct", "phase 3 (failed primary endpoint)"),
    ("ponezumab",    "APP",  "amyloid_tau_direct", "phase 2 (discontinued)"),
    ("trontinemab",  "APP",  "amyloid_tau_direct", "phase 2/3 (Brainshuttle anti-Abeta)"),
    ("remternetug",  "APP",  "amyloid_tau_direct", "phase 3"),
    ("sabirnetug",   "APP",  "amyloid_tau_direct", "phase 2 (ACU193, Abeta oligomers)"),
    ("semorinemab",  "MAPT", "amyloid_tau_direct", "phase 2 (anti-tau)"),
    ("gosuranemab",  "MAPT", "amyloid_tau_direct", "phase 2 (anti-tau, BIIB092)"),
    ("tilavonemab",  "MAPT", "amyloid_tau_direct", "phase 2 (anti-tau, ABBV-8E12)"),
    ("zagotenemab",  "MAPT", "amyloid_tau_direct", "phase 2 (anti-tau, LY3303560)"),
    ("bepranemab",   "MAPT", "amyloid_tau_direct", "phase 2 (anti-tau)"),
    ("davunetide",   "MAPT", "amyloid_tau_direct", "phase 2/3 (NAP peptide, microtubule stabilizer)"),
]

raw_responses = {}


def main():
    entries, dropped = [], []
    for name, gene, mechanism, status in SEEDS:
        hits = uniprot_tool.search_gene(gene)
        raw_responses[f"search_gene:{gene}"] = hits
        if not hits:
            print(f"WARNING: gene not resolved: {gene} ({name})")
            dropped.append({"name": name, "reason": f"search_gene({gene}) no hit"})
            continue
        accession = hits[0]["accession"]
        entry = uniprot_tool.get_entry(accession)
        raw_responses[f"get_entry:{accession}"] = entry
        if not entry:
            print(f"WARNING: accession not verified: {accession} ({name})")
            dropped.append({"name": name, "reason": f"get_entry({accession}) failed"})
            continue
        entries.append({
            "name": name,
            "target_uniprot": accession,
            "mechanism": mechanism,
            "status": status,
        })
        print(f"{name:14s} -> {accession} ({entry['protein_name']})")

    print(f"\nBuilt {len(entries)} entries, {len(dropped)} dropped")
    OUT_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"-> {OUT_FILE}")

    raw_file = RUN_DIR / f"uniprot_raw_{TS}.json"
    raw_file.write_text(json.dumps(
        {"raw_responses": raw_responses, "dropped": dropped}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"-> {raw_file}")


if __name__ == "__main__":
    main()
