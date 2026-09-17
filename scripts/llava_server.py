#!/usr/bin/env python3
"""
Qwen3-VL-8B Server with LoRA multi-adapter support.
Base model loaded ONCE. LoRA adapters swapped via PEFT add_adapter/set_adapter.
No base model reload — switching is fast (<2s) and reliable.

Blocking inference runs in a worker thread so /health stays responsive
during long generations. Requests are serialized by a lock because only
one adapter can be active at a time.
"""

import os, time, logging, asyncio
from typing import List
from contextlib import asynccontextmanager
import torch, uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from peft import PeftModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nano-bio-server")

MODEL_PATH = "E:/models/qwen/Qwen3-VL-8B-Instruct"
LORA_DIR = "E:/Cu-agent/models/lora_enhanced"

peft_model = None   # Base model + PEFT wrapper, lives forever
processor = None
current_agent = None

AGENTS = {
    "extractor": "Knowledge Extraction",
    "manufacturing": "Antibacterial Prediction — production QC & manufacturability scoring",
    "delivery": "Target-Tissue Delivery Efficiency Scoring",
    "safety": "Biosafety Assessment",
    "mechanism": "Mechanism Mining — synergy + durability scoring",
    "coordinator": "Task Orchestration",
    "ranker": "Comparison & Ranking",
    "designer": "Creative Designing — Generates novel nanomaterial candidates from API data",
    "base": "Raw Qwen3-VL-8B base model (NO LoRA) — control experiments",
}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "nano-bio"
    messages: List[ChatMessage]
    max_tokens: int = 10240
    temperature: float = 0.3
    agent: str = "extractor"


def cast_adapter_to_bf16():
    """LoRA weights are saved in fp32 (2x VRAM). Cast to bf16 for inference —
    halves adapter VRAM (cda 2.3GB->1.15GB) and keeps the 24GB card below the
    thrashing ceiling. Base model is already bf16, so only LoRA params change.
    """
    n = 0
    for p in peft_model.parameters():
        if p.dtype == torch.float32:
            p.data = p.data.to(torch.bfloat16)
            n += 1
    if n:
        torch.cuda.empty_cache()
    logger.info(f"  Cast {n} fp32 params to bf16. VRAM: {torch.cuda.memory_allocated()/1e9:.1f}GB")


def switch_adapter(agent_name: str):
    """Switch to a different LoRA adapter. Fast — only loads small LoRA weights.

    Raises ValueError for unknown agents; on load failure the previous
    adapter is restored and RuntimeError is raised, so the model is never
    left without an active adapter.
    """
    global peft_model, current_agent

    if agent_name == current_agent:
        return

    adapter_path = os.path.join(LORA_DIR, agent_name)
    if not os.path.isdir(adapter_path):
        raise ValueError(f"Unknown agent '{agent_name}': no adapter at {adapter_path}")

    prev = current_agent

    # Delete old adapter to free VRAM (24GB card can't hold two large adapters)
    if prev and prev in peft_model.peft_config:
        try:
            peft_model.delete_adapter(prev)
            torch.cuda.empty_cache()
        except Exception as e:
            logger.warning(f"  delete_adapter {prev}: {e}")

    try:
        # Load new adapter from disk (~1-2s for LoRA weights only)
        peft_model.load_adapter(adapter_path, adapter_name=agent_name)
        peft_model.set_adapter(agent_name)
        cast_adapter_to_bf16()
    except Exception as e:
        logger.error(f"  load_adapter {agent_name} failed: {e} — restoring {prev}")
        try:
            if prev:
                if prev not in peft_model.peft_config:
                    peft_model.load_adapter(os.path.join(LORA_DIR, prev), adapter_name=prev)
                peft_model.set_adapter(prev)
                cast_adapter_to_bf16()
        except Exception as e2:
            logger.error(f"  restore {prev} failed: {e2}")
        raise RuntimeError(f"switch to '{agent_name}' failed: {e}")

    current_agent = agent_name
    logger.info(f"  Switched to {agent_name}. VRAM: {torch.cuda.memory_allocated()/1e9:.1f}GB")


