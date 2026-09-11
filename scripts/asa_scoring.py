#!/usr/bin/env python3
"""
Deterministic ASA scoring engine (Phase 3).

Pure functions — the agent subscores are inputs, the rubric is external
configuration (scripts/asa_rubric.json). Changing the rubric re-scores
historical subscores WITHOUT re-running any agent.

Axis model (rubric-driven):
  - axis WITH subscores  -> weighted sum of sub-dimension scores (missing
                            sub-dimension counts as 0 and is reported, never
                            silently filled)
  - axis WITHOUT subscores (e.g. microbiome_remodeling) -> the agent's direct
                            axis score is taken as-is

Consistency (from run_nano_bio_eval.py, lines 90-92):
  Cj = 1 - (1/3) * sum((Wij - Wbar)^2) / Wbar
  Sj = Wbar * Cj
where Wij are the axis scores and Wbar their mean.

Total semantics:
  total_raw = sum(axis_score * axis_weight)
  total_adj = total_raw * Cj   (when consistency.enabled; else total_adj = total_raw)
  RANKING USES total_adj. total_raw is kept for audit.
  NOTE: total_adj = total_raw * Cj is a deliberate variant of the original
  Sj = Wbar * Cj — it keeps the axis weights in the total instead of a plain
  mean, while applying the same consistency discount.

Usage:
  python scripts/asa_scoring.py [subscores.json] [--rubric path]
  (no file argument -> read JSON from stdin)

Input JSON: either the full extract_subscores payload ({"materials": {...}}),
or {material_name: {axis: {sub: score}}}, or a single {axis: {sub: score}}.
"""

import json
import sys
from pathlib import Path

WEIGHT_TOL = 1e-6
DEFAULT_RUBRIC = Path(__file__).parent / "asa_rubric.json"


def load_rubric(path) -> dict:
    """Load and validate a rubric. Weights must sum to 1 (no normalization —
    a rubric that does not sum to 1 is an error, not something to fix)."""
    with open(path, "r", encoding="utf-8") as f:
        rubric = json.load(f)
    axes = rubric.get("axes")
    if not axes:
        raise ValueError("rubric has no 'axes'")
    total = sum(a["weight"] for a in axes.values())
    if abs(total - 1.0) > WEIGHT_TOL:
        raise ValueError(f"axis weights sum to {total}, expected 1.0 (tol {WEIGHT_TOL})")
    for name, a in axes.items():
        if "weight" not in a:
            raise ValueError(f"axis '{name}' missing 'weight'")
        subs = a.get("subscores") or {}
        if subs and abs(sum(subs.values()) - 1.0) > WEIGHT_TOL:
            raise ValueError(
                f"axis '{name}' subscore weights sum to {sum(subs.values())}, expected 1.0")
    return rubric


