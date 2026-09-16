#!/usr/bin/env python3
"""
Compare ADTB-100 blind agent scores against preset ground truth.

Reads adtb100_scores_<TS>.json (from benchmark_adtb100.py) and the benchmark
JSON, then computes — mechanically, no agent involved:

  1. Per-tier mean/min/max of every agent dimension (High-quality /
     Intermediate / Negative control).
  2. Spearman rank correlation (tie-corrected) between agent overall and
     preset Overall_score.
  3. Pairwise cross-tier concordance: fraction of (higher-tier, lower-tier)
     pairs where the agent score orders them correctly.
  4. Fixed-threshold 3-tier confusion matrix (agent overall >=7 -> High,
     >=4 -> Intermediate, else Negative).
  5. Precision@70: preset Label "positive" has exactly 70 members; check the
     agent top-70.
  6. Mean rank of the 10 negative controls (lower = better separation).

Usage: python scripts/compare_adtb100.py <timestamp>
"""

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from output_utils import find_run_dir

BENCHMARK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "benchmark", "ADTB-100_v1.0_Alzheimer_Therapeutics_Benchmark.json")

DIMS = ["efficacy", "mechanism", "safety", "bbb", "clinical", "overall"]
PRESET_DIMS = {"efficacy": "Efficacy", "mechanism": "Mechanism_score", "bbb": "BBB_score",
               "safety": "Safety_score", "clinical": "Clinical_score", "overall": "Overall_score"}
TIERS = ["High-quality", "Intermediate", "Negative control"]

# Rubric-mode payloads (the rubric file, 5 weighted dims). Only dims with a
# meaningful benchmark counterpart get a Spearman; others are reported NA.
RUBRIC_DIMS = ["ad_relevance", "delivery", "synergy", "duration", "manufacturability",
               "safety", "ca_overall", "overall"]
RUBRIC_PRESET_DIMS = {"ad_relevance": "Efficacy", "delivery": "BBB_score",
                      "safety": "Safety_score", "overall": "Overall_score"}

# v3 AD-TxBench-100: benchmark dims are exactly the rubric dims (hard-gated).
V3_PRESET_RUBRIC = {"ad_relevance": "AD_relevance", "delivery": "Target_delivery",
                    "synergy": "Multi_target_synergy", "duration": "Effect_duration",
                    "manufacturability": "Manufacturing_control", "safety": "Biosafety",
                    "overall": "Final_score"}
V3_PRESET_LEGACY = {"overall": "Final_score"}


