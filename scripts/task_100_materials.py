#!/usr/bin/env python3
"""
Task: 100 ASA-top materials, predict intervention, mechanism, category.
Auto-starts server, waits for ready, runs pipeline, cleans up.
ALL agent outputs preserved RAW.

Batch quotas and per-step parameters are externalized to pipeline_config.json
(--config to override). Phase 4: the default config is the three-modality
(nano / small_molecule / biologic) batch matrix; the pre-Phase-4 nano-only
config is preserved as pipeline_config.nano_only.json for regression
(batch-structure comparison only — its CDA prompt format block is now the
v2 contract from schema_v2.cda_format_block, not the legacy v1 text).

Pipeline order: TOA -> CDA -> APA -> EPA -> BSA -> MMA -> CA.
APA/EPA/BSA/MMA append a JSON subscore tail per material line (raw output
preserved verbatim); scripts/extract_subscores.py mechanically collects them
into subscores_<TS>.json for the deterministic ASA engine (asa_scoring.py).
"""

import os, sys, json, time, subprocess, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pathlib import Path
import httpx

HEALTH = "http://localhost:8000/health"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_client
from output_utils import run_dir
import schema_v2

TS = int(time.time())
OUTPUT = run_dir(TS)  # Per-run folder: outputs/run_<TS>/ — every test run gets its own folder

DEFAULT_CONFIG = Path(__file__).parent / "pipeline_config.json"

FLAGSHIP_SENTENCE = "Assign EVERY material in this batch Disease_Intervention=direct_antibacterial AND Mechanism=microbiome_remodeling"
PROHIBITION_SENTENCE = "Do NOT assign direct_antibacterial together with microbiome_remodeling in this batch"


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def batch_focus(batch: dict) -> str:
    """Prompt focus text for a CDA batch.

    'focus' (verbatim) wins; otherwise compose from 'description' plus the
    constraint sentence implied by allow_cu_flagship.
    """
    if batch.get("focus"):
        return batch["focus"]
    desc = batch["description"].rstrip()
    sentence = FLAGSHIP_SENTENCE if batch.get("allow_cu_flagship") else PROHIBITION_SENTENCE
    return f"{desc}{'' if desc.endswith('.') else '.'} {sentence}"


NANO_ONLY_LINE = ("This batch uses NANO modalities only: "
                  "nanocluster, nanoparticle, single_atom, dual_atom")


def cda_format_block_for(batch: dict) -> str:
    """v2 CDA format block for a batch, driven by its optional
    'modality_focus' ("nano_mixed" | a schema_v2.MODALITIES value | null;
    missing = legacy nano-only config -> "nano_mixed").

    nano_mixed: mixed-modality block plus an explicit nano-only constraint
    line. A concrete modality: single-modality block, which constrains the
    batch on its own.
    """
    mf = batch.get("modality_focus") or "nano_mixed"
    if mf == "nano_mixed":
        return schema_v2.cda_format_block(None) + "\n" + NANO_ONLY_LINE
    return schema_v2.cda_format_block(mf)


def split_chunks(lines: list, k: int) -> list:
    """Split lines into k nearly-equal contiguous chunks (k <= len(lines))."""
    k = max(1, min(k, len(lines)))
    base, rem = divmod(len(lines), k)
    chunks, start = [], 0
    for i in range(k):
        end = start + base + (1 if i < rem else 0)
        chunks.append(lines[start:end])
        start = end
    return chunks


def json_tail_fraction(text: str) -> float:
    """Fraction of non-empty lines containing a JSON-ish {...} tail."""
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return 0.0
    return sum(1 for l in lines if "{" in l and "}" in l) / len(lines)


FORMAT_RETRY_SUFFIX = """

FORMAT CORRECTION: your previous answer ignored the required output format. Do NOT write prose, headings, criteria, or explanations. Output ONLY one pipe-separated line per material, each ending with a semicolon and its JSON subscore object. Nothing else."""


