#!/usr/bin/env python3
"""
Rank designer-designed materials by ASA score into a Markdown document.

Mechanical compilation only: fields are preserved VERBATIM from the raw designer
output files (task100_designer_<TS>_part*.txt). The only operations are:
  - splitting pipe-separated fields
  - repairing physically fused lines (two records emitted without a newline,
    detected as 2F-1 fields; split point logged in the MD appendix)
  - normalizing legacy 9-field lines (no Chemical_Formula) to 10 fields
  - sorting by ASA score descending
No content is rewritten, cleaned, translated, or curated.

Usage: python scripts/rank_cda_outputs.py [timestamp] [--rubric path]

Phase 3: when the run directory contains subscores_<TS>.json (from
extract_subscores.py), the PRIMARY sort key is ASA_Adj — the deterministic
score from asa_scoring.py + the rubric (default scripts/asa_rubric.json,
--rubric to re-rank historical subscores with a different rubric WITHOUT
re-running any agent). The designer self-reported ASA column is kept for display,
renamed ASA_SelfReport. Without subscores the legacy self-report ranking is
used unchanged.
"""

import argparse, json, re, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from output_utils import find_run_dir, OUTPUT_ROOT
import schema_v2
import asa_scoring

OUTPUT = OUTPUT_ROOT

FIELDS = schema_v2.FIELDS_V1               # legacy 11-field format (current pipeline output)
LEGACY_FIELDS = schema_v2.LEGACY_LENGTHS   # runs before Ligand (10) / before Chemical_Formula+Ligand (9)
RECORD_LENGTHS = (*LEGACY_FIELDS, len(schema_v2.FIELDS_V1), 12, len(schema_v2.FIELDS_V2))  # 9/10/11/12(v2 minus Ligand)/13

# Ranking drops only Size_nm; SMILES / Target_UniProt are shown right after
# Chemical_Formula (Phase 4 three-modality extension). Modality (legacy records:
# Material_Category, relocated verbatim by schema_v2) is shown right after
# Material_Name per project requirement.
TABLE_FIELDS = ["Material_Name", "Modality", "Chemical_Formula", "SMILES", "Target_UniProt",
                "Ligand", "Core_Elements",
                "ASA_Score(1-10)", "Disease_Intervention", "Mechanism",
                "NADH_Activity(YES/NO)", "Key_Features"]
ASA = "ASA_Score(1-10)"
NAME = "Material_Name"
MODALITY = "Modality"
SMILES = "SMILES"
UNIPROT = "Target_UniProt"
ELEMENTS = "Core_Elements"
INTERVENTION = "Disease_Intervention"
MECHANISM = "Mechanism"
NADH = "NADH_Activity(YES/NO)"

NAME_RE = re.compile(r"[A-Z][A-Za-z0-9]*_[A-Za-z0-9_\-]*")

# Display-only column names for the deterministic-ASA ranking mode.
SELF_REPORT = "ASA_SelfReport"
ASA_ADJ = "ASA_Adj"


def _normalize(cells):
    """Legacy + v2 records -> FIELDS_V2 dict (schema_v2.normalize_record);
    None for unrecognized column counts."""
    return schema_v2.normalize_record(cells)


def load_subscores(ts: str):
    """Return the extract_subscores payload for this run, or None."""
    f = find_run_dir(ts) / f"subscores_{ts}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def compute_asa_map(payload: dict, rubric_path=None):
    """(rubric, {material_name: compute_asa result}) from a subscores payload."""
    rubric = asa_scoring.load_rubric(rubric_path or asa_scoring.DEFAULT_RUBRIC)
    return rubric, {name: asa_scoring.compute_asa(axes, rubric)
                    for name, axes in payload.get("materials", {}).items()}


