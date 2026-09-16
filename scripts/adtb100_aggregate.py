#!/usr/bin/env python3
"""
Aggregate repeated ADTB-100 runs into mean±std statistics.

Scans outputs/run_*/adtb100_scores_*.json (preferring *_complete.json), keeps
payloads matching the given filter (default: rubric anchored, gate off =
additive), groups by (model_variant, mode), and computes per-run metrics with
the same formulas as compare_adtb100.py:

  rho(overall), concordance, tier accuracy, precision@70, neg mean rank,
  parse coverage.

Usage: python scripts/adtb100_aggregate.py [--gate off] [--out aggregate_adtb100.md]
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_adtb100 import spearman, TIERS

OUTPUT_ROOT = Path("E:/Cu-agent/outputs")
BENCHMARK = Path("E:/Cu-agent/benchmark/ADTB-100_v1.0_Alzheimer_Therapeutics_Benchmark.json")

TIER_RANK = {t: i for i, t in enumerate(TIERS)}


def metrics_for(payload, truth):
    rows = []
    for r in payload["results"]:
        t = truth[r["ID"]]
        ov = r["agent_scores"].get("overall")
        rows.append({"tier": t["Category"], "label": t["Label"], "preset": t["Overall_score"],
                     "overall": ov})
    scored = [r for r in rows if r["overall"] is not None]
    n = len(rows)
    m = {"n": n, "scored": len(scored), "coverage": len(scored) / n if n else 0}
    if len(scored) < 10:
        return m
    m["rho"] = spearman([r["overall"] for r in scored], [r["preset"] for r in scored])
    pairs = ok = 0
    for a in scored:
        for b in scored:
            if TIER_RANK[a["tier"]] < TIER_RANK[b["tier"]]:
                pairs += 1
                ok += 1 if a["overall"] > b["overall"] else (0.5 if a["overall"] == b["overall"] else 0)
    m["concordance"] = ok / pairs if pairs else None
    def tier_of(v):
        return "High-quality" if v >= 7 else ("Intermediate" if v >= 4 else "Negative control")
    m["tier_acc"] = sum(1 for r in scored if tier_of(r["overall"]) == r["tier"]) / len(scored)
    ranked = sorted(scored, key=lambda r: r["overall"], reverse=True)
    top70 = ranked[:70]
    m["p70"] = sum(1 for r in top70 if r["label"] == "positive") / len(top70)
    neg = [i + 1 for i, r in enumerate(ranked) if r["tier"] == "Negative control"]
    m["neg_rank"] = sum(neg) / len(neg) if neg else None
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", default="off")
    ap.add_argument("--since", default=None, help="only include run_<TS> with TS >= this value")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    truth = {r["ID"]: r for r in json.loads(BENCHMARK.read_text(encoding="utf-8"))["records"]}

    # prefer _complete.json over the raw scores file of the same run
    seen = {}
    for f in OUTPUT_ROOT.glob("run_*/adtb100_scores_*.json"):
        if args.since:
            try:
                if int(f.parent.name.split("_")[1]) < int(args.since):
                    continue
            except (IndexError, ValueError):
                continue
        stem = f.name.replace("_complete", "")
        if stem not in seen or f.name.endswith("_complete.json"):
            seen[stem] = f

    groups = defaultdict(list)
    for f in sorted(seen.values()):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not payload.get("rubric"):
            continue
        if (payload.get("gate") or "off") != args.gate:
            continue
        # runs made before the gate field existed: distinguish by content —
        # gated runs carry ad_relevance scores, additive runs don't
        has_gate_dim = any(r["agent_scores"].get("ad_relevance") is not None
                           for r in payload["results"])
        if (args.gate == "off") == has_gate_dim:
            continue
        key = (payload.get("model_variant", "?"), payload.get("mode", "?"))
        m = metrics_for(payload, truth)
        m["run"] = f.parent.name
        groups[key].append(m)

    KEYS = [("coverage", "parse coverage"), ("rho", "Spearman rho"), ("concordance", "cross-tier concordance"),
            ("tier_acc", "3-tier accuracy"), ("p70", "Precision@70"), ("neg_rank", "neg-control mean rank")]

    L = []
    A = L.append
    A(f"# ADTB-100 additive-mode repeated-run aggregation (gate={args.gate})")
    A("")
    for (variant, mode), runs in sorted(groups.items()):
        A(f"## {variant} × {mode}(n={len(runs)} runs)")
        A("")
        A("| metric | mean ± std | min ~ max |")
        A("|---|---|---|")
        for k, label in KEYS:
            vals = [r[k] for r in runs if r.get(k) is not None]
            if not vals:
                continue
            mean = sum(vals) / len(vals)
            std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
            A(f"| {label} | {mean:.3f} ± {std:.3f} | {min(vals):.3f} ~ {max(vals):.3f} |")
        A("")
        A(f"runs: {', '.join(r['run'] for r in runs)}")
        A("")
    text = "\n".join(L)
    print(text)
    out = Path(args.out) if args.out else OUTPUT_ROOT / f"aggregate_adtb100_gate_{args.gate}.md"
    out.write_text(text, encoding="utf-8")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
