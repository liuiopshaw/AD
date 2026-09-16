#!/usr/bin/env python3
"""
Control experiment: RAW Qwen3-VL-8B base model (NO LoRA agents), ONE single call.
Task = the task100 material-design task, WITHOUT the Cu-optimization clauses
(no Cu flagship quota, no Cu preference rules, non-Cu example line).

The server persists every completion to outputs/server_responses/ — so this
script tolerates the 40-90 min single-shot generation: if the HTTP read times
out, it polls the persistence folder for the result instead of losing it.

Output saved RAW to outputs/base_task100_<TS>.txt.
"""

import os, sys, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_client
from output_utils import run_dir

OUTPUT = Path("E:/Cu-agent/outputs")  # server_responses/ audit folder stays flat here

# task100 design prompt WITHOUT any Cu-optimization content
PROMPT = """Design 100 nanomaterial candidates that have been REPORTED in peer-reviewed literature and achieve HIGH comprehensive ASA scores (combining antibacterial, enzyme-like activity, and biosafety), for Alzheimer's therapy research via the gut-brain axis.

For EACH material, output ONE line with ALL these fields, pipe-separated:

Material_Name | Chemical_Formula | Ligand | Size_nm | Core_Elements | Material_Category | ASA_Score(1-10) | Disease_Intervention | Mechanism | NADH_Activity(YES/NO) | Key_Features

Chemical_Formula: formula of the INORGANIC active phase (e.g., Fe3O4, CeO2, ZnO)
Ligand: the stabilizing ligand/coating as reported in literature. For nanoclusters and NPs <10nm an organic capping agent is REQUIRED (e.g., cyclodextrin, glutathione, BSA, PVP, PEG, citrate, tannic acid, chitosan). For SAC/DAC write the anchoring support (e.g., N-doped carbon, CeO2, ZIF-8, g-C3N4).
Material_Category MUST be one of: single_atom, dual_atom, nanocluster, nanoparticle, other
Disease_Intervention MUST be one of: direct_antibacterial, probiotic_delivery, ROS_inflammation_clearance, immune_modulation, other
Mechanism MUST be one of: microbiome_remodeling, gut_barrier_restoration, metabolite_modulation, gut_immune_regulation, other
NADH_Activity: YES or NO

Cover ALL 4 size categories roughly evenly.
Use VARIED elements (Fe, Cu, Co, Mn, Ce, Ni, Pt, Au, Ag, Zn, Mo) — do NOT focus on any single element.
Include both well-known materials AND novel designs from the literature.

Output format (ONE LINE per material, NO intro, NO summary):
Fe3O4_NP_Cit | Fe3O4 | citrate | 15 | Fe,O | nanoparticle | 8.2 | ROS_inflammation_clearance | microbiome_remodeling | YES | Citrate-coated magnetite nanoparticles, Fenton-like ROS clearance, biocompatible"""


def save(content: str, ts: int, t0: float, src=None):
    out = run_dir(ts) / f"base_task100_{ts}.txt"  # per-run folder
    out.write_text(content, encoding="utf-8")
    lines = [l for l in content.split("\n") if "|" in l]
    print(f"Done in {time.time()-t0:.0f}s. Saved RAW: {out}" + (f" (from {src.name})" if src else ""))
    print(f"  {len(content)} chars, {len(lines)} pipe-lines")


def main():
    ts = int(time.time())
    t0 = time.time()
    local = llm_client.is_local_endpoint(llm_client.resolve_endpoint("base"))
    print("ONE call to RAW base model (agent=base, no LoRA)." if local else
          "ONE call via the 'base' endpoint from llm_endpoints.json.")
    if local:
        print("Server persists the completion to outputs/server_responses/ — result survives client timeout.")
    # Single attempt, no timeout retry: on the local server a ReadTimeout means
    # the 40-90 min generation is still running and a retry would duplicate it.
    result = llm_client.chat("base", PROMPT, max_tokens=10240, temperature=0.7,
                             timeout=900, retries=1, retry_on_timeout=False)
    if not result.startswith("ERROR"):
        save(result, ts, t0)
        return
    if not local:
        # Cloud endpoint: nothing is persisted server-side — just fail.
        print(result)
        raise SystemExit(1)
    print(f"{result} — falling back to polling server_responses/ ...")

    resp_dir = OUTPUT / "server_responses"
    deadline = t0 + 7200  # up to 2h
    while time.time() < deadline:
        cands = [p for p in resp_dir.glob("base_*.txt") if p.stat().st_mtime >= t0 - 5]
        if cands:
            save(max(cands, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8"),
                 ts, t0, src=max(cands, key=lambda p: p.stat().st_mtime))
            return
        time.sleep(30)
    print("ERROR: no persisted completion within 2h")


if __name__ == "__main__":
    main()
