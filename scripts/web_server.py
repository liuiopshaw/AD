#!/usr/bin/env python3
"""
Web chat server — TOA orchestration entry (Kimi-style UI).

Independent of llava_server.py (:8000). This service (:8001) only PROXIES the
upstream LLM server; it never starts/stops/modifies it.

- GET  /                     -> static/index.html
- GET  /static/*             -> scripts/static/
- GET  /api/health           -> upstream /health proxy
- POST /api/orchestrate      -> SSE stream running the pipeline semantics
                                TOA -> CDA(batches) -> APA -> EPA -> BSA -> MMA -> CA
- GET  /api/sessions         -> chat session list (outputs/chat/)
- GET  /api/sessions/<id>    -> one session's history

Upstream LLM base URL: env CU_AGENT_LLM_BASE (default http://localhost:8000).

Iron rules (CLAUDE.md): every agent output is saved RAW — no cleaning, no
truncation beyond the pipeline's own prompt/input conventions, no fallback
data. Per-request raw outputs land in outputs/run_<TS>/ (output_utils.run_dir).
"""

import os, sys, json, time, asyncio, re, uuid
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
from output_utils import run_dir, OUTPUT_ROOT  # noqa: E402
import schema_v2  # noqa: E402

LLM_BASE = os.environ.get("CU_AGENT_LLM_BASE", "http://localhost:8000").rstrip("/")
CONFIG_PATH = BASE_DIR / "pipeline_config.json"
STATIC_DIR = BASE_DIR / "static"
CHAT_DIR = OUTPUT_ROOT / "chat"
GEN_TIMEOUT = 2400  # long generations, same as the pipeline

# ---------------------------------------------------------------------------
# Pipeline semantics — mirrored from task_100_materials.py (read-only reuse).
# NOTE: batch_focus / cda_format_block_for / split_chunks are re-implemented
# here verbatim instead of importing task_100_materials, because importing
# that module executes its module-level run_dir(TS) and would create a
# spurious empty outputs/run_<TS>/ folder on every web server start.
# ---------------------------------------------------------------------------

FLAGSHIP_SENTENCE = "Assign EVERY material in this batch Disease_Intervention=direct_antibacterial AND Mechanism=microbiome_remodeling"
PROHIBITION_SENTENCE = "Do NOT assign direct_antibacterial together with microbiome_remodeling in this batch"


def batch_focus(batch: dict) -> str:
    """Same logic as task_100_materials.batch_focus."""
    if batch.get("focus"):
        return batch["focus"]
    desc = batch["description"].rstrip()
    sentence = FLAGSHIP_SENTENCE if batch.get("allow_cu_flagship") else PROHIBITION_SENTENCE
    return f"{desc}{'' if desc.endswith('.') else '.'} {sentence}"


NANO_ONLY_LINE = ("This batch uses NANO modalities only: "
                  "nanocluster, nanoparticle, single_atom, dual_atom")


def cda_format_block_for(batch: dict) -> str:
    """Same logic as task_100_materials.cda_format_block_for."""
    mf = batch.get("modality_focus") or "nano_mixed"
    if mf == "nano_mixed":
        return schema_v2.cda_format_block(None) + "\n" + NANO_ONLY_LINE
    return schema_v2.cda_format_block(mf)


def split_chunks(lines: list, k: int) -> list:
    """Same logic as task_100_materials.split_chunks."""
    k = max(1, min(k, len(lines)))
    base, rem = divmod(len(lines), k)
    chunks, start = [], 0
    for i in range(k):
        end = start + base + (1 if i < rem else 0)
        chunks.append(lines[start:end])
        start = end
    return chunks


# TOA prompt — identical to the TOA step of task_100_materials.py, plus the
# user's chat message appended as an explicit request line.
TOA_PROMPT_TEMPLATE = """You are the Task Orchestration Agent (TOA). Route the following workflow to the available agents.

Workflow goal: Design 100 candidates spanning nanomaterials, small-molecule drugs, and biologics — with a FOCUS on Cu-based nanomaterials whose selective direct antibacterial action and gut-microbiome remodeling are priority mechanisms, alongside AD-relevant small molecules and biologics targeting amyloid/tau/neuroinflammation pathways. Validate NADH oxidase-like activity, assess antibacterial performance and biosafety, analyze mechanisms, and produce a ranked summary report.

Available agents:
- cda: Creative material design — generates candidates (nanomaterials, small molecules, biologics) with all required fields
- apa: Manufacturability assessment — scores production controllability, scalability, and precise dose control
- epa: Delivery & enzyme validation — validates NADH activity and scores target-tissue delivery efficiency
- bsa: Biosafety assessment — scores overall biosafety
- mma: Mechanism mining — explains mechanisms, scores multi-target synergy and effect durability
- ca: Comparison & summary — ranks candidates and produces the final report

Output ONLY a JSON task plan:
{
  "intent": "brief analysis of what the user request needs",
  "needs_pipeline": true,
  "agents_needed": ["..."],
  "task_sequence": [{"agent": "...", "task": "..."}],
  "data_flow": "how outputs move between agents"
}

Routing rule: set "needs_pipeline": true ONLY when the user request asks to design, screen, rank, or evaluate candidate materials/drugs. For any other request (questions about the system itself, domain knowledge Q&A, explanations, casual chat), set "needs_pipeline": false and put the single best-suited agent to answer in "agents_needed" (use "ca" when unsure)."""

