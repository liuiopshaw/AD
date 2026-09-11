#!/usr/bin/env python3
"""
AD100 ranking — v3 contract (user-specified 4-dimension classification).

Parses task100_cda_<TS>_part*.txt (schema v3, 14/13 cols) from the run
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
# 家族归并(2026-08-04 用户要求):同一基础治疗剂的变体分支(尺寸/核型/剂型
# 后缀,如 CuNC@beta-CD_2nm_Cu vs CuNC@beta-CD_1nm_Cu2O)折叠为一个家族,
# 排名只展示最高分的代表条目;原始行全部保留在家族下方。
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


# 疑似混合产物检测(分类独立性,2026-08-04):纳米制剂名称含小分子 API 负载词
HYBRID_API_RE = re.compile(
    r"quercetin|curcumin|resveratrol|EGCG|epicatechin|kaempferol|luteolin|ferulic|"
    r"caffeine|astaxanthin|lycopene|zeaxanthin|trolox|coQ10|sulforaphane|ginsenoside|"
    r"dopamine|melatonin|vitamin|donepezil|memantine", re.IGNORECASE)

DIMS = [
    ("Drug_Type", schema_v2.DRUG_TYPES, "药物种类"),
    ("Target_Category", schema_v2.TARGET_CATEGORIES, "药物作用靶点"),
    ("Action_Mode", schema_v2.ACTION_MODES, "药物作用方式"),
    ("AD_Mechanism", schema_v2.AD_MECHANISMS, "AD 治疗机制"),
]

TABLE_FIELDS = ["Material_Name", "Drug_Type", "Target_Category", "Action_Mode",
                "AD_Mechanism", "Chemical_Formula", "SMILES", "Target_UniProt",
                "Ligand", "Core_Elements", "ASA_Score(1-10)",
                "Key_Features"]


def parse_records(ts: str):
    parts = sorted(find_run_dir(ts).glob(f"task100_cda_{ts}_part*.txt"))
    redos = sorted(find_run_dir(ts).glob(f"task100_cda_{ts}_redo_part*.txt"))
    # --redo-batch: task100_cda_<ts>_redo_part<N>.txt replaces the original
    # part<N>.txt (the original raw file is left on disk untouched).
    redo_ids = {m.group(1) for p in redos
                if (m := re.search(r"redo_part(\d+)\.txt$", p.name))}
    if redo_ids:
        parts = [p for p in parts
                 if not ((m := re.search(r"_part(\d+)\.txt$", p.name))
                         and m.group(1) in redo_ids)]
        parts += redos
    if not parts:
        raise SystemExit(f"No task100_cda_{ts}_part*.txt found in {find_run_dir(ts)}")
    recs, unparsed, prose = [], [], 0
    for p in parts:
        for line in p.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            if "|" not in line:
                prose += 1  # CDA preamble/chatter lines — not records
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
        candidates = (list(OUTPUT_ROOT.glob("run_*/task100_cda_*_part1.txt"))
                      + list(OUTPUT_ROOT.glob("task100_cda_*_part1.txt")))
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        ts = re.search(r"task100_cda_(\d+)_part1", latest.name).group(1)

    recs, unparsed, sources, prose = parse_records(ts)

    payload = load_subscores(ts)
    asa_map, rubric = (None, None)
    if payload:
        rubric, asa_map = compute_asa_map(payload, args.rubric)
    mech_bonus = (rubric or {}).get("mechanism_bonus", {})
    pattern_bonus = (rubric or {}).get("pattern_bonus", [])

    def bonus_of(rec):
        b = mech_bonus.get(rec.get("AD_Mechanism", ""), 0.0)
        for pb in pattern_bonus:
            if re.search(pb["regex"], rec.get(NAME, "")):
                b += pb["bonus"]
        return b

    def sort_key(rec):
        bonus = bonus_of(rec)
        if asa_map is not None:
            res = asa_map.get(rec[NAME])
            if res is not None:
                return res["total_adj"] + bonus
            return float("-inf")  # no subscores -> sink to bottom
        v = asa_float(rec)
        return (v if v == v else float("-inf")) + bonus

    ranked = sorted(recs, key=sort_key, reverse=True)
    families = group_families(ranked, sort_key)  # [(representative, variants)]

    out = find_run_dir(ts)
    lines = []
    A = lines.append
    A(f"# AD100 候选药物四维分类排名(运行 {ts})")
    A("")
    A("> 本文由 `scripts/rank_ad100.py` 机械生成,agent 原始输出逐字保留,未做任何改写。")
    A("> **家族归并**:同一基础治疗剂的变体分支(尺寸/核型/剂型后缀)折叠为一个家族,排名按家族计,代表条目为家族内最高分者,变体以 ↳ 缩进列于其下。")
    if asa_map is not None:
        A(f"> **主排序键: ASA_Adj(确定性计算, rubric v{rubric.get('version')};`--rubric` 可换规则对历史子分纯重算)。** ASA_SelfReport 为 CDA 自报分,仅展示。")
    else:
        A("> 主排序键: CDA 自报 ASA_Score(本运行无 subscores)。")
    if mech_bonus:
        A(f"> 机制加分(rubric mechanism_bonus): {', '.join(f'{k} +{v}' for k, v in mech_bonus.items())} —— 排序键 = ASA_Adj + 加分。")
    if pattern_bonus:
        for pb in pattern_bonus:
            A(f"> 模式加分(rubric pattern_bonus): {pb['label']} —— Material_Name 匹配 `{pb['regex']}` 的候选 +{pb['bonus']}。")
    A(f"> 来源文件: {', '.join(sources)}")
    A("")
    A(f"- 候选总数: **{len(ranked)}**(未解析 {len(unparsed)} 行;另有 CDA 散文噪声行 {prose} 条,不计入)")
    A(f"- 唯一候选(按 Material_Name 去重): **{len({r.get(NAME, '') for r in ranked})}** —— 重复行逐字保留展示,未删除")
    A(f"- **基础治疗剂数(家族归并后): {len(families)}**(原始行 {len(ranked)} 条;变体分支已折叠)")
    # 两组分限制检查(2026-08-05):复合物一律归纳米制剂,但候选名称含
    # ≥2 个不同 API 词 = 三元及以上组合(载体+双负载),违规。
    def _api_hits(n):
        return {m.group(0).lower() for m in HYBRID_API_RE.finditer(n)}
    over2 = [r.get(NAME, "") for r in ranked if len(_api_hits(r.get(NAME, ""))) >= 2]
    if over2:
        A(f"- ⚠ 超两组分(三元及以上)违规: **{len(over2)}** 条 —— {', '.join(over2[:8])}")
    else:
        A("- 两组分限制检查: **0 条违规**(复合物均归入纳米制剂)")
    A("")

    # ---- 4-dimension distributions ----
    A("## 四维分类分布(用户指定分类体系)")
    A("")
    for field, enum, label in DIMS:
        cnt = Counter(r.get(field, "") for r in ranked)
        A(f"### {label}({field})")
        A("")
        A("| 类别 | 数量(占比) |")
        A("|---|---|")
        for v in enum:
            c = cnt.get(v, 0)
            A(f"| {v} | **{c} ({c * 100 // max(len(ranked), 1)}%)** |")
        off = {k: v for k, v in cnt.items() if k not in enum}
        if off:
            A(f"| ⚠ 枚举外(模型未守约束) | {sum(off.values())}: {', '.join(f'{k}×{v}' for k, v in sorted(off.items(), key=lambda x: -x[1]))} |")
        A("")

    # ---- Top-20 mechanism profile (高分区机制构成,按家族代表计) ----
    top20 = Counter(rep.get("AD_Mechanism", "") for rep, _ in families[:20])
    A("## 高分区(Top 20 家族)AD 机制构成")
    A("")
    A("| AD_Mechanism | 数量 |")
    A("|---|---|")
    for mech, c in top20.most_common():
        A(f"| {mech} | **{c}** |")
    A("")

    # ---- Full ranking (family-collapsed) ----
    A("## 完整排名(按基础治疗剂家族)")
    A("")
    header = ["Rank"] + TABLE_FIELDS
    header.insert(9, "Bonus")
    if asa_map is not None:
        header.insert(10, ASA_ADJ)
        header[header.index(ASA_SCORE_COL)] = SELF_REPORT
    A("| " + " | ".join(header) + " |")
    A("|" + "---|" * len(header))

    def _row(prefix, r):
        row = [prefix] + [str(r.get(f, "")) for f in TABLE_FIELDS]
        row.insert(9, f"+{bonus_of(r):.1f}" if bonus_of(r) else "—")
        if asa_map is not None:
            res = asa_map.get(r[NAME])
            row.insert(10, f"{res['total_adj']:.3f}" if res else "—")
        return "| " + " | ".join(row) + " |"

    for i, (rep, variants) in enumerate(families, 1):
        A(_row(str(i), rep))
        for v in variants:
            A(_row("↳", v))
    A("")
    if unparsed:
        A("## 未解析行(原样保留)")
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
        ws.title = "排名(家族代表)"
        ws.append(header)
        for i, (rep, variants) in enumerate(families, 1):
            row = [i] + [rep.get(f, "") for f in TABLE_FIELDS]
            row.insert(9, round(bonus_of(rep), 1) if bonus_of(rep) else None)
            if asa_map is not None:
                res = asa_map.get(rep[NAME])
                row.insert(10, round(res["total_adj"], 3) if res else None)
            ws.append(row)
        wsv = wb.create_sheet("变体明细")
        wsv.append(["家族代表", "变体名称"])
        for rep, variants in families:
            for v in variants:
                wsv.append([rep.get(NAME, ""), v.get(NAME, "")])
        ws2 = wb.create_sheet("四维分布")
        for field, enum, label in DIMS:
            cnt = Counter(r.get(field, "") for r in ranked)
            ws2.append([f"{label} ({field})", "数量", "占比"])
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
