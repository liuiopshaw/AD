#!/usr/bin/env python3
"""
Export the anonymized ADTB/AD-TxBench 2x2 runs to a single xlsx.

Combines the four anonymized runs (LoRA/base x harness/prompt): decodes
Candidate_NNN back to real drug names via each payload's deanonymize map, and
puts preset scores/tier side by side with model scores/tier.

Usage: python scripts/export_anon_xlsx.py TS1 TS2 TS3 TS4 [out.xlsx]
       (default: the four anonymized runs of 2026-08-31)
"""

import json
import os
import sys
from collections import Counter

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

BENCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "benchmark")

DIMS = ["ad_relevance", "delivery", "synergy", "duration", "manufacturability", "safety"]
DIM_ZH = {"ad_relevance": "AD相关性", "delivery": "靶组织递送", "synergy": "多靶点协同",
          "duration": "效应持续", "manufacturability": "生产质控", "safety": "生物安全性"}
PRESET_MAP = {"ad_relevance": "AD_relevance", "delivery": "Target_delivery",
              "synergy": "Multi_target_synergy", "duration": "Effect_duration",
              "manufacturability": "Manufacturing_control", "safety": "Biosafety",
              "overall": "Final_score"}

DEFAULT_RUNS = [
    ("1788680577", "LoRA+harness"),
    ("1788681422", "base+harness"),
    ("1788682318", "LoRA+prompt"),
    ("1788682741", "base+prompt"),
]

GREEN = PatternFill("solid", fgColor="C6EFCE")
RED = PatternFill("solid", fgColor="FFC7CE")
BOLD = Font(bold=True)


def load_run(ts):
    path = f"E:/Cu-agent/outputs/run_{ts}/adtb100_scores_{ts}.json"
    comp = path.replace(".json", "_complete.json")
    if os.path.exists(comp):
        path = comp
    return json.loads(open(path, encoding="utf-8").read())


def main():
    args = sys.argv[1:]
    runs = [(t, l) for t, l in zip(args[::2], args[1::2])] if len(args) >= 8 else DEFAULT_RUNS
    out_path = args[-1] if args and args[-1].endswith(".xlsx") else \
        "E:/Cu-agent/outputs/adtb100_anonymized_2x2.xlsx"

    payloads = [(label, load_run(ts)) for ts, label in runs]
    bench_file = payloads[0][1]["benchmark_file"]
    bench = json.load(open(os.path.join(BENCH_DIR, bench_file), encoding="utf-8"))
    truth = {r["ID"]: r for r in bench["records"]}

    # tier thresholds = midpoints of preset tier Final_score means
    tier_vals = {}
    for r in bench["records"]:
        tier_vals.setdefault(r["Category"], []).append(r["Final_score"])
    tiers = sorted(tier_vals, key=lambda t: -sum(tier_vals[t]) / len(tier_vals[t]))
    means = {t: sum(tier_vals[t]) / len(tier_vals[t]) for t in tiers}
    thr = [(means[tiers[i]] + means[tiers[i + 1]]) / 2 for i in range(len(tiers) - 1)]

    def tier_of(v):
        if v is None:
            return None
        for i, t in enumerate(thr):
            if v >= t:
                return tiers[i]
        return tiers[-1]

    wb = openpyxl.Workbook()

    # ---- overview sheet ----
    ws = wb.active
    ws.title = "总览"
    header = ["ID", "药品名称", "匿名代号", "类别", "机理", "预设评级", "预设Final分"]
    for label, _ in payloads:
        header += [f"{label} overall", f"{label} 评级"]
    header += ["四条件均分", "均值评级", "评级一致?"]
    ws.append(header)
    for c in range(1, len(header) + 1):
        ws.cell(1, c).font = BOLD

    ids = [r["ID"] for r in payloads[0][1]["results"]]
    per_condition = {}  # label -> {ID: agent_scores}
    for label, p in payloads:
        per_condition[label] = {r["ID"]: r["agent_scores"] for r in p["results"]}

    n_match = 0
    for rid in ids:
        t = truth[rid]
        code = next((c for c, n in payloads[0][1].get("deanonymize", {}).items()
                     if n == t["Therapeutic"]), "")
        row = [rid, t["Therapeutic"], code, t["Therapeutic_class"], t["Mechanism"],
               t["Category"], t["Final_score"]]
        ovs = []
        for label, _ in payloads:
            ov = per_condition[label][rid]["overall"]
            ovs.append(ov)
            row += [ov, tier_of(ov)]
        valid = [v for v in ovs if v is not None]
        avg = round(sum(valid) / len(valid), 2) if valid else None
        avg_tier = tier_of(avg)
        match = avg_tier == t["Category"]
        n_match += match
        row += [avg, avg_tier, "一致" if match else "不一致"]
        ws.append(row)
        ws.cell(ws.max_row, len(header)).fill = GREEN if match else RED

    ws.append([])
    ws.append(["四条件均值评级与预设一致", f"{n_match}/{len(ids)} = {n_match/len(ids):.1%}"])
    ws.cell(ws.max_row, 1).font = BOLD

    # ---- per-condition sheets ----
    for label, p in payloads:
        ws = wb.create_sheet(label)
        header = ["ID", "药品名称", "代号", "预设评级"]
        for d in DIMS:
            header += [f"{DIM_ZH[d]}_预设", f"{DIM_ZH[d]}_模型"]
        header += ["Final_预设", "overall_模型", "ca自报", "模型评级", "一致?"]
        ws.append(header)
        for c in range(1, len(header) + 1):
            ws.cell(1, c).font = BOLD
        for r in p["results"]:
            t = truth[r["ID"]]
            s = r["agent_scores"]
            row = [r["ID"], t["Therapeutic"], r["Compound"], t["Category"]]
            for d in DIMS:
                row += [t[PRESET_MAP[d]], s.get(d)]
            pt = tier_of(s.get("overall"))
            row += [t["Final_score"], s.get("overall"), s.get("ca_overall"), pt,
                    "一致" if pt == t["Category"] else "不一致"]
            ws.append(row)
            ws.cell(ws.max_row, len(header)).fill = GREEN if pt == t["Category"] else RED

    # column widths
    for ws in wb.worksheets:
        for i, col in enumerate(ws.columns, 1):
            w = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[get_column_letter(i)].width = min(max(w + 2, 8), 40)

    wb.save(out_path)
    print(f"Wrote {out_path}")
    print(f"四条件均值评级一致率: {n_match}/{len(ids)} = {n_match/len(ids):.1%}")


if __name__ == "__main__":
    main()