# Direct-answer prompt for requests that do not need the screening pipeline
# (system questions, domain Q&A, explanations, casual chat).
DIRECT_ANSWER_TEMPLATE = """You are an expert assistant of the Nano-Bio Evaluator multi-agent system (Alzheimer's gut-brain-axis intervention discovery spanning nanomaterials, small-molecule drugs, and biologics).

Answer the user's request directly and concisely, in the user's language. If the question is about the system's agents or workflow, answer accurately from this roster: TOA (task orchestration/routing), CDA (candidate design), APA (antibacterial scoring), EPA (enzyme activity), BSA (biosafety), MMA (mechanism mining), CA (comparison & summary).

User request: {message}"""

VALID_ANSWER_AGENTS = ("ca", "toa", "mma", "epa", "bsa", "apa", "cda", "ea")


def parse_plan(toa_raw: str) -> dict:
    """Best-effort extraction of the TOA plan JSON; {} when unparseable
    (callers then keep the default pipeline behavior)."""
    start, end = toa_raw.find("{"), toa_raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(toa_raw[start:end + 1])
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}

CDA_PROMPT_TEMPLATE = """Design {count} candidates that have been REPORTED in peer-reviewed literature and achieve HIGH comprehensive ASA scores (combining antibacterial, enzyme-like activity, and biosafety).

This is batch {n} of {total_batches} — {focus}

{format_block}"""

APA_PROMPT_TEMPLATE = """Assess MANUFACTURABILITY & PRECISE CONTROL (manufacturability and precise-control capability) of each candidate below: is its preparation controllable, scalable, and precisely tunable in composition and dose?

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

EPA_PROMPT_TEMPLATE = """Review and validate the following candidate list. For each candidate:
1. Verify the NADH activity prediction (YES/NO) with reasoning
2. Score TARGET-TISSUE DELIVERY EFFICIENCY (target-tissue delivery efficiency, 1-10): how efficiently the candidate reaches its intended target tissue — for gut-targeted candidates consider stability in GI tract, mucosal retention, size/ligand effects; for CNS candidates consider BBB penetration, bioavailability (10 = most efficient delivery).

Candidates:
{part_text}

Output in the same pipe-separated format: first append a semicolon and a JSON object with the delivery score (REQUIRED on every line), then optionally a semicolon and a short validation note, e.g.:
...original line...; {{"delivery_efficiency": 8}}; validation note
The JSON object is MANDATORY — every line MUST contain exactly one JSON object."""

BSA_PROMPT_TEMPLATE = """Assess the overall BIOSAFETY (biosafety) of each candidate below: cytotoxicity, organ damage (liver/kidney/spleen/brain), in-vivo reactions (hemolysis, inflammation, immunogenicity), environmental risk, and structural stability (ion leaching for nano candidates). Combine into ONE biosafety score 1-10 (10 = safest).

Candidates:
{part_text}

Output: ONE line per candidate with the original fields UNCHANGED, then append a semicolon and a JSON object with the biosafety score, e.g.:
...original line...; {{"biosafety": 8}}"""

MMA_PROMPT_TEMPLATE = """For the following candidates, explain:
1. The molecular mechanism behind the assigned AD_Mechanism and how it connects to Alzheimer's therapy
2. Score MULTI-TARGET SYNERGY POTENTIAL (multi-target synergy potential, 1-10): capacity of the candidate to engage multiple targets/pathways synergistically (10 = strong multi-target synergy)
3. Score EFFECT DURABILITY (effect durability, 1-10): expected persistence of the therapeutic effect — dosing frequency, resistance/tolerance risk, microbiome or epigenetic memory (10 = most durable)

Candidates:
{part_text}

Output: ONE line per candidate with the original fields, then append a semicolon and your mechanism explanation, then append another semicolon and a JSON object with BOTH scores, e.g.:
...original line...; mechanism explanation; {{"multi_target_synergy": 8, "durability": 7}}"""

CA_PROMPT_TEMPLATE = """Generate a comprehensive summary report from the 100 materials below.

