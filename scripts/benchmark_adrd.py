#!/usr/bin/env python3
"""
ADRD-Bench evaluation (Caregiving QA component: 29 MCQ + 120 True/False).

Unified QA (1438 q) is NOT redistributed upstream (only source indices), so it
cannot be evaluated without the original datasets — only the Caregiving
component is run.

Blind protocol: the model sees only Question (+ Options); answers are never
in the prompt. Raw outputs saved unmodified; parsing is extraction-only.

Usage:
  python scripts/benchmark_adrd.py [--agent epa] [--use-base] [--batch-size 10]
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from benchmark_adtb100 import call_agent  # reuse server client + retry logic
import benchmark_adtb100 as B
from output_utils import run_dir

BENCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "benchmark", "ADRD-Bench-main")
MCQ_FILE = os.path.join(BENCH_DIR, "ADRD_Caregiving_QA",
                        "ADRD_Caregiving_Multiple_Choice.json")
TF_FILE = os.path.join(BENCH_DIR, "ADRD_Caregiving_QA",
                       "ADRD_Caregiving_True_or_False.json")

TS = int(time.time())
RUN_DIR = run_dir(TS)


def save_raw(filename, content):
    path = RUN_DIR / filename
    path.write_text(content, encoding="utf-8")
    print(f"  -> {path}")


def mcq_prompt(batch):
    lines = []
    for j, q in enumerate(batch):
        opts = "  ".join(f"{k}. {v}" for k, v in q["Options"].items())
        lines.append(f"{j+1}. {q['Question']}\n   {opts}")
    return f"""Answer each multiple-choice question about Alzheimer's disease and related dementias (ADRD). Reply with ONLY the option letter per line.

Questions:
{chr(10).join(lines)}

Output format (ONE LINE per question, numbered, letter only):
1. <A/B/C/D/E>
2. ..."""


def tf_prompt(batch):
    lines = "\n".join(f"{j+1}. {q['Question']}" for j, q in enumerate(batch))
    return f"""Judge each statement about Alzheimer's disease and related dementias (ADRD) caregiving as true (Yes) or false (No). Reply with ONLY Yes or No per line.

Statements:
{lines}

Output format (ONE LINE per statement, numbered, Yes/No only):
1. <Yes/No>
2. ..."""


def parse_answers(raw, n, kind):
    """kind: 'mcq' -> letter A-E; 'tf' -> Yes/No. Extraction only."""
    out = [None] * n
    for line in raw.split("\n"):
        m = re.match(r"\s*(\d+)[.)]\s*(.*)", line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if not (0 <= idx < n):
            continue
        body = m.group(2).strip()
        if kind == "mcq":
            am = re.match(r"\(?([A-E])\b", body, re.IGNORECASE)
            if am:
                out[idx] = am.group(1).upper()
        else:
            ym = re.match(r"\(?\s*(Yes|No|True|False)\b", body, re.IGNORECASE)
            if ym:
                v = ym.group(1).lower()
                out[idx] = "Yes" if v in ("yes", "true") else "No"
    return out


def run_split(name, items, prompt_fn, kind, answer_key, agent, batch_size):
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        bnum = i // batch_size + 1
        raw = call_agent(agent, prompt_fn(batch), max_tokens=2048, temperature=0.1)
        save_raw(f"adrd_{name}_batch{bnum}_raw_{TS}.txt", raw)
        parsed = parse_answers(raw, len(batch), kind)
        for q, p in zip(batch, parsed):
            results.append({"ID": q["ID"], "gold": q[answer_key], "pred": p,
                            "correct": p is not None and p.lower() == str(q[answer_key]).lower()})
        miss = sum(1 for p in parsed if p is None)
        if miss:
            print(f"  WARNING: {name} batch {bnum}: {miss}/{len(batch)} unparsed")
        time.sleep(1)
    n = len(results)
    acc = sum(r["correct"] for r in results) / n if n else 0
    unparsed = sum(1 for r in results if r["pred"] is None)
    print(f"[{name}] acc {sum(r['correct'] for r in results)}/{n} = {acc:.1%}, unparsed {unparsed}")
    return {"split": name, "n": n, "accuracy": acc, "unparsed": unparsed, "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="epa", help="LoRA adapter to route to")
    ap.add_argument("--use-base", action="store_true")
    ap.add_argument("--batch-size", type=int, default=10)
    args = ap.parse_args()

    B.AGENT_OVERRIDE = "base" if args.use_base else None
    agent = "base" if args.use_base else args.agent

    mcq = json.load(open(MCQ_FILE, encoding="utf-8"))["data"]
    tf = json.load(open(TF_FILE, encoding="utf-8"))["data"]
    print(f"ADRD-Bench Caregiving QA: {len(mcq)} MCQ + {len(tf)} T/F, agent={agent}")
    print(f"Run dir: {RUN_DIR}")

    t0 = time.time()
    splits = [
        run_split("mcq", mcq, mcq_prompt, "mcq", "Answer", agent, args.batch_size),
        run_split("tf", tf, tf_prompt, "tf", "Answer", agent, args.batch_size),
    ]
    total_n = sum(s["n"] for s in splits)
    total_correct = sum(round(s["accuracy"] * s["n"]) for s in splits)
    out = {
        "benchmark": "ADRD-Bench Caregiving QA (MCQ + True/False)",
        "note": "Unified QA not evaluated: upstream redistributes only source indices",
        "model_variant": "base (Qwen3-VL-8B, NO LoRA)" if args.use_base
                         else f"lora adapter: {args.agent}",
        "timestamp": TS, "elapsed_s": round(time.time() - t0, 1),
        "overall_accuracy": total_correct / total_n if total_n else None,
        "splits": splits,
    }
    out_file = RUN_DIR / f"adrd_scores_{TS}.json"
    out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nOVERALL: {total_correct}/{total_n} = {out['overall_accuracy']:.1%}")
    print(f"-> {out_file}")


if __name__ == "__main__":
    main()