def parse_records(ts: str):
    parts = sorted(find_run_dir(ts).glob(f"task100_designer_{ts}_part*.txt"))
    if not parts:
        raise SystemExit(f"No task100_designer_{ts}_part*.txt found in {find_run_dir(ts)}")

    records, fused, bad = [], [], []
    for p in parts:
        text = p.read_text(encoding="utf-8")
        for line in text.split("\n"):
            line = line.strip()
            if not line or "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            if len(cells) in RECORD_LENGTHS:
                rec = _normalize(cells)
                if rec is not None:
                    records.append(rec)
                else:
                    bad.append((p.name, line))
            elif len(cells) in (2 * len(FIELDS) - 1, 2 * len(schema_v2.FIELDS_V2) - 1, 19, 17):
                # Two records fused on one physical line: the glue cell holds
                # "<featuresA><nameB>". Split at the last name-like token.
                glue_idx = (len(cells) + 1) // 2 - 1
                m = list(NAME_RE.finditer(cells[glue_idx]))
                if m:
                    cut = m[-1].start()
                    rec_a = cells[:glue_idx] + [cells[glue_idx][:cut].strip()]
                    rec_b = [cells[glue_idx][cut:].strip()] + cells[glue_idx + 1:]
                    for rec in (_normalize(rec_a), _normalize(rec_b)):
                        if rec is not None:
                            records.append(rec)
                        else:
                            bad.append((p.name, line))
                    fused.append((p.name, cells[glue_idx]))
                else:
                    bad.append((p.name, line))
            else:
                bad.append((p.name, line))
    return [p.name for p in parts], records, fused, bad


