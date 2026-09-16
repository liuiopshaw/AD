#!/usr/bin/env python3
"""
Mechanically extract per-material ASA subscores from raw agent part files.

Reads task100_{manufacturing,delivery,safety,mechanism}_<TS>_part*.txt from the
run directory and collects the JSON subscore tail each agent appended to every
material line (see task_100_materials.py). Extraction is purely mechanical:
  - material name = first pipe-separated cell of the line (verbatim)
  - subscores      = the LAST valid JSON object on the line (json.loads)
Extraction failures (unparsed line, missing/invalid JSON tail) are recorded
in "missing" — nothing is invented or repaired (CLAUDE.md iron rule).

Output: subscores_<TS>.json in the run directory:
  {"ts": ..., "source_files": [...],
   "materials": {name: {axis: {sub: score}}},
   "missing": [{file, line, reason, ...}]}

Axis mapping: manufacturing->manufacturability, delivery->delivery_efficiency,
safety->biosafety, mechanism->multi_target_synergy+durability
(scripts/asa_rubric.json axis names).

NOTE: agent ids were renamed 2026-09 (apa->manufacturing, epa->delivery,
bsa->safety, mma->mechanism). Output files from older runs use the legacy
task100_{apa,epa,bsa,mma}_ prefixes and are NOT picked up by the globs below;
re-extracting subscores from a legacy run requires renaming those files first.

Usage: python scripts/extract_subscores.py [timestamp]
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from output_utils import find_run_dir, OUTPUT_ROOT

AGENT_AXES = {
    "manufacturing": ["manufacturability"],            # manufacturing control & tunability (rubric, 评分标准/标准.md)
    "delivery": ["delivery_efficiency"],               # target-tissue delivery efficiency
    "safety": ["biosafety"],                           # biological safety
    "mechanism": ["multi_target_synergy", "durability"],  # multi-target synergy + effect durability
}

JSON_OBJ_RE = re.compile(r"\{[^{}]*\}")


def last_json_object(line: str):
    """Return the last JSON-decodable {...} object on the line, else None."""
    for cand in reversed(JSON_OBJ_RE.findall(line)):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    return None


def extract(ts: str) -> dict:
    run = find_run_dir(ts)
    materials, missing, src_files = {}, [], []
    for agent, axes in AGENT_AXES.items():
        # Originals first, then redo files (--experts-only reruns) by mtime
        # so the NEWEST redo's subscores override for the same material names.
        files = sorted(run.glob(f"task100_{agent}_{ts}_part*.txt")) +                 sorted(run.glob(f"task100_{agent}_{ts}_redo*_part*.txt"),
                       key=lambda p: p.stat().st_mtime)
        for p in files:
            src_files.append(p.name)
            for lineno, raw in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
                line = raw.strip()
                if not line:
                    continue
                obj = last_json_object(line)
                if "|" in line:
                    name = line.split("|")[0].strip()
                elif obj is not None and ";" in line:
                    # Tolerated variant: "Material_Name; {...}" (some adapters
                    # drop the original record and keep only name + JSON tail)
                    name = line.split(";")[0].strip()
                else:
                    missing.append({"file": p.name, "line": lineno,
                                    "reason": "not a pipe-separated record",
                                    "raw": line[:120]})
                    continue
                if obj is None:
                    missing.append({"file": p.name, "line": lineno, "material": name,
                                    "reason": "no valid JSON subscore tail"})
                    continue
                for axis in axes:
                    v = obj.get(axis)
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        materials.setdefault(name, {})[axis] = v
                    else:
                        missing.append({"file": p.name, "line": lineno,
                                        "material": name,
                                        "reason": f"axis '{axis}' missing/non-numeric in JSON tail"})
    return {"ts": ts, "source_files": src_files, "materials": materials, "missing": missing}


def main():
    ts = sys.argv[1] if len(sys.argv) > 1 else None
    if ts is None:
        candidates = (list(OUTPUT_ROOT.glob("task100_designer_*_part1.txt"))
                      + list(OUTPUT_ROOT.glob("run_*/task100_designer_*_part1.txt")))
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
        ts = re.search(r"task100_designer_(\d+)_part1", latest.name).group(1)

    payload = extract(ts)
    out_path = find_run_dir(ts) / f"subscores_{ts}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    n_axes = sum(len(v) for v in payload["materials"].values())
    print(f"Wrote {out_path}")
    print(f"  materials: {len(payload['materials'])}, axis entries: {n_axes}, "
          f"missing/unparsed: {len(payload['missing'])}")


if __name__ == "__main__":
    main()