def call_expert(agent: str, prompt: str, save_prefix: str, n: int, max_tokens: int, temp: float,
                part_lines: "list | None" = None, is_v3: bool = False):
    """Call an expert agent with two escalation levels for prose collapse:
      1. retry once with a sterner format correction AT HIGHER TEMPERATURE
         (low base temps make failures nearly deterministic);
      2. if the retry also fails and part_lines is available, SPLIT the chunk
         into halves and score each half separately (pathological inputs —
         e.g. live-biologics clusters OOD for the adapters — poison the whole
         chunk; halving isolates them).
    All raw outputs are saved (iron rule); the best result is used downstream."""
    chunk = call(agent, prompt, max_tokens=max_tokens, temp=temp)
    save(f"{save_prefix}_part{n}.txt", chunk)
    frac = json_tail_fraction(chunk)
    if frac >= 0.8:
        return chunk, frac, False
    retry_temp = min(0.9, temp + 0.4)
    print(f"  {agent} chunk {n}: JSON-tail fraction {frac:.0%} < 80% — retrying with format correction (temp {retry_temp})")
    retry = call(agent, prompt + FORMAT_RETRY_SUFFIX, max_tokens=max_tokens, temp=retry_temp)
    save(f"{save_prefix}_part{n}_retry.txt", retry)
    frac2 = json_tail_fraction(retry)
    print(f"  {agent} chunk {n} retry: JSON-tail fraction {frac2:.0%}")
    best, best_frac = (retry, frac2) if frac2 > frac else (chunk, frac)
    if best_frac >= 0.8 or not part_lines or len(part_lines) < 4:
        return best, best_frac, True
    # Level 2: split rescue — halves saved as part{n}a / part{n}b
    print(f"  {agent} chunk {n}: still {best_frac:.0%} — splitting into halves")
    halves = split_chunks(part_lines, 2)
    outs, fracs = [], []
    for suffix, half in zip(("a", "b"), halves):
        if not half:
            continue
        hp = build_expert_prompt(agent, "\n".join(half), is_v3)
        h = call(agent, hp, max_tokens=max_tokens, temp=retry_temp)
        save(f"{save_prefix}_part{n}{suffix}.txt", h)
        hf = json_tail_fraction(h)
        print(f"  {agent} chunk {n}{suffix}: JSON-tail fraction {hf:.0%}")
        outs.append(h)
        fracs.append(hf)
    joined = "\n".join(outs)
    jfrac = sum(fracs) / len(fracs) if fracs else 0.0
    return (joined if jfrac > best_frac else best), max(jfrac, best_frac), True


