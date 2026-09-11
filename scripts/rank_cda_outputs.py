#!/usr/bin/env python3
"""
Rank CDA-designed materials by ASA score into a Markdown document.

Mechanical compilation only: fields are preserved VERBATIM from the raw CDA
output files (task100_cda_<TS>_part*.txt). The only operations are:
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
re-running any agent). The CDA self-reported ASA column is kept for display,
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
    parts = sorted(find_run_dir(ts).glob(f"task100_cda_{ts}_part*.txt"))
    if not parts:
        raise SystemExit(f"No task100_cda_{ts}_part*.txt found in {find_run_dir(ts)}")

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
    parser = argparse.ArgumentParser(description="Rank CDA outputs (deterministic ASA when subscores exist)")
    parser.add_argument("ts", nargs="?", help="run timestamp (default: latest)")
    parser.add_argument("--rubric", default=None,
                        help="ASA rubric JSON (default: scripts/asa_rubric.json); "
                             "re-ranks historical subscores without re-running agents")
    args = parser.parse_args()
    ts = args.ts
    if ts is None:
        candidates = (list(OUTPUT.glob("task100_cda_*_part1.txt"))
                      + list(OUTPUT.glob("run_*/task100_cda_*_part1.txt")))
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        ts = re.search(r"task100_cda_(\d+)_part1", latest.name).group(1)

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

    out.append(f"# 材料 ASA 排名汇总(运行 {ts})\n")
    out.append("> 本文档由 `scripts/rank_cda_outputs.py` 机械生成。")
    if asa_map:
        out.append(f"> **主排序键: ASA_Adj(确定性计算, rubric v{rubric.get('version')}, scripts/asa_scoring.py;`--rubric` 可换规则对历史子分纯重算,不重跑 agent)。**")
        out.append("> ASA_SelfReport 为 CDA 自报 ASA_Score,仅展示,不参与排序。子分来自 APA/EPA/BSA/MMA 原始输出的 JSON 尾(scripts/extract_subscores.py 机械提取)。")
    else:
        out.append("> 所有字段为 CDA agent 原始输出**逐字保留**,仅按 ASA 分数降序排列,未做任何内容改写、清洗或精选。")
    out.append("> 排名按项目目标仅去掉尺寸数值(Size_nm);材料类别(Modality,旧记录由 Material_Category 逐字迁入)保留展示。")
    if db_map:
        out.append(f"> DB_Formula 列为数据库工具查证结果(来源: {db_source}, scripts/formula_lookup.py),非 agent 输出;Chemical_Formula 列仍是 agent 原始输出。")
    out.append(f"> 来源文件: {', '.join(src_files)}\n")

    # ---- 目标指标:Cu × direct_antibacterial × microbiome_remodeling ----
    cu = [r for r in valid if "Cu" in [e.strip() for e in r[ELEMENTS].split(",")]]
    da = [r for r in valid if r[INTERVENTION] == "direct_antibacterial"]
    mr = [r for r in valid if r[MECHANISM] == "microbiome_remodeling"]
    cu_da = [r for r in cu if r[INTERVENTION] == "direct_antibacterial"]
    cu_mr = [r for r in cu if r[MECHANISM] == "microbiome_remodeling"]
    cu_both = [r for r in cu if r[INTERVENTION] == "direct_antibacterial" and r[MECHANISM] == "microbiome_remodeling"]
    pct = lambda x: f"{len(x)} ({len(x)/len(valid)*100:.0f}%)" if valid else "0"

    out.append(f"- 材料总数: **{len(valid)}**")
    out.append(f"- NADH 活性 YES: **{nadh_yes}** ({nadh_yes/len(valid)*100:.0f}%)" if valid else "")
    out.append(f"- ASA 范围: {asa(valid[-1])} – {asa(valid[0])}" if valid else "")
    if asa_map:
        adj = [asa_map[r[NAME]]["total_adj"] for r in valid if r[NAME] in asa_map]
        out.append(f"\n- ASA_Adj 范围: {min(adj):.3f} – {max(adj):.3f}(rubric v{rubric.get('version')})" if adj else "")
    out.append("")
    out.append("## 目标指标(Cu × 直接抗菌 × 重塑菌群)\n")
    out.append("| 指标 | 数量(占比) |")
    out.append("|---|---|")
    out.append(f"| Cu 基材料 | **{pct(cu)}** |")
    out.append(f"| direct_antibacterial(全部) | {pct(da)} |")
    out.append(f"| microbiome_remodeling(全部) | {pct(mr)} |")
    out.append(f"| Cu ∩ direct_antibacterial | **{pct(cu_da)}** |")
    out.append(f"| Cu ∩ microbiome_remodeling | **{pct(cu_mr)}** |")
    out.append(f"| Cu ∩ 两者兼备 | **{pct(cu_both)}** |")

    # 全榜元素频率 — 验证 Cu 处于前列但不刻意 dominant(项目目标)
    all_elem = Counter()
    for r in valid:
        for e in r[ELEMENTS].split(","):
            e = e.strip()
            if e and e not in ("O", "N", "C"):
                all_elem[e] += 1
    out.append(f"| 全榜元素频率 Top8(不含 O/N/C,按材料计) | {', '.join(f'{e}×{n}' for e, n in all_elem.most_common(8))} |")

    # 两者兼备集合的元素频率 — 验证 Cu 是否为最高频元素(项目目标)
    both_set = [r for r in valid if r[INTERVENTION] == "direct_antibacterial" and r[MECHANISM] == "microbiome_remodeling"]
    elem_freq = Counter()
    for r in both_set:
        for e in r[ELEMENTS].split(","):
            e = e.strip()
            if e and e != "O":
                elem_freq[e] += 1
    top_elems = ", ".join(f"{e}×{n}" for e, n in elem_freq.most_common(6))
    cu_is_top = bool(elem_freq) and elem_freq.get("Cu", 0) == elem_freq.most_common(1)[0][1]
    out.append(f"| 两者兼备元素频率(不含 O,按材料计) | {top_elems} |")
    out.append(f"| Cu 为两者兼备最高频元素 | **{'✅ 是' if cu_is_top else '❌ 否'}** |\n")

    # ---- Phase 4: three-modality coverage metrics ----
    mod_freq = Counter(r[MODALITY].strip() for r in valid)
    mech_freq = Counter(r[MECHANISM].strip() for r in valid)
    smiles_ok = sum(1 for r in valid if r[SMILES].strip() not in ("", "NA"))
    uniprot_ok = sum(1 for r in valid if r[UNIPROT].strip() not in ("", "NA"))

    out.append("## 三模态统计(Phase 4)\n")
    out.append("| 指标 | 值 |")
    out.append("|---|---|")
    out.append("| Modality 分布 | " + ", ".join(f"{m}×{mod_freq.get(m, 0)}" for m in schema_v2.MODALITIES) + " |")
    out.append("| Mechanism 分布 | " + ", ".join(f"{k}×{v}" for k, v in mech_freq.most_common()) + " |")
    out.append(f"| SMILES 非 NA | **{smiles_ok}** |")
    out.append(f"| Target_UniProt 非 NA | **{uniprot_ok}** |\n")

    out.append("## 完整排名\n")
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
    out.append("\n## Top5 按 Modality 分组(主排序键)\n")
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
            out.append("\n---\n\n## 附录:ASA 子分缺失(按 0 计,未编造)\n")
            if no_sub:
                out.append(f"### 无提取子分的材料({len(no_sub)} 个,列于榜尾)\n")
                for n in no_sub:
                    out.append(f"- {esc(n)}")
            if partial:
                out.append(f"\n### 部分子维度缺失({len(partial)} 个材料,缺失维度按 0 计)\n")
                for n, miss in partial:
                    out.append(f"- {esc(n)}: {', '.join(miss)}")
            if n_extract_missing:
                out.append(f"\n### 提取失败行({n_extract_missing} 条,详见 subscores_{ts}.json 的 missing 字段)")

    if fused or bad or nan_asa:
        out.append("\n---\n\n## 附录:格式异常记录\n")
        if fused:
            out.append(f"### 连行修复({len(fused)} 处)\n")
            out.append("原始输出中两个材料缺少换行连在一行,已按最后一个材料名标记机械拆分,内容未改。原始粘合字段如下:\n")
            for fname, cell in fused:
                out.append(f"- `{fname}`: …{esc(cell)}")
        if nan_asa:
            out.append(f"\n### ASA 分数不可解析({len(nan_asa)} 条,未参与排名)\n")
            for r in nan_asa:
                out.append("- " + esc(" | ".join(r[f] for f in schema_v2.FIELDS_V2)))
        if bad:
            out.append(f"\n### 无法解析的行({len(bad)} 条,逐字保留)\n")
            for fname, line in bad:
                out.append(f"- `{fname}`: {esc(line)}")

    md_path = find_run_dir(ts) / f"ranking_{ts}.md"
    md_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    mode = f"ASA_Adj rubric v{rubric.get('version')}" if asa_map else "self-report fallback (no subscores)"
    print(f"Wrote {md_path} ({len(valid)} ranked materials, {len(fused)} fused repairs, {len(bad)} unparsed; mode: {mode})")


if __name__ == "__main__":
    main()
