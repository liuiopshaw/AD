#!/usr/bin/env python3
"""
JSONL training-data quality gate (Phase 1).

Per line checks:
  1. valid JSON object
  2. has instruction / input / output fields; instruction and input non-empty
     (hard FAIL). Empty output is reported separately as WARN — raw builds from
     build_training_data.py intentionally leave output for later annotation;
     pass --strict to treat empty output as FAIL.
  3. input contains no PDF garbage: >=20 consecutive chars that are neither
     ASCII printable, CJK, Unicode letter/number/punctuation, nor whitespace
  4. dedup by sha256(instruction + input): internal dups within the file, and
     overlap against the existing baseline data/training/*.jsonl

Usage:
    python finetune/validate_jsonl.py                      # validate data/training/*.jsonl
    python finetune/validate_jsonl.py data/training_v2/*.jsonl
    python finetune/validate_jsonl.py --strict FILE...
"""

import argparse
import glob
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__import__("os").environ.get("CU_AGENT_ROOT", "E:/Cu-agent"))
BASELINE_DIR = PROJECT_ROOT / "data" / "training"
REQUIRED_FIELDS = ("instruction", "input", "output")
GARBAGE_RUN = 20
MAX_SAMPLES_PER_ISSUE = 3


def pair_hash(obj: dict) -> str:
    return hashlib.sha256(
        (obj.get("instruction", "") + "\n" + obj.get("input", "")).encode("utf-8")
    ).hexdigest()


def _is_allowed(ch: str) -> bool:
    o = ord(ch)
    if 0x20 <= o <= 0x7E:          # ASCII printable
        return True
    if ch.isspace():
        return True
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N", "P")  # letters, numbers, punctuation (any script)


def garbage_run_length(text: str) -> int:
    """Longest run of chars outside ASCII-printable/CJK/letter/number/punct/space."""
    best = run = 0
    for ch in text:
        if _is_allowed(ch):
            run = 0
        else:
            run += 1
            best = max(best, run)
    return best


def load_baseline_hashes(exclude: Path = None) -> dict:
    """sha256 -> source filename for every line in data/training/*.jsonl."""
    hashes = {}
    for path in sorted(BASELINE_DIR.glob("*.jsonl")):
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    hashes.setdefault(pair_hash(json.loads(line)), path.name)
                except json.JSONDecodeError:
                    continue
    return hashes


def validate_file(path: Path, baseline: dict, strict: bool) -> dict:
    stats = {
        "file": str(path), "lines": 0, "pass": 0, "warn_empty_output": 0,
        "fail": 0, "internal_dup": 0, "baseline_dup": 0,
        "issues": {},  # reason -> [line_no, ...]
    }

    def issue(reason, lineno, sample=""):
        stats["issues"].setdefault(reason, [])
        if len(stats["issues"][reason]) < MAX_SAMPLES_PER_ISSUE:
            stats["issues"][reason].append((lineno, sample[:120]))

    seen = set()
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            stats["lines"] += 1

            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                stats["fail"] += 1
                issue("invalid_json", lineno, f"{e}: {raw[:80]}")
                continue

            missing = [k for k in REQUIRED_FIELDS if k not in obj]
            if missing:
                stats["fail"] += 1
                issue(f"missing_fields:{','.join(missing)}", lineno, raw[:80])
                continue
            if not str(obj["instruction"]).strip() or not str(obj["input"]).strip():
                stats["fail"] += 1
                issue("empty_instruction_or_input", lineno, raw[:80])
                continue

            if not str(obj["output"]).strip():
                if strict:
                    stats["fail"] += 1
                    issue("empty_output", lineno)
                    continue
                stats["warn_empty_output"] += 1

            run = garbage_run_length(str(obj["input"]))
            if run >= GARBAGE_RUN:
                stats["fail"] += 1
                issue("garbled_input", lineno, str(obj["input"])[:120])
                continue

            h = pair_hash(obj)
            if h in seen:
                stats["internal_dup"] += 1
                issue("internal_dup", lineno)
                continue
            seen.add(h)
            if h in baseline:
                stats["baseline_dup"] += 1
                issue(f"dup_vs_baseline:{baseline[h]}", lineno)
                continue

            stats["pass"] += 1
    return stats


def report(stats_list, strict: bool) -> int:
    total_fail = 0
    for s in stats_list:
        total_fail += s["fail"]
        print(f"\n{'='*60}\n{s['file']}")
        print(f"  lines={s['lines']} pass={s['pass']} "
              f"warn_empty_output={s['warn_empty_output']} FAIL={s['fail']}")
        print(f"  internal_dup={s['internal_dup']} baseline_dup={s['baseline_dup']}")
        for reason, samples in s["issues"].items():
            print(f"  issue: {reason} (showing {len(samples)})")
            for lineno, sample in samples:
                print(f"    line {lineno}: {sample}")
    print(f"\n{'='*60}")
    print(f"SUMMARY: {len(stats_list)} file(s), total FAIL={total_fail}"
          f"{' (strict: empty output = FAIL)' if strict else ''}")
    return 1 if total_fail else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*",
                        help="JSONL files or glob patterns (default: data/training/*.jsonl)")
    parser.add_argument("--strict", action="store_true",
                        help="Treat empty output as FAIL (default: WARN)")
    args = parser.parse_args()

    patterns = args.paths or [str(BASELINE_DIR / "*.jsonl")]
    files = []
    for p in patterns:
        matched = sorted(glob.glob(p))
        files.extend(Path(m) for m in matched)
    if not files:
        sys.exit("No files matched.")

    stats_list = []
    for p in files:
        # A file inside the baseline dir must not be compared against itself.
        exclude = p if p.parent.resolve() == BASELINE_DIR.resolve() else None
        baseline = load_baseline_hashes(exclude=exclude)
        stats_list.append(validate_file(p, baseline, args.strict))
    sys.exit(report(stats_list, args.strict))


if __name__ == "__main__":
    main()