def _generate(req: ChatRequest) -> dict:
    """Tokenize + generate + response dict. Caller handles adapter state."""
    msgs = [{"role": m.role, "content": [{"type": "text", "text": m.content}]} for m in req.messages]
    text = processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], return_tensors="pt").to(peft_model.device)

    gen_kwargs = {"max_new_tokens": req.max_tokens}
    if req.temperature > 0:
        gen_kwargs.update(do_sample=True, temperature=req.temperature)
    else:
        gen_kwargs.update(do_sample=False)

    # Reproducibility (user requirement): deterministic seed PER
    # PROMPT — base seed + crc32(prompt). Identical prompts still reproduce
    # byte-identical outputs, but different prompts (e.g. CDA batches 1-4
    # sharing a long common prefix) get decorrelated sampling trajectories.
    # (First version used a single fixed seed for every request, which made
    # batches converge to near-duplicate candidate lists.) Override base with
    # CU_AGENT_SEED; CU_AGENT_SEED="" disables seeding.
    seed_env = os.environ.get("CU_AGENT_SEED", "42")
    if seed_env:
        import zlib
        seed = (int(seed_env) + zlib.crc32(text.encode("utf-8"))) % (2**31)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    with torch.no_grad():
        output_ids = peft_model.generate(**inputs, **gen_kwargs)

    response = processor.decode(output_ids[0][len(inputs.input_ids[0]):], skip_special_tokens=True)

    # Persist every completion server-side: long generations (30-90 min at
    # 10k+ context) must survive client HTTP timeouts — results land on disk
    # regardless of whether the client is still listening.
    try:
        resp_dir = os.path.join("E:/Cu-agent/outputs", "server_responses")
        os.makedirs(resp_dir, exist_ok=True)
        with open(os.path.join(resp_dir, f"{req.agent}_{int(time.time())}.txt"), "w", encoding="utf-8") as f:
            f.write(response)
    except Exception as e:
        logger.warning(f"persist response: {e}")

    return {
        "id": f"chatcmpl-{int(time.time())}", "object": "chat.completion",
        "created": int(time.time()), "model": "nano-bio",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": response}, "finish_reason": "stop"}],
        "agent_used": req.agent
    }


def generate_response(req: ChatRequest) -> dict:
    """Blocking switch + generation. Runs in a worker thread (see endpoint)."""
    if req.agent == "base":
        # Raw base model: no adapter switching, all LoRA weights disabled
        with peft_model.disable_adapter():
            return _generate(req)
    switch_adapter(req.agent)
    return _generate(req)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global peft_model, processor, current_agent
    from transformers import Qwen3VLForConditionalGeneration, AutoProcessor

    logger.info(f"Loading base model... VRAM: {torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB")

    base = Qwen3VLForConditionalGeneration.from_pretrained(
        MODEL_PATH, device_map="auto", torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    processor = AutoProcessor.from_pretrained(MODEL_PATH)
    processor.tokenizer.pad_token = processor.tokenizer.eos_token

    # Create PEFT wrapper with first adapter
    adapters = sorted([d for d in os.listdir(LORA_DIR) if os.path.isdir(os.path.join(LORA_DIR, d))])
    first_adapter = adapters[0] if adapters else "extractor"
    first_path = os.path.join(LORA_DIR, first_adapter)
    peft_model = PeftModel.from_pretrained(base, first_path, adapter_name=first_adapter)
    current_agent = first_adapter  # Track it — otherwise it stays resident forever
    cast_adapter_to_bf16()  # LoRA saved fp32; halve adapter VRAM for inference
    logger.info(f"  Initial adapter: {first_adapter}. VRAM: {torch.cuda.memory_allocated()/1e9:.1f}GB")
    logger.info(f"Ready. Available adapters: {adapters}")
    yield


app = FastAPI(title="Nano-Bio Evaluator", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Only one adapter can be active at a time — serialize all inference requests.
request_lock = asyncio.Lock()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "vram_gb": torch.cuda.memory_allocated()/1e9 if torch.cuda.is_available() else 0,
        "current_agent": current_agent,
        "adapters_loaded": list(peft_model.peft_config.keys()) if peft_model else []
    }

@app.get("/agents")
async def list_agents():
    return {"agents": AGENTS}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    agent = req.agent or "extractor"
    if agent != "base" and not os.path.isdir(os.path.join(LORA_DIR, agent)):
        return JSONResponse(status_code=400, content={"error": f"Unknown agent: '{agent}'"})
    req.agent = agent

    # Lock is held for the whole switch+generate; the blocking work runs in a
    # worker thread so the event loop (and /health) stays responsive even
    # during 15-minute generations.
    async with request_lock:
        try:
            return await asyncio.to_thread(generate_response, req)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        except RuntimeError as e:
            return JSONResponse(status_code=503, content={"error": str(e)})
        except Exception as e:
            logger.exception("generation failed")
            return JSONResponse(status_code=500, content={"error": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("NANO_BIO_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