Report structure:
1. Total count by Modality (nanocluster/nanoparticle/single_atom/dual_atom/small_molecule/biologic)
2. Distribution of disease intervention methods
3. Distribution of mechanisms
4. NADH activity rate (YES count / total)
5. Top 10 highest ASA score candidates with their full details
6. Key patterns: which modalities tend to have which intervention types?
7. Recommendations for Alzheimer's therapy via gut-brain axis

Materials:
{cda}

EPA validation:
{epa}

MMA analysis:
{mma}"""

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Nano-Bio Evaluator — TOA Chat", version="0.1")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

orch_lock = asyncio.Lock()

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def save_raw(out_dir: Path, name: str, content: str) -> None:
    """Save agent output RAW (zero modification)."""
    with open(out_dir / name, "w", encoding="utf-8") as f:
        f.write(content)


async def call_agent(client: httpx.AsyncClient, agent: str, prompt: str,
                     max_tokens: int, temp: float) -> str:
    """Single upstream call, same request shape as task_100_materials.call()."""
    r = await client.post(
        f"{LLM_BASE}/v1/chat/completions",
        json={
            "model": "nano-bio", "agent": agent,
            "messages": [{"role": "user", "content": prompt[:10000]}],
            "max_tokens": max_tokens, "temperature": temp,
        },
        timeout=GEN_TIMEOUT,
    )
    if r.status_code != 200:
        raise RuntimeError(f"upstream {agent} returned HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def load_cfg() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def session_path(session_id: str) -> Path:
    return CHAT_DIR / f"{session_id}.json"


def load_session(session_id: str) -> dict:
    p = session_path(session_id)
    if p.is_file():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"session_id": session_id, "created": int(time.time()), "messages": []}


def save_session(sess: dict) -> None:
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    with open(session_path(sess["session_id"]), "w", encoding="utf-8") as f:
        json.dump(sess, f, ensure_ascii=False, indent=2)


async def orchestrate_stream(message: str, session_id: str):
    """SSE generator: run the full pipeline semantics, yielding one JSON
    event per step. Raw outputs are saved per-step BEFORE the event is
    yielded, so a mid-stream failure still leaves completed raw files."""
    ts = int(time.time())
    out = run_dir(ts)
    run_dir_str = str(out)
    sess = load_session(session_id)
    sess["messages"].append({"role": "user", "content": message, "ts": ts})
    sess["run_dir"] = run_dir_str
    # Full event sequence is kept in the session so the frontend can replay
    # the whole orchestration (cards + agent contents) when reopened.
    events = sess.setdefault("events", [])

    def emit(ev: dict) -> str:
        events.append(ev)
        return sse(ev)

    async def finish(status: str, assistant_content: str):
        sess["messages"].append({
            "role": "assistant", "content": assistant_content,
            "run_dir": run_dir_str, "status": status, "ts": int(time.time()),
        })
        save_session(sess)

    try:
        cfg = load_cfg()
        async with httpx.AsyncClient() as client:
            # ---- Step 1: TOA plan ----
            # (prompt kept verbatim from the pipeline; user request appended
            # by concatenation — the template contains literal JSON braces
            # and must NOT go through str.format)
            toa_raw = await call_agent(
                client, "toa", TOA_PROMPT_TEMPLATE + "\n\nUser request: " + message,
                cfg["toa"]["max_tokens"], cfg["toa"]["temperature"])
            save_raw(out, f"task100_toa_{ts}.txt", toa_raw)
            yield emit({"type": "plan", "content": toa_raw})

            # ---- Intent routing: honor TOA's needs_pipeline decision ----
            plan_obj = parse_plan(toa_raw)
            needs_pipeline = bool(plan_obj.get("needs_pipeline", True))

            if not needs_pipeline:
                wanted = plan_obj.get("agents_needed") or []
                answer_agent = next(
                    (a for a in wanted if a in VALID_ANSWER_AGENTS), "ca")
                yield emit({"type": "agent_start", "agent": answer_agent,
                            "batch": 1})
                answer = await call_agent(
                    client, answer_agent,
                    DIRECT_ANSWER_TEMPLATE.format(message=message),
                    4096, 0.3)
                save_raw(out, f"chat_{answer_agent}_{ts}.txt", answer)
                yield emit({"type": "direct_answer",
                            "agent": answer_agent, "content": answer})
                await finish("done", answer)
                yield emit({"type": "done", "run_dir": run_dir_str})
                return

            # ---- Step 2: CDA batches ----
            batches = cfg["cda"]["batches"]
            total_batches = len(batches)
            cda_chunks = []
            for b in batches:
                n = b["batch_id"]
                yield emit({"type": "agent_start", "agent": "cda", "batch": n})
                chunk = await call_agent(
                    client, "cda",
                    CDA_PROMPT_TEMPLATE.format(
                        count=b["count"], n=n, total_batches=total_batches,
                        focus=batch_focus(b), format_block=cda_format_block_for(b)),
                    b["max_tokens"], cfg["cda"]["temperature"])
                save_raw(out, f"task100_cda_{ts}_part{n}.txt", chunk)
                cda_chunks.append(chunk)
                yield emit({"type": "agent_done", "agent": "cda", "batch": n,
                            "chars": len(chunk), "content": chunk})

            cda_raw = "\n".join(cda_chunks)
            mat_lines = [l for l in cda_raw.split("\n") if l.strip()]

            # ---- Steps 3-6: APA / EPA / BSA / MMA (chunked per config) ----
            chunked_steps = [
                ("apa", APA_PROMPT_TEMPLATE),
                ("epa", EPA_PROMPT_TEMPLATE),
                ("bsa", BSA_PROMPT_TEMPLATE),
                ("mma", MMA_PROMPT_TEMPLATE),
            ]
            raws = {}
            for agent, template in chunked_steps:
                chunks_out = []
                for n, part in enumerate(
                        split_chunks(mat_lines, cfg[agent]["chunks"]), start=1):
                    if not part:
                        continue
                    yield emit({"type": "agent_start", "agent": agent, "batch": n})
                    chunk = await call_agent(
                        client, agent,
                        template.format(part_text="\n".join(part)),
                        cfg[agent]["max_tokens"], cfg[agent]["temperature"])
                    save_raw(out, f"task100_{agent}_{ts}_part{n}.txt", chunk)
                    chunks_out.append(chunk)
                    yield emit({"type": "agent_done", "agent": agent,
                                "batch": n, "chars": len(chunk),
                                "content": chunk})
                raws[agent] = "\n".join(chunks_out)

            # ---- Step 7: CA summary ----
            yield emit({"type": "agent_start", "agent": "ca", "batch": 1})
            trunc = cfg["ca"]["input_truncation"]
            ca_raw = await call_agent(
                client, "ca",
                CA_PROMPT_TEMPLATE.format(
                    cda=cda_raw[:trunc["cda"]],
                    epa=raws["epa"][:trunc["epa"]],
                    mma=raws["mma"][:trunc["mma"]]),
                cfg["ca"]["max_tokens"], cfg["ca"]["temperature"])
            save_raw(out, f"task100_ca_{ts}.txt", ca_raw)
            yield emit({"type": "summary", "content": ca_raw})

        await finish("done", ca_raw)
        yield emit({"type": "done", "run_dir": run_dir_str})
    except Exception as e:
        # Graceful error: report and end the stream; completed raw files stay.
        try:
            await finish("error", f"ERROR: {e}")
        except Exception:
            pass
        yield sse({"type": "error", "message": str(e), "run_dir": run_dir_str})


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/health")
async def api_health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{LLM_BASE}/health")
        return {"llm_base": LLM_BASE, "status": "ok" if r.status_code == 200 else "error",
                "upstream_status": r.status_code}
    except Exception as e:
        return {"llm_base": LLM_BASE, "status": "unreachable", "error": str(e)}


@app.post("/api/orchestrate")
async def api_orchestrate(payload: dict):
    message = (payload.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)
    session_id = payload.get("session_id") or uuid.uuid4().hex[:16]
    if not SESSION_ID_RE.match(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)

    if orch_lock.locked():
        async def busy():
            yield sse({"type": "error",
                       "message": "An orchestration task is already in progress; please wait for it to finish before submitting a new request."})
        return StreamingResponse(busy(), media_type="text/event-stream",
                                 headers={"X-Session-Id": session_id})

    async def locked_stream():
        async with orch_lock:
            async for chunk in orchestrate_stream(message, session_id):
                yield chunk

    return StreamingResponse(locked_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Session-Id": session_id})


@app.get("/api/sessions")
async def api_sessions():
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(CHAT_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime,
                    reverse=True):
        try:
            with open(p, "r", encoding="utf-8") as f:
                s = json.load(f)
            first_user = next((m for m in s.get("messages", [])
                               if m.get("role") == "user"), None)
            items.append({
                "session_id": s.get("session_id", p.stem),
                "created": s.get("created"),
                "run_dir": s.get("run_dir"),
                "title": (first_user["content"][:40] if first_user else "(empty session)"),
                "message_count": len(s.get("messages", [])),
            })
        except Exception:
            continue
    return {"sessions": items}


@app.get("/api/sessions/{session_id}")
async def api_session(session_id: str):
    if not SESSION_ID_RE.match(session_id):
        return JSONResponse({"error": "invalid session_id"}, status_code=400)
    p = session_path(session_id)
    if not p.is_file():
        return JSONResponse({"error": "session not found"}, status_code=404)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1",
                port=int(os.environ.get("CU_AGENT_WEB_PORT", "8001")),
                log_level="info")
