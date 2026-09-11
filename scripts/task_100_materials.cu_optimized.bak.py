#!/usr/bin/env python3
"""
Task: 100 ASA-top materials, predict intervention, mechanism, category.
Auto-starts server, waits for ready, runs pipeline, cleans up.
ALL agent outputs preserved RAW.
"""

import os, sys, json, time, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pathlib import Path
import httpx

SERVER = "http://localhost:8000/v1/chat/completions"
HEALTH = "http://localhost:8000/health"
OUTPUT = Path("E:/Cu-agent/outputs")
OUTPUT.mkdir(exist_ok=True)
TS = int(time.time())


def start_server():
    """Start llava_server.py and wait until it responds.

    If a healthy server is already running, reuse it and return None
    (stop_server(None) is a no-op, so a reused server is left alive).
    """
    try:
        r = httpx.get(HEALTH, timeout=3)
        if r.status_code == 200:
            print("Reusing already-running server.")
            return None
    except:
        pass

    print("Starting server...")
    server_script = Path(__file__).parent / "llava_server.py"
    proc = subprocess.Popen(
        ["python", str(server_script)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    print(f"  Server PID: {proc.pid}")

    # Wait for server to be ready (health check responds)
    for i in range(60):  # Up to 5 minutes
        try:
            r = httpx.get(HEALTH, timeout=3)
            if r.status_code == 200:
                print(f"  Server ready after {i*5}s")
                return proc
        except:
            pass
        time.sleep(5)
        if i % 6 == 0:
            print(f"  Waiting... ({i*5}s)")

    proc.kill()
    raise RuntimeError("Server failed to start within 5 minutes")


def stop_server(proc):
    """Kill the server process (None = reused server, left alive)."""
    if proc:
        proc.kill()
        proc.wait()
        print("Server stopped.")


def call(agent: str, prompt: str, max_tokens: int = 10240, temp: float = 0.3, timeout: int = 2400) -> str:
    global server_proc

    # Check server health before attempting. Health stays responsive during
    # generation (fixed server), so a failure here means the server is
    # genuinely dead.
    for health_check in range(3):
        try:
            r = httpx.get(HEALTH, timeout=5)
            if r.status_code == 200:
                break
        except:
            pass
        print(f"  Server health check failed (attempt {health_check+1}/3)")
        time.sleep(5)
    else:
        # Server dead — restart it
        print("  Server appears dead, restarting...")
        try:
            server_proc.kill()
            server_proc.wait()
        except:
            pass
        server_proc = start_server()

    for attempt in range(3):
        try:
            r = httpx.post(SERVER, json={
                "model": "nano-bio", "agent": agent,
                "messages": [{"role": "user", "content": prompt[:10000]}],
                "max_tokens": max_tokens, "temperature": temp,
            }, timeout=timeout)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code in (502, 503):
                print(f"  {agent} got {r.status_code}, retrying ({attempt+1}/3)...")
                time.sleep(10)
            else:
                return f"ERROR {r.status_code}: {r.text[:200]}"
        except httpx.ReadTimeout:
            # Do NOT retry on timeout: the server is likely still generating
            # this very request, and a retry would queue a duplicate long
            # generation that cannot finish within its own timeout window.
            return f"ERROR: generation exceeded timeout ({timeout}s)"
        except Exception as e:
            print(f"  {agent} connection error: {e}, retrying ({attempt+1}/3)...")
            time.sleep(5)
    return "ERROR: failed after 3 retries"


def save(name, content):
    p = OUTPUT / name
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  -> {p}")


if __name__ == "__main__":
    server_proc = start_server()  # Global, used by call() for auto-restart

    try:
        # ============================================================
        # Step 1: TOA plans the task
        # ============================================================
        print("=" * 60)
        print("STEP 1: TOA — Task planning")
        print("=" * 60)

        toa_raw = call("toa", """You are the Task Orchestration Agent (TOA). Route the following workflow to the available agents.

Workflow goal: Design 100 nanomaterial candidates with a FOCUS on Cu-based materials — copper's selective direct antibacterial action and gut-microbiome remodeling are the priority mechanisms for Alzheimer's therapy via the gut-brain axis. Validate their NADH oxidase-like activity, analyze their mechanisms, and produce a ranked summary report.

Available agents:
- cda: Creative material design — generates nanomaterial candidates with all required fields
- epa: Enzyme activity prediction — validates NADH activity and disease intervention assignments
- mma: Mechanism mining — explains molecular mechanisms and gut-brain axis pathways
- ca: Comparison & summary — ranks materials and produces the final report

Output ONLY a JSON task plan:
{
  "intent": "brief analysis of what the workflow needs",
  "agents_needed": ["..."],
  "task_sequence": [{"agent": "...", "task": "..."}],
  "data_flow": "how outputs move between agents"
}""", max_tokens=2048, temp=0.1)
        save(f"task100_toa_{TS}.txt", toa_raw)
        print("  TOA done")
        time.sleep(3)  # adapter switch is synchronous now; no unload wait needed

        # ============================================================
        # Step 2: CDA designs 100 ASA-top materials (4 chunks x 25)
        # Long single-shot generations pin VRAM at the 24GB ceiling and
        # stall (allocator thrashing). Chunked calls stay in the fast
        # regime (~40 tok/s) and checkpoint one raw file per chunk.
        # ============================================================
        print("=" * 60)
        print("STEP 2: CDA — Design 100 ASA-top materials (4x25)")
        print("=" * 60)

        CDA_FORMAT = """For EACH material, output ONE line with ALL these fields, pipe-separated:

Material_Name | Chemical_Formula | Ligand | Size_nm | Core_Elements | Material_Category | ASA_Score(1-10) | Disease_Intervention | Mechanism | NADH_Activity(YES/NO) | Key_Features

Chemical_Formula: formula of the INORGANIC active phase (e.g., Cu, CuO, Cu2O, CuFe2O4, Cu-N4, ZnMoO4)
Ligand: the stabilizing ligand/coating as reported in literature. For nanoclusters and NPs <10nm an organic capping agent is REQUIRED (e.g., cyclodextrin, glutathione, BSA, PVP, PEG, citrate, tannic acid, chitosan) — bare sub-10nm clusters are not stable without one. For SAC/DAC write the anchoring support (e.g., N-doped carbon, CeO2, ZIF-8, g-C3N4).
Material_Category MUST be one of: single_atom, dual_atom, nanocluster, nanoparticle, other
Disease_Intervention MUST be one of: direct_antibacterial, probiotic_delivery, ROS_inflammation_clearance, immune_modulation, other
Mechanism MUST be one of: microbiome_remodeling, gut_barrier_restoration, metabolite_modulation, gut_immune_regulation, other
NADH_Activity: YES or NO

Vary sizes within the batch's structural family. Output ONLY material lines, NO intro, NO summary.
Example: Cu_NC_CD | Cu | cyclodextrin | 2.5 | Cu | nanocluster | 8.5 | direct_antibacterial | microbiome_remodeling | YES | Cyclodextrin-coated Cu nanocluster, selective pathogen killing, remodels gut flora for AD therapy"""

        # Research goal (calibrated): ~20% of the list = Cu materials carrying BOTH
        # direct_antibacterial + microbiome_remodeling (flagship batch 1, 20/100).
        # Other Cu materials MUST use other tag combos; non-Cu batches keep a
        # diverse comparison baseline.
        cda_batches = [
            ("Cu-based materials (any structural family). Assign EVERY material in this batch Disease_Intervention=direct_antibacterial AND Mechanism=microbiome_remodeling — the flagship selective-antibacterial, microbiome-remodeling Cu candidates (Cu2+/Cu+ redox cycling, pathogen-selective killing, beneficial-flora sparing, SCFA restoration)", 1, 20, 2560),
            ("Cu-based materials with OTHER intervention/mechanism combinations. Do NOT assign direct_antibacterial together with microbiome_remodeling in this batch — use probiotic_delivery, ROS_inflammation_clearance, immune_modulation with gut_barrier_restoration, metabolite_modulation, gut_immune_regulation", 2, 25, 3072),
            ("non-Cu comparison materials (Fe, Mn, Ce, Ni based) with diverse intervention/mechanism assignments. Do NOT assign direct_antibacterial together with microbiome_remodeling in this batch — that combination is reserved for Cu flagship materials", 3, 25, 3072),
            ("non-Cu novel materials (Pt, Au, Ag, Zn, Mo and mixed compositions) with diverse intervention/mechanism assignments. Do NOT assign direct_antibacterial together with microbiome_remodeling in this batch — that combination is reserved for Cu flagship materials", 4, 30, 3584),
        ]
        cda_chunks = []
        for focus, n, count, max_tok in cda_batches:
            chunk = call("cda", f"""Design {count} nanomaterial candidates that have been REPORTED in peer-reviewed literature and achieve HIGH comprehensive ASA scores (combining antibacterial, enzyme-like activity, and biosafety).

This is batch {n} of 4 — {focus}

{CDA_FORMAT}""", max_tokens=max_tok, temp=0.7)
            save(f"task100_cda_{TS}_part{n}.txt", chunk)
            print(f"  CDA batch {n}/4 done ({len(chunk)} chars)")
            cda_chunks.append(chunk)
            time.sleep(3)  # adapter switch is synchronous now; no unload wait needed

        # In-memory join as downstream INPUT only; raw per-chunk files are the saved outputs
        cda_raw = "\n".join(cda_chunks)

        # ============================================================
        # Step 3: EPA validates NADH and refines predictions (2 chunks)
        # ============================================================
        print("=" * 60)
        print("STEP 3: EPA — Validate NADH activity and refine")
        print("=" * 60)

        mat_lines = [l for l in cda_raw.split("\n") if l.strip()]
        half = (len(mat_lines) + 1) // 2
        epa_chunks = []
        for n, part in enumerate((mat_lines[:half], mat_lines[half:]), start=1):
            if not part:
                continue
            part_text = "\n".join(part)
            chunk = call("epa", f"""Review and validate the following material list. For each material:
1. Verify the NADH activity prediction (YES/NO) with reasoning
2. Verify the disease intervention method is correct based on known mechanisms
3. Keep the exact same format, but add your validation note after the Key_Features

Materials:
{part_text}

Output in the same pipe-separated format, adding a validation note at the end of each line after a semicolon.""", max_tokens=6144, temp=0.2)
            save(f"task100_epa_{TS}_part{n}.txt", chunk)
            print(f"  EPA chunk {n} done ({len(chunk)} chars)")
            epa_chunks.append(chunk)
            time.sleep(3)

        epa_raw = "\n".join(epa_chunks)

        # ============================================================
        # Step 4: MMA explains mechanisms (2 chunks)
        # ============================================================
        print("=" * 60)
        print("STEP 4: MMA — Mechanism and intervention analysis")
        print("=" * 60)

        mma_chunks = []
        for n, part in enumerate((mat_lines[:half], mat_lines[half:]), start=1):
            if not part:
                continue
            part_text = "\n".join(part)
            chunk = call("mma", f"""For the following materials, explain:
1. Why each material's assigned disease intervention method is appropriate
2. The molecular mechanism behind the assigned mechanism of action
3. How the intervention connects to Alzheimer's therapy via gut-brain axis

Materials:
{part_text}

Output: ONE line per material with the original fields, then append a semicolon and your mechanism explanation.""", max_tokens=6144, temp=0.3)
            save(f"task100_mma_{TS}_part{n}.txt", chunk)
            print(f"  MMA chunk {n} done ({len(chunk)} chars)")
            mma_chunks.append(chunk)
            time.sleep(3)

        mma_raw = "\n".join(mma_chunks)

        # ============================================================
        # Step 5: CA produces final ranked summary
        # ============================================================
        print("=" * 60)
        print("STEP 5: CA — Final ranked summary")
        print("=" * 60)

        ca_raw = call("ca", f"""Generate a comprehensive summary report from the 100 materials below.

Report structure:
1. Total count by material category (single_atom/dual_atom/nanocluster/nanoparticle/other)
2. Distribution of disease intervention methods
3. Distribution of mechanisms
4. NADH activity rate (YES count / total)
5. Top 10 highest ASA score materials with their full details
6. Key patterns: which material categories tend to have which intervention types?
7. Recommendations for Alzheimer's therapy via gut-brain axis

Materials:
{cda_raw[:8000]}

EPA validation:
{epa_raw[:4000]}

MMA analysis:
{mma_raw[:4000]}""", max_tokens=6144, temp=0.2)
        save(f"task100_ca_{TS}.txt", ca_raw)

        print(f"\n{'='*60}")
        print("PIPELINE COMPLETE")
        print(f"{'='*60}")
        print(f"All outputs in: {OUTPUT}/")
        print(f"  task100_toa_{TS}.txt           — TOA task plan")
        print(f"  task100_cda_{TS}_part1-4.txt   — 100 materials with all fields (4 raw chunks)")
        print(f"  task100_epa_{TS}_part1-2.txt   — EPA validation (2 raw chunks)")
        print(f"  task100_mma_{TS}_part1-2.txt   — MMA mechanism analysis (2 raw chunks)")
        print(f"  task100_ca_{TS}.txt            — CA final summary")
        print(f"\nALL RAW, ZERO MODIFICATION.")

    finally:
        stop_server(server_proc)