def main():
    parser = argparse.ArgumentParser(description="Rank designer outputs (deterministic ASA when subscores exist)")
    parser.add_argument("ts", nargs="?", help="run timestamp (default: latest)")
    parser.add_argument("--rubric", default=None,
                        help="ASA rubric JSON (default: scripts/asa_rubric.json); "
                             "re-ranks historical subscores without re-running agents")
    args = parser.parse_args()
    ts = args.ts
    if ts is None:
        candidates = (list(OUTPUT.glob("task100_designer_*_part1.txt"))
                      + list(OUTPUT.glob("run_*/task100_designer_*_part1.txt")))
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        ts = re.search(r"task100_designer_(\d+)_part1", latest.name).group(1)

    src_files, records, fused, bad = parse_records(ts)

    # Phase 3: deterministic ASA from extracted subscores, if present.
    sub_payload = load_subscores(ts)
    rubric, asa_map = (None, {})
    if sub_payload is not None:
        rubric, asa_map = compute_asa_map(sub_payload, args.rubric)

    def asa(rec):
        try:
            return float(rec[ASA])
        except ValueError:
            return float("nan")

    valid = [r for r in records if asa(r) == asa(r)]  # drop NaN ASA
    nan_asa = [r for r in records if asa(r) != asa(r)]
    if asa_map:
        # Primary key: deterministic ASA_Adj; materials without extracted
        # subscores sink to the bottom (nothing is invented for them).
        valid.sort(key=lambda r: (-asa_map[r[NAME]]["total_adj"], r[NAME])
                   if r[NAME] in asa_map else (float("inf"), r[NAME]))
    else:
        valid.sort(key=lambda r: (-asa(r), r[NAME]))

    nadh_yes = sum(1 for r in valid if r[NADH].strip().upper() == "YES")

    def esc(s):
        return s.replace("|", "\\|")

    out = []
    # Database-verified formulas (tool data, NOT agent output) — present when
    # scripts/formula_lookup.py has been run for this timestamp.
    db_map, db_source = {}, None
    map_file = OUTPUT / f"task100_formula_map_{ts}.json"
    if map_file.exists():
        import json as _json
        payload = _json.loads(map_file.read_text(encoding="utf-8"))
        db_map = payload.get("materials", {})
        db_source = payload.get("source")

    out.append(f"# Material ASA ranking summary (run {ts})\n")
    out.append("> This document was mechanically generated by `scripts/rank_cda_outputs.py`.")
    if asa_map:
        out.append(f"> **Primary sort key: ASA_Adj (deterministically computed, rubric v{rubric.get('version')}, scripts/asa_scoring.py; `--rubric` re-computes historical subscores with a different rubric without re-running any agent).**")
        out.append("> ASA_SelfReport is the designer self-reported ASA_Score, shown for display only and not used for sorting. Subscores come from the JSON tail of the raw manufacturing/delivery/safety/mechanism outputs (mechanically extracted by scripts/extract_subscores.py).")
    else:
        out.append("> All fields are preserved **verbatim** from the raw designer agent output, sorted only by ASA score descending, with no content rewriting, cleaning, or curation.")
    out.append("> Per project goals, the ranking drops only the size value (Size_nm); the material category (Modality, relocated verbatim from Material_Category for legacy records) is kept for display.")
    if db_map:
        out.append(f"> The DB_Formula column is the database-tool verification result (source: {db_source}, scripts/formula_lookup.py), not agent output; the Chemical_Formula column remains the raw agent output.")
    out.append(f"> Source files: {', '.join(src_files)}\n")

    # ---- Target metric: Cu x direct_antibacterial x microbiome_remodeling ----
    cu = [r for r in valid if "Cu" in [e.strip() for e in r[ELEMENTS].split(",")]]
    da = [r for r in valid if r[INTERVENTION] == "direct_antibacterial"]
    mr = [r for r in valid if r[MECHANISM] == "microbiome_remodeling"]
    cu_da = [r for r in cu if r[INTERVENTION] == "direct_antibacterial"]
    cu_mr = [r for r in cu if r[MECHANISM] == "microbiome_remodeling"]
    cu_both = [r for r in cu if r[INTERVENTION] == "direct_antibacterial" and r[MECHANISM] == "microbiome_remodeling"]
    pct = lambda x: f"{len(x)} ({len(x)/len(valid)*100:.0f}%)" if valid else "0"

    out.append(f"- Total materials: **{len(valid)}**")
    out.append(f"- NADH activity YES: **{nadh_yes}** ({nadh_yes/len(valid)*100:.0f}%)" if valid else "")
    out.append(f"- ASA range: {asa(valid[-1])} - {asa(valid[0])}" if valid else "")
    if asa_map:
        adj = [asa_map[r[NAME]]["total_adj"] for r in valid if r[NAME] in asa_map]
        out.append(f"\n- ASA_Adj range: {min(adj):.3f} - {max(adj):.3f} (rubric v{rubric.get('version')})" if adj else "")
    out.append("")
    out.append("## Target metric (Cu x direct antibacterial x microbiome remodeling)\n")
    out.append("| Metric | Count (share) |")
    out.append("|---|---|")
    out.append(f"| Cu-based materials | **{pct(cu)}** |")
    out.append(f"| direct_antibacterial (all) | {pct(da)} |")
    out.append(f"| microbiome_remodeling (all) | {pct(mr)} |")
    out.append(f"| Cu ∩ direct_antibacterial | **{pct(cu_da)}** |")
    out.append(f"| Cu ∩ microbiome_remodeling | **{pct(cu_mr)}** |")
    out.append(f"| Cu with both | **{pct(cu_both)}** |")

    # Element frequency across the full ranking — verify Cu is near the top but not artificially dominant (project goal)
    all_elem = Counter()
    for r in valid:
        for e in r[ELEMENTS].split(","):
            e = e.strip()
            if e and e not in ("O", "N", "C"):
                all_elem[e] += 1
    out.append(f"| Element frequency Top8 (excl. O/N/C, per material) | {', '.join(f'{e}x{n}' for e, n in all_elem.most_common(8))} |")

    # Element frequency within the both-metric set — verify whether Cu is the most frequent element (project goal)
    both_set = [r for r in valid if r[INTERVENTION] == "direct_antibacterial" and r[MECHANISM] == "microbiome_remodeling"]
    elem_freq = Counter()
    for r in both_set:
        for e in r[ELEMENTS].split(","):
            e = e.strip()
            if e and e != "O":
                elem_freq[e] += 1
    top_elems = ", ".join(f"{e}×{n}" for e, n in elem_freq.most_common(6))
    cu_is_top = bool(elem_freq) and elem_freq.get("Cu", 0) == elem_freq.most_common(1)[0][1]
    out.append(f"| Element frequency in both-metric set (excl. O, per material) | {top_elems} |")
    out.append(f"| Cu is the most frequent element in both-metric set | **{'YES' if cu_is_top else 'NO'}** |\n")

    # ---- Phase 4: three-modality coverage metrics ----
    mod_freq = Counter(r[MODALITY].strip() for r in valid)
    mech_freq = Counter(r[MECHANISM].strip() for r in valid)
    smiles_ok = sum(1 for r in valid if r[SMILES].strip() not in ("", "NA"))
    uniprot_ok = sum(1 for r in valid if r[UNIPROT].strip() not in ("", "NA"))

    out.append("## Three-modality statistics (Phase 4)\n")
    out.append("| Metric | Value |")
    out.append("|---|---|")
    out.append("| Modality distribution | " + ", ".join(f"{m}x{mod_freq.get(m, 0)}" for m in schema_v2.MODALITIES) + " |")
    out.append("| Mechanism distribution | " + ", ".join(f"{k}x{v}" for k, v in mech_freq.most_common()) + " |")
    out.append(f"| SMILES not NA | **{smiles_ok}** |")
    out.append(f"| Target_UniProt not NA | **{uniprot_ok}** |\n")

    out.append("## Full ranking\n")
    db_pos = TABLE_FIELDS.index("Chemical_Formula") + 1  # DB_Formula after Chemical_Formula
    # In deterministic-ASA mode the self-report column is renamed and the
    # computed ASA_Adj column is inserted right before it.
    base_cols = []
    for f in TABLE_FIELDS:
        if asa_map and f == ASA:
            base_cols += [ASA_ADJ, SELF_REPORT]
        else:
            base_cols.append(f)
    cols = base_cols[:db_pos] + (["DB_Formula"] if db_map else []) + base_cols[db_pos:]
    out.append("| Rank | " + " | ".join(cols) + " |")
    out.append("|" + "---|" * (len(cols) + 1))
    for i, r in enumerate(valid, 1):
        cells = []
        for f in TABLE_FIELDS:
            if asa_map and f == ASA:
                res = asa_map.get(r[NAME])
                cells.append(f"{res['total_adj']:.3f}" if res else "—")
                cells.append(esc(r[ASA]))
            else:
                cells.append(esc(r[f]))
        if db_map:
            dbv = (db_map.get(r[NAME]) or {}).get("combined_formula") or "—"
            cells = cells[:db_pos] + [dbv] + cells[db_pos:]
        out.append(f"| {i} | " + " | ".join(cells) + " |")

    # ---- Phase 4: Top-5 per modality (primary sort key — `valid` is already sorted) ----
    out.append("\n## Top5 grouped by Modality (primary sort key)\n")
    observed = list(schema_v2.MODALITIES) + sorted(
        {r[MODALITY].strip() for r in valid} - set(schema_v2.MODALITIES))
    for m in observed:
        group = [r for r in valid if r[MODALITY].strip() == m][:5]
        if not group:
            continue
        out.append(f"### {m}\n")
        out.append("| # | Material_Name | " + (ASA_ADJ if asa_map else ASA) + " |")
        out.append("|---|---|---|")
        for j, r in enumerate(group, 1):
            if asa_map:
                res = asa_map.get(r[NAME])
                score = f"{res['total_adj']:.3f}" if res else "—"
            else:
                score = esc(r[ASA])
            out.append(f"| {j} | {esc(r[NAME])} | {score} |")
        out.append("")

    if asa_map:
        no_sub = [r[NAME] for r in valid if r[NAME] not in asa_map]
        partial = [(n, asa_map[n]["missing"]) for n in dict.fromkeys(r[NAME] for r in valid)
                   if n in asa_map and asa_map[n]["missing"]]
        n_extract_missing = len(sub_payload.get("missing", []))
        if no_sub or partial or n_extract_missing:
            out.append("\n---\n\n## Appendix: missing ASA subscores (counted as 0, never fabricated)\n")
            if no_sub:
                out.append(f"### Materials with no extracted subscores ({len(no_sub)}, listed at the bottom)\n")
                for n in no_sub:
                    out.append(f"- {esc(n)}")
            if partial:
                out.append(f"\n### Partial subscore coverage ({len(partial)} materials, missing dims counted as 0)\n")
                for n, miss in partial:
                    out.append(f"- {esc(n)}: {', '.join(miss)}")
            if n_extract_missing:
                out.append(f"\n### Extraction-failed lines ({n_extract_missing}, see the missing field in subscores_{ts}.json)")

    if fused or bad or nan_asa:
        out.append("\n---\n\n## Appendix: format anomalies\n")
        if fused:
            out.append(f"### Fused-line repairs ({len(fused)})\n")
            out.append("Two materials were fused onto one line in the raw output; they were mechanically split at the last material-name marker without changing content. Original fused fields:\n")
            for fname, cell in fused:
                out.append(f"- `{fname}`: …{esc(cell)}")
        if nan_asa:
            out.append(f"\n### Unparseable ASA scores ({len(nan_asa)}, excluded from ranking)\n")
            for r in nan_asa:
                out.append("- " + esc(" | ".join(r[f] for f in schema_v2.FIELDS_V2)))
        if bad:
            out.append(f"\n### Unparseable lines ({len(bad)}, preserved verbatim)\n")
            for fname, line in bad:
                out.append(f"- `{fname}`: {esc(line)}")

    md_path = find_run_dir(ts) / f"ranking_{ts}.md"
    md_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    mode = f"ASA_Adj rubric v{rubric.get('version')}" if asa_map else "self-report fallback (no subscores)"
    print(f"Wrote {md_path} ({len(valid)} ranked materials, {len(fused)} fused repairs, {len(bad)} unparsed; mode: {mode})")


if __name__ == "__main__":
    main()