def avg_ranks(values):
    """Average ranks (1 = lowest) with tie correction."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(x, y):
    rx, ry = avg_ranks(x), avg_ranks(y)
    n = len(x)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    return cov / (vx * vy) ** 0.5 if vx and vy else None


def main():
    ts = sys.argv[1] if len(sys.argv) > 1 else None
    if ts is None:
        from output_utils import OUTPUT_ROOT
        cands = sorted(OUTPUT_ROOT.glob("run_*/adtb100_scores_*.json"),
                       key=lambda p: p.stat().st_mtime)
        if not cands:
            raise SystemExit("No run_*/adtb100_scores_*.json under outputs/")
        scores_file = cands[-1]
    else:
        scores_file = find_run_dir(ts) / f"adtb100_scores_{ts}.json"
        complete = scores_file.with_name(scores_file.name.replace(".json", "_complete.json"))
        if complete.exists():
            scores_file = complete  # retry-merged version wins
    run = scores_file.parent
    payload = json.loads(scores_file.read_text(encoding="utf-8"))
    bench_path = os.path.join(os.path.dirname(BENCHMARK),
                              payload.get("benchmark_file", os.path.basename(BENCHMARK)))
    bench = json.load(open(bench_path, encoding="utf-8"))
    truth = {r["ID"]: r for r in bench["records"]}

    is_v3 = "Therapeutic" in bench["records"][0]
    overall_key = "Final_score" if is_v3 else "Overall_score"
    label_key = "Ground_truth" if is_v3 else "Label"

    is_rubric = bool(payload.get("rubric"))
    dims = RUBRIC_DIMS if is_rubric else DIMS
    if is_v3:
        preset_map = V3_PRESET_RUBRIC if is_rubric else V3_PRESET_LEGACY
    else:
        preset_map = RUBRIC_PRESET_DIMS if is_rubric else PRESET_DIMS

    # tiers ordered best→worst by mean preset overall score
    tier_vals = {}
    for r in bench["records"]:
        tier_vals.setdefault(r["Category"], []).append(r[overall_key])
    tiers = sorted(tier_vals, key=lambda t: -sum(tier_vals[t]) / len(tier_vals[t]))

    rows = []
    for r in payload["results"]:
        t = truth[r["ID"]]
        rows.append({
            "ID": r["ID"], "Compound": r["Compound"],
            "tier": t["Category"], "label": t[label_key],
            "preset": {d: t[pk] for d, pk in preset_map.items()},
            "agent": r["agent_scores"],
        })

    scored = [r for r in rows if r["agent"]["overall"] is not None]
    missing = [r for r in rows if r["agent"]["overall"] is None]

    L = []
    A = L.append
    A(f"# ADTB-100 Blind-Evaluation Comparison Report (run {payload['timestamp']})")
    A("")
    A(f"- Protocol: {payload['protocol']}")
    A(f"- Model: {payload.get('model_variant', 'lora (per-agent adapters)')}")
    A(f"- Mode: {payload.get('mode', 'harness')} ({' → '.join(payload['agent_chain'])})")
    if is_rubric:
        A(f"- Anchoring: {payload['rubric']}")
        A(f"- Gating: {payload.get('gate', 'off')}")
    if payload.get("retry_note"):
        A(f"- Retry: {payload['retry_note']}")
    if payload.get("skipped_placeholders"):
        A(f"- Note: {payload['skipped_placeholders']} anonymous placeholder records in the benchmark (no name/category/mechanism) "
          f"cannot be blind-evaluated and were skipped; only {len(rows)} named records were evaluated")
    A(f"- Samples: {len(rows)}; overall parsed successfully for {len(scored)}, missing for {len(missing)}")
    A("")

    tier_preset_means = {t: sum(tier_vals[t]) / len(tier_vals[t]) for t in tiers}
    tier_counts = Counter(r["tier"] for r in rows)

    # 1. per-tier stats
    preset_str = " / ".join(f"{t}={tier_preset_means[t]:.2f}" for t in tiers)
    A(f"## 1. Agent score distribution per tier (preset {preset_str})")
    A("")
    header_tiers = " | ".join(f"{t} (n={tier_counts[t]})" for t in tiers)
    A(f"| Dimension | {header_tiers} | Monotonically decreasing? |")
    A("|---|---|---|---|")
    tier_means = {}
    for d in dims:
        means = []
        cells = []
        for tier in tiers:
            vals = [r["agent"].get(d) for r in scored if r["tier"] == tier]
            vals = [v for v in vals if v is not None]
            m = sum(vals) / len(vals) if vals else None
            means.append(m)
            cells.append(f"{m:.2f} [{min(vals):.0f}-{max(vals):.0f}]" if vals else "NA")
        tier_means[d] = means
        mono = "✓" if all(m is not None for m in means) and all(
            means[i] > means[i + 1] for i in range(len(means) - 1)) else "✗"
        A(f"| {d} | {' | '.join(cells)} | {mono} |")
    A("")

    # 2. Spearman per dimension
    A("## 2. Spearman rank correlation (agent dimension scores vs preset counterparts, tie-corrected)")
    A("")
    if is_rubric and not is_v3:
        A("> rubric dimensions do not map to benchmark dimensions; only ad_relevance↔Efficacy, delivery↔BBB_score, "
          "safety↔Safety_score, and overall↔Overall_score are comparable; other dimensions are marked NA.")
        A("")
    if is_v3 and is_rubric:
        A("> v3 benchmark dimensions correspond one-to-one with the rubric; overall↔Final_score (hard-gated formula).")
        A("")
    A("| Dimension | rho |")
    A("|---|---|")
    rho = {}
    for d in dims:
        if d not in preset_map:
            rho[d] = None
            A(f"| {d} | NA |")
            continue
        sub = [r for r in scored if r["agent"].get(d) is not None]
        x = [r["agent"][d] for r in sub]
        y = [r["preset"][d] for r in sub]
        rho[d] = spearman(x, y) if len(sub) > 2 else None
        A(f"| {d} | {rho[d]:.3f} |" if rho[d] is not None else f"| {d} | NA |")
    A("")

    # 3. pairwise cross-tier concordance on overall
    tier_rank = {t: i for i, t in enumerate(tiers)}  # 0 = best
    pairs = ok = 0
    pair_detail = Counter()
    for a in scored:
        for b in scored:
            if tier_rank[a["tier"]] < tier_rank[b["tier"]]:
                pairs += 1
                pair_detail[(a["tier"], b["tier"])] += 1
                if a["agent"]["overall"] > b["agent"]["overall"]:
                    ok += 1
                elif a["agent"]["overall"] == b["agent"]["overall"]:
                    ok += 0.5
    concordance = ok / pairs if pairs else None
    pair_str = " + ".join(f"{ta[:4]}-{tb[:4]} {c}" for (ta, tb), c in sorted(pair_detail.items()))
    A("## 3. Cross-tier pairwise concordance (overall)")
    A("")
    A(f"- Total cross-tier ordered pairs: {pairs} ({pair_str})")
    A(f"- correctly ordered by agent: {ok:.0f} (ties count 0.5) -> **concordance = {concordance:.3f}**")
    A("")

    # 4. tier classification with thresholds = midpoints of preset tier means
    thr = [(tier_preset_means[tiers[i]] + tier_preset_means[tiers[i + 1]]) / 2
           for i in range(len(tiers) - 1)]

    def tier_of(v):
        for i, t in enumerate(thr):
            if v >= t:
                return tiers[i]
        return tiers[-1]

    conf = Counter()
    for r in scored:
        conf[(r["tier"], tier_of(r["agent"]["overall"]))] += 1
    correct = sum(conf[(t, t)] for t in tiers)
    thr_str = ", ".join(f"≥{t:.2f}→{tiers[i]}" for i, t in enumerate(thr))
    A(f"## 4. 3-tier classification (thresholds = midpoints of preset tier means: {thr_str}, else -> {tiers[-1]})")
    A("")
    A(f"| preset \\ predicted | {' | '.join(t for t in tiers)} |")
    A("|---|---|---|---|")
    for t in tiers:
        A(f"| {t} | {' | '.join(str(conf[(t, tt)]) for tt in tiers)} |")
    A(f"| **accuracy** | | | **{correct}/{len(scored)} = {correct/len(scored):.1%}** |")
    A("")

    # 5. precision@k (k = number of positives among evaluated)
    ranked = sorted(scored, key=lambda r: r["agent"]["overall"], reverse=True)
    k_pos = sum(1 for r in rows if r["label"] == "positive")
    topk = ranked[:k_pos]
    pk = sum(1 for r in topk if r["label"] == "positive") / len(topk) if topk else None
    A(f"## 5. Precision@{k_pos} ({k_pos} preset positives among evaluated)")
    A("")
    A(f"- true positives in agent top-{k_pos}: {sum(1 for r in topk if r['label']=='positive')}/{k_pos} -> **{pk:.1%}**")
    A("")

    # 6. negative control mean rank (last tier)
    neg_tier = tiers[-1]
    neg_ranks = [i + 1 for i, r in enumerate(ranked) if r["tier"] == neg_tier]
    A("## 6. Negative-control rank positions (1 = best)")
    A("")
    n_neg = tier_counts[neg_tier]
    A(f"- mean rank of {n_neg} negative controls: **{sum(neg_ranks)/len(neg_ranks):.1f}** / {len(ranked)}"
      f" (ideal ~= {len(ranked) - (n_neg - 1) / 2:.1f}); median {sorted(neg_ranks)[len(neg_ranks)//2]}")
    A("")

    if missing:
        A("## Appendix: items with unparsed overall")
        A("")
        for r in missing:
            A(f"- {r['ID']} {r['Compound']}")
        A("")

    report = {
        "timestamp": payload["timestamp"], "scores_file": scores_file.name,
        "n": len(rows), "scored": len(scored),
        "tier_means": tier_means, "spearman": rho,
        "concordance": concordance,
        "tier_accuracy": correct / len(scored) if scored else None,
        "precision_at_k": pk, "k_positives": k_pos,
        "neg_mean_rank": sum(neg_ranks) / len(neg_ranks) if neg_ranks else None,
    }
    (run / f"adtb100_compare_{payload['timestamp']}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = run / f"adtb100_compare_{payload['timestamp']}.md"
    md.write_text("\n".join(L), encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("\n".join(L))
    print(f"-> {md}")


if __name__ == "__main__":
    main()
