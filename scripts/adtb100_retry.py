#!/usr/bin/env python3
"""
Retry missing items from a prompt-mode ADTB-100 run.

Some batches omit the `overall:` field despite instructions. This script finds
items with overall=None in adtb100_scores_<TS>.json, re-asks the SAME model
variant with the SAME solo prompt plus one explicit compliance line, and merges
the new scores into a new scores file. Original raw files are untouched; retry
raws are saved alongside.

Usage: python scripts/adtb100_retry.py <timestamp>
"""

import glob
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import benchmark_adtb100 as B

REINFORCE = "\n\nREMINDER: EVERY line MUST contain ALL SIX scores (efficacy, mechanism, safety, bbb, clinical, overall). Do NOT omit overall."


def main():
    ts = sys.argv[1]
    run_files = glob.glob(f"E:/Cu-agent/outputs/run_{ts}/adtb100_scores_{ts}.json")
    if not run_files:
        raise SystemExit(f"scores file not found for ts={ts}")
    path = run_files[0]
    payload = json.loads(open(path, encoding="utf-8").read())
    is_base = payload.get("model_variant", "").startswith("base")
    B.AGENT_OVERRIDE = "base" if is_base else None
    B.RUN_DIR = Path(os.path.dirname(path))

    missing_idx = [i for i, r in enumerate(payload["results"])
                   if r["agent_scores"]["overall"] is None]
    print(f"ts={ts} variant={'base' if is_base else 'lora'} missing overall: {len(missing_idx)}")
    if not missing_idx:
        return

    is_rubric = bool(payload.get("rubric"))
    rubric_text = B.load_rubric() if is_rubric else None
    B.GATE = payload.get("gate") or "off"

    retry_ts = int(time.time())
    for chunk_i in range(0, len(missing_idx), 20):
        idxs = missing_idx[chunk_i:chunk_i + 20]
        batch = [{"Compound": payload["results"][i]["Compound"],
                  "Class": payload["results"][i]["Class"],
                  "Mechanism": payload["results"][i]["Mechanism"]} for i in idxs]
        if is_rubric:
            raw = B.call_agent("ca", B.r_solo_prompt(batch, rubric_text) + REINFORCE,
                               max_tokens=8192)
            dims = B.RUBRIC_DIM_PATTERNS
        else:
            raw = B.call_agent("ca", B.solo_prompt(batch) + REINFORCE, max_tokens=8192)
            dims = B.DIM_PATTERNS
        B.save_raw(f"adtb100_solo_retry{chunk_i//20+1}_raw_{retry_ts}.txt", raw)
        parsed = B.parse_scores(raw, len(idxs), dims)
        for k, i in enumerate(idxs):
            for dim, v in parsed[k].items():
                if v is None:
                    continue
                if is_rubric and dim == "overall":
                    payload["results"][i]["agent_scores"]["ca_overall"] = \
                        payload["results"][i]["agent_scores"].get("ca_overall") or v
                elif payload["results"][i]["agent_scores"].get(dim) is None:
                    payload["results"][i]["agent_scores"][dim] = v
            if is_rubric:
                s = payload["results"][i]["agent_scores"]
                if s["overall"] is None:
                    s["overall"] = B.rubric_overall(s)
        time.sleep(2)

    still = sum(1 for r in payload["results"] if r["agent_scores"]["overall"] is None)
    payload["retry_note"] = (f"retry {retry_ts}: re-asked {len(missing_idx)} items with "
                             f"compliance reminder; still missing: {still}")
    out_path = path.replace(f"_{ts}.json", f"_{ts}_complete.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"still missing: {still} -> {out_path}")


if __name__ == "__main__":
    main()
