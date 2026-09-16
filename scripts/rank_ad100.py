#!/usr/bin/env python3
"""
AD100 ranking — v3 contract (user-specified 4-dimension classification).

Parses task100_designer_<TS>_part*.txt (schema v3, 14/13 cols) from the run
directory, sorts by deterministic ASA_Adj when subscores_<TS>.json exists
(extract_subscores.py + asa_scoring.py, --rubric to re-score with a different
rubric WITHOUT re-running agents), and reports the four classification
distributions:
  1. Drug_Type        (nano_formulation/biologic/small_molecule/other)
  2. Target_Category  (gut_targeted_regulation/.../epigenetic_regulation)
  3. Action_Mode      (microbiota_ratio_modulation/.../active_substance_delivery)
  4. AD_Mechanism     (gut_microbiome_axis/.../synaptic_function_modulation)

Outputs ranking_ad100_<TS>.md and ranking_ad100_<TS>.xlsx in the run dir.
Agent output is never rewritten (CLAUDE.md iron rule) — ranking is mechanical.

Usage: python scripts/rank_ad100.py [timestamp] [--rubric path]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import schema_v2
import asa_scoring
from output_utils import find_run_dir, OUTPUT_ROOT
from rank_cda_outputs import load_subscores, compute_asa_map, SELF_REPORT, ASA_ADJ

NAME = "Material_Name"
ASA = "ASA_Score(1-10)"
ASA_SCORE_COL = ASA  # column renamed to ASA_SelfReport in ASA_Adj mode

# ---------------------------------------------------------------------------
# Family collapsing (requested by the user on 2026-08-04): variant branches
# of the same base therapeutic (size/core-type/dosage-form suffixes, e.g.
# CuNC@beta-CD_2nm_Cu vs CuNC@beta-CD_1nm_Cu2O) are folded into one family;
# the ranking shows only the highest-scoring representative entry, with all
# original rows kept below the family.
# ---------------------------------------------------------------------------
_SIZE_TOKEN_RE = re.compile(r"_?\d+(?:\.\d+)?\s*nm", re.IGNORECASE)
_FORMULA_TOKEN_RE = re.compile(r"^([A-Z][a-z]?\d*)+$")


def family_key(name: str) -> str:
    """Normalize a candidate name to its base-therapeutic family key."""
    k = _SIZE_TOKEN_RE.sub("", name)
    parts = [p for p in re.split(r"[_\s]+", k) if p]
    # drop trailing pure-formula tokens (Cu, CuO, Cu2O, Fe3O4...)
    while len(parts) > 1 and _FORMULA_TOKEN_RE.match(parts[-1]):
        parts.pop()
    return "_".join(parts).strip("_- ") or name


def group_families(ranked: list, key_fn) -> list:
    """[(rep_record, [variant_records...])] ordered by representative sort key."""
    fams = {}
    for r in ranked:
        fams.setdefault(family_key(r.get(NAME, "")), []).append(r)
    groups = []
    for members in fams.values():
        members.sort(key=key_fn, reverse=True)
        groups.append((members[0], members[1:]))
    groups.sort(key=lambda g: key_fn(g[0]), reverse=True)
    return groups


# Suspected hybrid-product detection (classification independence, 2026-08-04):
# nano formulation name contains small-molecule API payload words
HYBRID_API_RE = re.compile(
    r"quercetin|curcumin|resveratrol|EGCG|epicatechin|kaempferol|luteolin|ferulic|"
    r"caffeine|astaxanthin|lycopene|zeaxanthin|trolox|coQ10|sulforaphane|ginsenoside|"
    r"dopamine|melatonin|vitamin|donepezil|memantine", re.IGNORECASE)

DIMS = [
    ("Drug_Type", schema_v2.DRUG_TYPES, "Drug Type"),
    ("Target_Category", schema_v2.TARGET_CATEGORIES, "Drug Target"),
    ("Action_Mode", schema_v2.ACTION_MODES, "Drug Action Mode"),
    ("AD_Mechanism", schema_v2.AD_MECHANISMS, "AD Therapeutic Mechanism"),
]

TABLE_FIELDS = ["Material_Name", "Drug_Type", "Target_Category", "Action_Mode",
                "AD_Mechanism", "Chemical_Formula", "SMILES", "Target_UniProt",
                "Ligand", "Core_Elements", "ASA_Score(1-10)",
                "Key_Features"]


def parse_records(ts: str):
    parts = sorted(find_run_dir(ts).glob(f"task100_designer_{ts}_part*.txt"))
    redos = sorted(find_run_dir(ts).glob(f"task100_designer_{ts}_redo_part*.txt"))
    # --redo-batch: task100_designer_<ts>_redo_part<N>.txt replaces the original
    # part<N>.txt (the original raw file is left on disk untouched).
    redo_ids = {m.group(1) for p in redos
                if (m := re.search(r"redo_part(\d+)\.txt$", p.name))}
    if redo_ids:
        parts = [p for p in parts
                 if not ((m := re.search(r"_part(\d+)\.txt$", p.name))
                         and m.group(1) in redo_ids)]
        parts += redos
    if not parts:
        raise SystemExit(f"No task100_designer_{ts}_part*.txt found in {find_run_dir(ts)}")
    recs, unparsed, prose = [], [], 0
    for p in parts:
        for line in p.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            if "|" not in line:
                prose += 1  # designer preamble/chatter lines — not records
                continue
            cells = [c.strip() for c in line.split("|")]
            if "Material_Name" in cells[0]:
                continue
            r = schema_v2.parse_record_v3(cells)
            (recs.append(r) if r else unparsed.append(line[:100]))
    return recs, unparsed, [p.name for p in parts], prose


def asa_float(rec):
    try:
        return float(rec.get(ASA, ""))
    except (TypeError, ValueError):
        return float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ts", nargs="?", help="run timestamp (default: latest AD100/v3 run)")
    ap.add_argument("--rubric", help="asa_rubric.json path — re-score saved subscores")
    args = ap.parse_args()

    ts = args.ts
    if ts is None:
        candidates = (list(OUTPUT_ROOT.glob("run_*/task100_designer_*_part1.txt"))
                      + list(OUTPUT_ROOT.glob("task100_designer_*_part1.txt")))
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        ts = re.search(r"task100_designer_(\d+)_part1", latest.name).group(1)

    recs, unparsed, sources, prose = parse_records(ts)

    payload = load_subscores(ts)
    asa_map, rubric = (None, None)
    if payload:
        rubric, asa_map = compute_asa_map(payload, args.rubric)

    def sort_key(rec):
        # No subjective bonuses: ranking is pure ASA_Adj (deterministic
        # weighted subscores + Cj consistency), or designer self-report when a run
        # has no subscores.
        if asa_map is not None:
            res = asa_map.get(rec[NAME])
            if res is not None:
                return res["total_adj"]
            return float("-inf")  # no subscores -> sink to bottom
        v = asa_float(rec)
        return v if v == v else float("-inf")

    ranked = sorted(recs, key=sort_key, reverse=True)
    families = group_families(ranked, sort_key)  # [(representative, variants)]

    out = find_run_dir(ts)
    lines = []
    A = lines.append
    A(f"# AD100 Candidate Drug Four-Dimension Classification Ranking (run {ts})")
    A("")
    A("> This document was mechanically generated by `scripts/rank_ad100.py`; the agents' raw output is preserved verbatim, with no rewriting.")
    A("> **Family collapsing**: variant branches of the same base therapeutic (size/core-type/dosage-form suffixes) are folded into one family; ranking is counted per family, the representative entry is the highest-scoring member of the family, and variants are listed below it indented with ↳.")
    if asa_map is not None:
        A(f"> **Primary sort key: ASA_Adj (deterministic computation, rubric v{rubric.get('version')}; `--rubric` re-scores historical subscores with a different rule set).** ASA_SelfReport is the designer self-reported score, shown for display only.")
    else:
        A("> Primary sort key: designer self-reported ASA_Score (no subscores in this run).")
    A(f"> Source files: {', '.join(sources)}")
    A("")
    A(f"- Total candidates: **{len(ranked)}** ({len(unparsed)} lines unparsed; plus {prose} designer prose-noise lines, not counted)")
    A(f"- Unique candidates (deduplicated by Material_Name): **{len({r.get(NAME, '') for r in ranked})}** —— duplicate rows are kept and shown verbatim, not deleted")
    A(f"- **Base therapeutics (after family collapsing): {len(families)}** ({len(ranked)} original rows; variant branches folded)")
    # Two-agent limit check (2026-08-05): composites are always classified as
    # nano_formulation, but a candidate name containing >=2 distinct API words
    # = a ternary-or-higher combination (carrier + dual payload), a violation.
    def _api_hits(n):
        return {m.group(0).lower() for m in HYBRID_API_RE.finditer(n)}
    over2 = [r.get(NAME, "") for r in ranked if len(_api_hits(r.get(NAME, ""))) >= 2]
    if over2:
        A(f"- ⚠ Over-two-agent (ternary or higher) violations: **{len(over2)}** —— {', '.join(over2[:8])}")
    else:
        A("- Two-agent limit check: **0 violations** (all composites classified as nano_formulation)")
    A("")

    # ---- 4-dimension distributions ----
    A("## Four-Dimension Classification Distributions (user-specified taxonomy)")
    A("")
    for field, enum, label in DIMS:
        cnt = Counter(r.get(field, "") for r in ranked)
        A(f"### {label}({field})")
        A("")
        A("| Category | Count (share) |")
        A("|---|---|")
        for v in enum:
            c = cnt.get(v, 0)
            A(f"| {v} | **{c} ({c * 100 // max(len(ranked), 1)}%)** |")
        off = {k: v for k, v in cnt.items() if k not in enum}
        if off:
            A(f"| ⚠ Off-enum (model violated the constraint) | {sum(off.values())}: {', '.join(f'{k}×{v}' for k, v in sorted(off.items(), key=lambda x: -x[1]))} |")
        A("")

    # ---- Top-20 mechanism profile (high-score region composition, counted by family representatives) ----
    top20 = Counter(rep.get("AD_Mechanism", "") for rep, _ in families[:20])
    A("## AD Mechanism Composition of the High-Score Region (Top 20 Families)")
    A("")
    A("| AD_Mechanism | Count |")
    A("|---|---|")
    for mech, c in top20.most_common():
        A(f"| {mech} | **{c}** |")
    A("")

    # ---- Full ranking (family-collapsed) ----
    A("## Full Ranking (by Base Therapeutic Family)")
    A("")
    header = ["Rank"] + TABLE_FIELDS
    if asa_map is not None:
        header.insert(9, ASA_ADJ)
        header[header.index(ASA_SCORE_COL)] = SELF_REPORT
    A("| " + " | ".join(header) + " |")
    A("|" + "---|" * len(header))

    def _row(prefix, r):
        row = [prefix] + [str(r.get(f, "")) for f in TABLE_FIELDS]
        if asa_map is not None:
            res = asa_map.get(r[NAME])
            row.insert(9, f"{res['total_adj']:.3f}" if res else "—")
        return "| " + " | ".join(row) + " |"

    for i, (rep, variants) in enumerate(families, 1):
        A(_row(str(i), rep))
        for v in variants:
            A(_row("↳", v))
    A("")
    if unparsed:
        A("## Unparsed Lines (kept verbatim)")
        A("")
        for u in unparsed:
            A(f"- `{u}`")

    md_path = out / f"ranking_ad100_{ts}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {md_path} ({len(ranked)} ranked, {len(unparsed)} unparsed, {prose} prose-noise"
          f"{', mode: ASA_Adj rubric v' + str(rubric.get('version')) if asa_map is not None else ', mode: self-report'})")

    # ---- xlsx ----
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Ranking (family reps)"
        ws.append(header)
        for i, (rep, variants) in enumerate(families, 1):
            row = [i] + [rep.get(f, "") for f in TABLE_FIELDS]
            if asa_map is not None:
                res = asa_map.get(rep[NAME])
                row.insert(9, round(res["total_adj"], 3) if res else None)
            ws.append(row)
        wsv = wb.create_sheet("Variant Details")
        wsv.append(["Family Representative", "Variant Name"])
        for rep, variants in families:
            for v in variants:
                wsv.append([rep.get(NAME, ""), v.get(NAME, "")])
        ws2 = wb.create_sheet("4-Dim Distributions")
        for field, enum, label in DIMS:
            cnt = Counter(r.get(field, "") for r in ranked)
            ws2.append([f"{label} ({field})", "Count", "Share"])
            for v in enum:
                ws2.append([v, cnt.get(v, 0), cnt.get(v, 0) / max(len(ranked), 1)])
            ws2.append([])
        xlsx_path = out / f"ranking_ad100_{ts}.xlsx"
        wb.save(xlsx_path)
        print(f"Wrote {xlsx_path}")
    except ImportError:
        print("openpyxl not available — xlsx skipped")


if __name__ == "__main__":
    main()