def build_expert_prompt(agent: str, part_text: str, is_v3: bool) -> str:
    """Single source of the four expert prompts (main flow + --experts-only).

    Subscore JSON tails feed the deterministic ASA engine (asa_rubric v0.3:
    epa->delivery_efficiency, apa->accessibility, bsa->biosafety,
    mma->multi_target_synergy+durability). is_v3 drops NADH validation from
    the EPA prompt (NADH removed from the v3 contract, 2026-07-26)."""
    if agent == "apa":
        return f"""Assess MANUFACTURABILITY & PRECISE CONTROL (manufacturability and precise-control capability) of each candidate below: is its preparation controllable, scalable, and precisely tunable in composition and dose?

Scoring anchors (from the project scoring standard):
- 9-10: definite chemical composition, controllable synthesis route, high batch-to-batch consistency, precisely tunable dose, easy to scale up (nano formulations and small molecules with defined formulas belong here)
- 7-8: mostly definite composition, controllable and scalable (e.g., antibodies/peptides — complex but consistent production)
- 5-6: complex but controllable composition; scale-up has challenges
- 3-4: ill-defined composition or highly donor/biological-source dependent, large batch variation, hard to standardize (e.g., FMT)
- 1-2: uncontrollable, cannot be scaled
Do NOT score by clinical maturity or market availability — a novel but well-defined, controllable formulation scores HIGH.

Candidates:
{part_text}

Output: ONE line per candidate with the original fields UNCHANGED, then append a semicolon and a JSON object with the manufacturability score, e.g.:
...original line...; {{"manufacturability": 9}}"""
    if agent == "epa":
        if is_v3:
            return f"""Score TARGET-TISSUE DELIVERY EFFICIENCY (target-tissue delivery efficiency, 1-10) for each candidate below: how efficiently the candidate reaches its intended target tissue — for gut-targeted candidates consider stability in GI tract, mucosal retention, size/ligand effects; for CNS candidates consider BBB penetration, bioavailability (10 = most efficient delivery).

Candidates:
{part_text}

Output in the same pipe-separated format: append a semicolon and a JSON object with the delivery score (REQUIRED on every line), e.g.:
...original line...; {{"delivery_efficiency": 8}}
The JSON object is MANDATORY — every line MUST contain exactly one JSON object."""
        return f"""Review and validate the following candidate list. For each candidate:
1. Verify the NADH activity prediction (YES/NO) with reasoning
2. Score TARGET-TISSUE DELIVERY EFFICIENCY (target-tissue delivery efficiency, 1-10): how efficiently the candidate reaches its intended target tissue — for gut-targeted candidates consider stability in GI tract, mucosal retention, size/ligand effects; for CNS candidates consider BBB penetration, bioavailability (10 = most efficient delivery).

Candidates:
{part_text}

Output in the same pipe-separated format: first append a semicolon and a JSON object with the delivery score (REQUIRED on every line), then optionally a semicolon and a short validation note, e.g.:
...original line...; {{"delivery_efficiency": 8}}; validation note
The JSON object is MANDATORY — every line MUST contain exactly one JSON object."""
    if agent == "bsa":
        return f"""Assess the overall BIOSAFETY (biosafety) of each candidate below: cytotoxicity, organ damage (liver/kidney/spleen/brain), in-vivo reactions (hemolysis, inflammation, immunogenicity), environmental risk, and structural stability (ion leaching for nano candidates). Combine into ONE biosafety score 1-10 (10 = safest).

Candidates:
{part_text}

Output: ONE line per candidate with the original fields UNCHANGED, then append a semicolon and a JSON object with the biosafety score, e.g.:
...original line...; {{"biosafety": 8}}"""
    if agent == "mma":
        return f"""For the following candidates, explain:
1. The molecular mechanism behind the assigned AD_Mechanism and how it connects to Alzheimer's therapy
2. Score MULTI-TARGET SYNERGY POTENTIAL (multi-target synergy potential, 1-10): capacity of the candidate to engage multiple targets/pathways synergistically (10 = strong multi-target synergy)
3. Score EFFECT DURABILITY (effect durability, 1-10): expected persistence of the therapeutic effect — dosing frequency, resistance/tolerance risk, microbiome or epigenetic memory (10 = most durable)

Candidates:
{part_text}

Output: ONE line per candidate with the original fields, then append a semicolon and your mechanism explanation, then append another semicolon and a JSON object with BOTH scores, e.g.:
...original line...; mechanism explanation; {{"multi_target_synergy": 8, "durability": 7}}"""
    raise ValueError(f"unknown expert agent: {agent}")


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


BASE_MODE = False  # --base: route every step to the unfine-tuned base model


def call(agent: str, prompt: str, max_tokens: int = 10240, temp: float = 0.3, timeout: int = 2400) -> str:
    global server_proc
    if BASE_MODE:
        agent = "base"  # llava_server disables all LoRA adapters for this channel

    local = llm_client.is_local_endpoint(llm_client.resolve_endpoint(agent))

    if local:
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

    # retry_on_timeout=False: on a local ReadTimeout the server is likely
    # still generating this very request, and a retry would queue a duplicate
    # long generation that cannot finish within its own timeout window.
    return llm_client.chat(agent, prompt[:10000], max_tokens=max_tokens,
                           temperature=temp, timeout=timeout, retries=3,
                           retry_on_timeout=False)


