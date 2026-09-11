#!/usr/bin/env python3
"""
Per-run output folder convention.

Every test run gets its own folder:  outputs/run_<TS>/
Producers (task_100, run_base, discover, batch_eval) call run_dir(ts) at start.
Consumers (formula_lookup, rank, excel) call find_run_dir(ts) — which falls
back to the flat outputs/ root for legacy runs saved before this convention.
"""

from pathlib import Path

OUTPUT_ROOT = Path("E:/Cu-agent/outputs")


def run_dir(ts, prefix: str = "run") -> Path:
    """Create (if needed) and return outputs/<prefix>_<ts>/ for a NEW test run."""
    d = OUTPUT_ROOT / f"{prefix}_{ts}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_run_dir(ts, prefix: str = "run") -> Path:
    """Return outputs/<prefix>_<ts>/ if it exists, else the flat outputs/ root
    (legacy layout — reads/writes stay next to the run's original files)."""
    d = OUTPUT_ROOT / f"{prefix}_{ts}"
    return d if d.is_dir() else OUTPUT_ROOT