def axis_score(subscores, axis_def) -> tuple:
    """Score one axis.

    Returns (score, missing):
      - axis_def has subscores -> weighted sum; a missing/non-numeric
        sub-dimension counts as 0 and its name is appended to `missing`.
      - axis_def has no subscores -> the agent's direct axis score: a plain
        number, or the single numeric value of a one-key dict. Absent ->
        (0.0, ["<axis>"]).
    """
    subs_def = axis_def.get("subscores") or {}
    if not subs_def:
        if isinstance(subscores, (int, float)) and not isinstance(subscores, bool):
            return float(subscores), []
        if isinstance(subscores, dict):
            vals = [v for v in subscores.values()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if vals:
                return float(vals[0]), []
        return 0.0, ["<axis>"]

    missing = []
    total = 0.0
    for sub, w in subs_def.items():
        v = subscores.get(sub) if isinstance(subscores, dict) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total += w * float(v)
        else:
            missing.append(sub)
    return total, missing


def cj_consistency(scores: list, clamp: "list | None" = None) -> tuple:
    """Cj = 1 - (1/3)*sum((Wij-Wbar)^2)/Wbar ; Sj = Wbar*Cj.
    Wbar == 0 -> (1.0, 0.0).
    clamp (e.g. [0, 1] from the rubric) bounds Cj so that lopsided
    candidates get a consistency discount without breaking the score
    scale (raw formula can go negative with 4+ axes)."""
    wbar = sum(scores) / len(scores)
    if wbar == 0:
        return 1.0, 0.0
    cj = 1 - (1.0 / 3.0) * sum((s - wbar) ** 2 for s in scores) / wbar
    if clamp:
        cj = max(clamp[0], min(clamp[1], cj))
    return cj, wbar * cj


def compute_asa(axis_scores: dict, rubric: dict) -> dict:
    """Compute the deterministic ASA for one material.

    axis_scores: {axis_name: {sub: score}} or {axis_name: direct_score}.
    Returns {total, total_raw, total_adj, axes, consistency_cj,
             consistency_sj, rubric_version, missing}.
    `total` is an alias of `total_adj` (the ranking key).
    """
    axes_def = rubric["axes"]
    per_axis, missing = {}, []
    for name, adef in axes_def.items():
        entry = (axis_scores or {}).get(name)
        if entry is None:
            per_axis[name] = 0.0
            missing.append(name)
            continue
        score, miss = axis_score(entry, adef)
        per_axis[name] = score
        missing.extend(f"{name}.{m}" for m in miss)

    # modality_adjustments: reserved hook (empty in rubric v0.1). When
    # populated, per-modality weight overrides apply here — config only.
    total_raw = sum(per_axis[n] * axes_def[n]["weight"] for n in axes_def)

    cons = rubric.get("consistency") or {}
    if cons.get("enabled"):
        cj, sj = cj_consistency(list(per_axis.values()), clamp=cons.get("clamp"))
        # Variant semantics: discount the WEIGHTED total by Cj (original Sj
        # discounts the plain mean Wbar). See module docstring.
        total_adj = total_raw * cj
    else:
        cj, sj = 1.0, total_raw
        total_adj = total_raw

    return {
        "total": total_adj,
        "total_raw": total_raw,
        "total_adj": total_adj,
        "axes": per_axis,
        "consistency_cj": cj,
        "consistency_sj": sj,
        "rubric_version": rubric.get("version"),
        "missing": missing,
    }


def _materials_of(payload: dict) -> dict:
    """Accept the extract payload, a {material: axes} map, or a single
    {axis: subs} map; always return {material: axes}."""
    if "materials" in payload:
        return payload["materials"]
    if payload and all(isinstance(v, dict) for v in payload.values()):
        # Heuristic: a single axis map has axis-name keys whose values hold
        # only numbers (or are numbers); a material map holds dicts of dicts.
        if any(any(isinstance(x, dict) for x in v.values()) for v in payload.values()):
            return payload
    return {"<single>": payload}


def main():
    args = [a for a in sys.argv[1:]]
    rubric_path = DEFAULT_RUBRIC
    if "--rubric" in args:
        i = args.index("--rubric")
        rubric_path = args[i + 1]
        del args[i:i + 2]
    rubric = load_rubric(rubric_path)

    text = open(args[0], encoding="utf-8").read() if args else sys.stdin.read()
    payload = json.loads(text)

    rows = []
    for name, axes in _materials_of(payload).items():
        r = compute_asa(axes, rubric)
        rows.append((name, r))
    rows.sort(key=lambda kv: (-kv[1]["total_adj"], kv[0]))

    print(f"rubric v{rubric.get('version')} ({rubric_path})")
    for name, r in rows:
        print(f"{name}: total_adj={r['total_adj']:.3f} total_raw={r['total_raw']:.3f} "
              f"Cj={r['consistency_cj']:.3f} axes={ {k: round(v, 2) for k, v in r['axes'].items()} }"
              + (f" MISSING={r['missing']}" if r["missing"] else ""))


if __name__ == "__main__":
    main()