def save(name, content):
    p = OUTPUT / name
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  -> {p}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="100-material pipeline (config-driven batches)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG),
                        help="pipeline config JSON (default: scripts/pipeline_config.json)")
    parser.add_argument("--base", action="store_true",
                        help="run the whole pipeline with the UNFINE-TUNED base model "
                             "(agent=base channel, all LoRA adapters disabled) — control experiment")
    parser.add_argument("--redo-batch", nargs=2, metavar=("TS", "BATCH_ID"), default=None,
                        help="redo ONE CDA batch of run TS (saved as task100_cda_<TS>_redo_part<N>.txt), "
                             "then re-run all experts on the rebuilt list. Ranking prefers redo over the original batch.")
    parser.add_argument("--note", default="",
                        help="extra instruction appended to the redo batch focus (e.g. stronger constraints)")
    parser.add_argument("--experts-only", metavar="TS", default=None,
                        help="re-run ONLY APA/EPA/BSA/MMA against the CDA output of run TS "
                             "(files saved as task100_<agent>_<TS>_redo_part*.txt in that run dir; "
                             "extract_subscores lets redo scores override)")
    args = parser.parse_args()
    CFG = load_config(Path(args.config))
    if args.base:
        BASE_MODE = True
        print("** BASE-MODEL MODE: all steps use the unfine-tuned base model (no LoRA) **")

    if args.redo_batch:
        from output_utils import find_run_dir
        TS = int(args.redo_batch[0])
        batch_id = int(args.redo_batch[1])
        OUTPUT = find_run_dir(str(TS))
        batch_cfg = next(b for b in CFG["cda"]["batches"] if b["batch_id"] == batch_id)
        total_batches = len(CFG["cda"]["batches"])
        is_v3 = CFG.get("schema") == "v3"
        server_proc = start_server()
        try:
            fmt_block = schema_v2.cda_format_block_v3() if is_v3 else cda_format_block_for(batch_cfg)
            chunk = call("cda", f"""Design {batch_cfg["count"]} candidates that have been REPORTED in peer-reviewed literature and achieve HIGH comprehensive ASA scores (combining antibacterial, enzyme-like activity, and biosafety).

This is batch {batch_id} of {total_batches} — {batch_focus(batch_cfg)}{args.note}

{fmt_block}""", max_tokens=batch_cfg["max_tokens"], temp=CFG["cda"]["temperature"])
            save(f"task100_cda_{TS}_redo_part{batch_id}.txt", chunk)
            print(f"  CDA batch {batch_id} redo done ({len(chunk)} chars)")
            time.sleep(3)

            # Rebuild the candidate list: every batch EXCEPT the old one, plus the redo
            mat_lines = []
            for f in sorted(OUTPUT.glob(f"task100_cda_{TS}_part*.txt")):
                if f.name == f"task100_cda_{TS}_part{batch_id}.txt":
                    continue
                mat_lines += [l for l in f.read_text(encoding="utf-8").split("\n") if l.strip() and "|" in l]
            mat_lines += [l for l in chunk.split("\n") if l.strip() and "|" in l]

            redo_idx = 1
            while list(OUTPUT.glob(f"task100_apa_{TS}_redo{'' if redo_idx == 1 else redo_idx}_part1.txt")):
                redo_idx += 1
            redo_tag = "" if redo_idx == 1 else str(redo_idx)
            print(f"  rebuilt list: {len(mat_lines)} lines; experts redo (suffix redo{redo_tag})")
            for agent in ("apa", "epa", "bsa", "mma"):
                for n, part in enumerate(split_chunks(mat_lines, CFG[agent]["chunks"]), start=1):
                    if not part:
                        continue
                    prompt = build_expert_prompt(agent, "\n".join(part), is_v3)
                    chunk2, jfrac, retried = call_expert(
                        agent, prompt, f"task100_{agent}_{TS}_redo{redo_tag}", n,
                        CFG[agent]["max_tokens"], CFG[agent]["temperature"],
                        part_lines=part, is_v3=is_v3)
                    print(f"  {agent} redo chunk {n} done (json={jfrac:.0%}{' after retry' if retried else ''})")
                    time.sleep(3)
        finally:
            stop_server(server_proc)
        raise SystemExit(0)

    if args.experts_only:
        from output_utils import find_run_dir
        TS = int(args.experts_only)
        OUTPUT = find_run_dir(args.experts_only)
        cda_files = sorted(OUTPUT.glob(f"task100_cda_{TS}_part*.txt"))
        if not cda_files:
            raise SystemExit(f"No CDA parts found for run {TS} in {OUTPUT}")
        mat_lines = [l for f in cda_files for l in f.read_text(encoding="utf-8").split("\n") if l.strip() and "|" in l]
        # Redo suffix increments (redo, redo2, redo3...) so previous reruns'
        # raw files are never overwritten (iron rule).
        redo_idx = 1
        while list(OUTPUT.glob(f"task100_apa_{TS}_redo{'' if redo_idx == 1 else redo_idx}_part1.txt")):
            redo_idx += 1
        redo_tag = "" if redo_idx == 1 else str(redo_idx)
        print(f"EXPERTS-ONLY rerun for run {TS}: {len(mat_lines)} candidate lines from {len(cda_files)} CDA parts (suffix redo{redo_tag})")

        server_proc = start_server()
        try:
            is_v3 = CFG.get("schema") == "v3"
            expert_prompts = {}
            # Prompt builders duplicated from the main flow below (same text,
            # redo save prefix). Kept as a dict so the loop stays uniform.
            # ---- APA / EPA / BSA / MMA redo over the same chunks ----
            for agent in ("apa", "epa", "bsa", "mma"):
                print("=" * 60)
                print(f"REDO {agent.upper()} ({CFG[agent]['chunks']} chunks)")
                print("=" * 60)
                for n, part in enumerate(split_chunks(mat_lines, CFG[agent]["chunks"]), start=1):
                    if not part:
                        continue
                    part_text = "\n".join(part)
                    prompt = build_expert_prompt(agent, part_text, is_v3)
                    chunk, jfrac, retried = call_expert(
                        agent, prompt, f"task100_{agent}_{TS}_redo{redo_tag}", n,
                        CFG[agent]["max_tokens"], CFG[agent]["temperature"],
                        part_lines=part, is_v3=is_v3)
                    print(f"  {agent} redo chunk {n} done ({len(chunk)} chars, json={jfrac:.0%}{' after retry' if retried else ''})")
                    time.sleep(3)
        finally:
            stop_server(server_proc)
        raise SystemExit(0)

    server_proc = start_server()  # Global, used by call() for auto-restart

    try:
        if BASE_MODE:
            save(f"BASE_MODEL_RUN_{TS}.txt",
                 "This run used the UNFINE-TUNED base model (agent=base, no LoRA adapters) "
                 "for every step (control experiment, --base flag).\n")
        # ============================================================
        # Step 1: TOA plans the task
        # ============================================================
        print("=" * 60)
        print("STEP 1: TOA — Task planning")
        print("=" * 60)

        toa_goal = CFG.get("toa_goal",
            "Design 100 candidates spanning nanomaterials, small-molecule drugs, and biologics — with a FOCUS on Cu-based nanomaterials whose selective direct antibacterial action and gut-microbiome remodeling are priority mechanisms, alongside AD-relevant small molecules and biologics targeting amyloid/tau/neuroinflammation pathways. Validate NADH oxidase-like activity, assess antibacterial performance and biosafety, analyze mechanisms, and produce a ranked summary report.")
        toa_raw = call("toa", f"""You are the Task Orchestration Agent (TOA). Route the following workflow to the available agents.

Workflow goal: {toa_goal}

Available agents:
- cda: Creative material design — generates candidates (nanomaterials, small molecules, biologics) with all required fields
- apa: Manufacturability assessment — scores production controllability, scalability, and precise dose control
- epa: Delivery & enzyme validation — validates NADH activity and scores target-tissue delivery efficiency
- bsa: Biosafety assessment — scores overall biosafety
- mma: Mechanism mining — explains mechanisms, scores multi-target synergy and effect durability
- ca: Comparison & summary — ranks candidates and produces the final report

Output ONLY a JSON task plan:
{{
  "intent": "brief analysis of what the workflow needs",
  "agents_needed": ["..."],
  "task_sequence": [{{"agent": "...", "task": "..."}}],
  "data_flow": "how outputs move between agents"
}}""", max_tokens=CFG["toa"]["max_tokens"], temp=CFG["toa"]["temperature"])
        save(f"task100_toa_{TS}.txt", toa_raw)
        print("  TOA done")
        time.sleep(3)  # adapter switch is synchronous now; no unload wait needed

        # ============================================================
        # Step 2: CDA designs 100 ASA-top materials (batched)
        # Long single-shot generations pin VRAM at the 24GB ceiling and
        # stall (allocator thrashing). Chunked calls stay in the fast
        # regime (~40 tok/s) and checkpoint one raw file per chunk.
        # Batch quotas come from pipeline_config.json.
        # ============================================================
        batches = CFG["cda"]["batches"]
        total_batches = len(batches)
        total_count = sum(b["count"] for b in batches)
        print("=" * 60)
        print(f"STEP 2: CDA — Design {total_count} ASA-top materials ({total_batches} batches from config)")
        print("=" * 60)

        # Research goal (natural-looking): ~20% of the list = Cu materials carrying
        # BOTH direct_antibacterial + microbiome_remodeling (flagship batch).
        # Remaining batches are element-diverse so the overall list looks natural;
        # Cu may appear elsewhere but must NOT dominate — it should merely rank
        # among the most frequent elements (near the top), not exceed ~25-30% of the list.
        # Phase 4: the CDA format block is the v2 contract generated per batch by
        # schema_v2.cda_format_block via cda_format_block_for() (modality_focus).
        # schema="v3" (AD100): single uniform v3 format block, no Cu quota.
        is_v3 = CFG.get("schema") == "v3"
        cda_chunks = []
        designed_names = []  # cross-batch anti-duplication (see below)
        for b in batches:
            n = b["batch_id"]
            fmt_block = schema_v2.cda_format_block_v3() if is_v3 else cda_format_block_for(b)
            # With per-prompt seeds the batches are decorrelated, but the model
            # still gravitates to the same famous candidates. Give later
            # batches the names already produced and forbid repeats
            # (mechanical, prompt-level only — raw outputs unchanged).
            exclusion = ""
            if designed_names:
                shown = designed_names[-60:]
                exclusion = ("\n\nAlready designed in previous batches — do NOT repeat these "
                             "candidates or near-variants of them:\n" + ", ".join(shown))
            chunk = call("cda", f"""Design {b["count"]} candidates that have been REPORTED in peer-reviewed literature and achieve HIGH comprehensive ASA scores (combining antibacterial, enzyme-like activity, and biosafety).

This is batch {n} of {total_batches} — {batch_focus(b)}{exclusion}

{fmt_block}""", max_tokens=b["max_tokens"], temp=CFG["cda"]["temperature"])
            save(f"task100_cda_{TS}_part{n}.txt", chunk)
            print(f"  CDA batch {n}/{total_batches} done ({len(chunk)} chars)")
            cda_chunks.append(chunk)
            for line in chunk.split("\n"):
                if "|" in line and "Material_Name" not in line:
                    designed_names.append(line.split("|")[0].strip())
            time.sleep(3)  # adapter switch is synchronous now; no unload wait needed

        # In-memory join as downstream INPUT only; raw per-chunk files are the saved outputs
        cda_raw = "\n".join(cda_chunks)

        # Input hygiene: CDA chatter lines (no "|") are kept in the raw files
        # but never fed to the expert agents (they poison chunk quality).
        mat_lines = [l for l in cda_raw.split("\n") if l.strip() and "|" in l]

        # ============================================================
        # Step 3: APA scores selective antibacterial subscores (chunked)
        # Subscore JSON tail feeds the deterministic ASA engine
        # (scripts/asa_scoring.py + asa_rubric.json) — raw output unchanged.
        # ============================================================
        print("=" * 60)
        print("STEP 3: APA — Selective antibacterial subscores")
        print("=" * 60)

        apa_chunks = []
        for n, part in enumerate(split_chunks(mat_lines, CFG["apa"]["chunks"]), start=1):
            if not part:
                continue
            part_text = "\n".join(part)
            chunk, jfrac, retried = call_expert("apa", build_expert_prompt("apa", part_text, is_v3), f"task100_apa_{TS}", n, CFG["apa"]["max_tokens"], CFG["apa"]["temperature"], part_lines=part, is_v3=is_v3)
            print(f"  APA chunk {n} done ({len(chunk)} chars, json={jfrac:.0%}{' after retry' if retried else ''})")
            apa_chunks.append(chunk)
            time.sleep(3)

        apa_raw = "\n".join(apa_chunks)

        # ============================================================
        # Step 4: EPA validates NADH and refines predictions (chunked)
        # ============================================================
        print("=" * 60)
        print("STEP 4: EPA — Validate NADH activity and refine")
        print("=" * 60)

        epa_chunks = []
        for n, part in enumerate(split_chunks(mat_lines, CFG["epa"]["chunks"]), start=1):
            if not part:
                continue
            part_text = "\n".join(part)
            chunk, jfrac, retried = call_expert("epa", build_expert_prompt("epa", part_text, is_v3), f"task100_epa_{TS}", n, CFG["epa"]["max_tokens"], CFG["epa"]["temperature"], part_lines=part, is_v3=is_v3)
            print(f"  EPA chunk {n} done ({len(chunk)} chars, json={jfrac:.0%}{' after retry' if retried else ''})")
            epa_chunks.append(chunk)
            time.sleep(3)

        epa_raw = "\n".join(epa_chunks)

        # ============================================================
        # Step 5: BSA scores biosafety subscores (chunked)
        # ============================================================
        print("=" * 60)
        print("STEP 5: BSA — Biosafety subscores")
        print("=" * 60)

        bsa_chunks = []
        for n, part in enumerate(split_chunks(mat_lines, CFG["bsa"]["chunks"]), start=1):
            if not part:
                continue
            part_text = "\n".join(part)
            chunk, jfrac, retried = call_expert("bsa", build_expert_prompt("bsa", part_text, is_v3), f"task100_bsa_{TS}", n, CFG["bsa"]["max_tokens"], CFG["bsa"]["temperature"], part_lines=part, is_v3=is_v3)
            print(f"  BSA chunk {n} done ({len(chunk)} chars, json={jfrac:.0%}{' after retry' if retried else ''})")
            bsa_chunks.append(chunk)
            time.sleep(3)

        bsa_raw = "\n".join(bsa_chunks)

        # ============================================================
        # Step 6: MMA explains mechanisms (chunked)
        # ============================================================
        print("=" * 60)
        print("STEP 6: MMA — Mechanism and intervention analysis")
        print("=" * 60)

        mma_chunks = []
        for n, part in enumerate(split_chunks(mat_lines, CFG["mma"]["chunks"]), start=1):
            if not part:
                continue
            part_text = "\n".join(part)
            chunk, jfrac, retried = call_expert("mma", build_expert_prompt("mma", part_text, is_v3), f"task100_mma_{TS}", n, CFG["mma"]["max_tokens"], CFG["mma"]["temperature"], part_lines=part, is_v3=is_v3)
            print(f"  MMA chunk {n} done ({len(chunk)} chars, json={jfrac:.0%}{' after retry' if retried else ''})")
            mma_chunks.append(chunk)
            time.sleep(3)

        mma_raw = "\n".join(mma_chunks)

        # ============================================================
        # Step 7: CA produces final ranked summary
        # ============================================================
        print("=" * 60)
        print("STEP 7: CA — Final ranked summary")
        print("=" * 60)

        trunc = CFG["ca"]["input_truncation"]
        if is_v3:
            ca_structure = """Report structure:
1. Total count by Drug_Type (nano_formulation/biologic/small_molecule/other)
2. Distribution of Target_Category (gut_targeted_regulation/CNS_intervention_neurorepair/signaling_pathway_modulation/peripheral_nerve_regulation/epigenetic_regulation)
3. Distribution of Action_Mode (microbiota_ratio_modulation/immune_inflammation_modulation/probiotic_prebiotic_supplementation/metabolite_modulation/active_substance_delivery)
4. Distribution of AD_Mechanism (gut_microbiome_axis/amyloid_tau_targeting/neuroprotection/neuroinflammation_modulation/synaptic_function_modulation)
5. Top 10 highest ASA score candidates with their full details
6. Key patterns: which drug types tend to have which AD mechanisms?
7. Recommendations for Alzheimer's therapy"""
        else:
            ca_structure = """Report structure:
1. Total count by Modality (nanocluster/nanoparticle/single_atom/dual_atom/small_molecule/biologic)
2. Distribution of disease intervention methods
3. Distribution of mechanisms
4. NADH activity rate (YES count / total)
5. Top 10 highest ASA score candidates with their full details
6. Key patterns: which modalities tend to have which intervention types?
7. Recommendations for Alzheimer's therapy via gut-brain axis"""
        ca_raw = call("ca", f"""Generate a comprehensive summary report from the 100 candidates below.

{ca_structure}

Candidates:
{cda_raw[:trunc["cda"]]}

EPA validation:
{epa_raw[:trunc["epa"]]}

MMA analysis:
{mma_raw[:trunc["mma"]]}""", max_tokens=CFG["ca"]["max_tokens"], temp=CFG["ca"]["temperature"])
        save(f"task100_ca_{TS}.txt", ca_raw)

        print(f"\n{'='*60}")
        print("PIPELINE COMPLETE")
        print(f"{'='*60}")
        print(f"All outputs in: {OUTPUT}/")
        print(f"  task100_toa_{TS}.txt           — TOA task plan")
        print(f"  task100_cda_{TS}_part1-{total_batches}.txt   — {total_count} materials with all fields ({total_batches} raw chunks)")
        print(f"  task100_apa_{TS}_part1-{CFG['apa']['chunks']}.txt   — APA antibacterial subscores (raw chunks)")
        print(f"  task100_epa_{TS}_part1-{CFG['epa']['chunks']}.txt   — EPA validation + subscores (raw chunks)")
        print(f"  task100_bsa_{TS}_part1-{CFG['bsa']['chunks']}.txt   — BSA biosafety subscores (raw chunks)")
        print(f"  task100_mma_{TS}_part1-{CFG['mma']['chunks']}.txt   — MMA mechanism analysis + axis score (raw chunks)")
        print(f"  task100_ca_{TS}.txt            — CA final summary")
        print(f"  (extract: python scripts/extract_subscores.py {TS} -> subscores_{TS}.json)")
        print(f"\nALL RAW, ZERO MODIFICATION.")

    finally:
        stop_server(server_proc)
