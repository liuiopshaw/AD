#!/usr/bin/env python3
"""
Unified per-agent LLM routing layer.

Every agent call in the scripts/ pipeline goes through chat() here. By default
everything routes to the local llava_server.py on localhost:8000 (unchanged
behavior). Any agent can be rerouted to a cloud OpenAI-compatible API
(DashScope / OpenAI / DeepSeek / ...) by adding an entry to
scripts/llm_endpoints.json:

  {
    "default": {"base_url": "http://localhost:8000/v1/chat/completions",
                "model": "nano-bio", "api_key_env": null},
    "delivery": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "model": "qwen-plus", "api_key_env": "QWEN_API_KEY"}
  }

Semantics:
- An agent entry overrides "default" field-by-field; unknown agents fall back
  to "default".
- "api_key_env" names an environment variable holding the API key, sent as
  "Authorization: Bearer <key>". null = no auth header (local server).
- Local endpoints (localhost / 127.0.0.1) keep the extra "agent" field in the
  request body — llava_server uses it to switch LoRA adapters. Non-local
  endpoints receive a standard OpenAI request body WITHOUT "agent".

Agent raw outputs are returned verbatim (project iron rule: no cleaning).
Errors are returned as "ERROR ..." strings, never raised, matching the
existing scripts' conventions.
"""

import json
import os
import time
from pathlib import Path

import httpx

CONFIG_PATH = Path(__file__).resolve().parent / "llm_endpoints.json"

LOCAL_CHAT_URL = "http://localhost:8000/v1/chat/completions"

# Built-in fallback when llm_endpoints.json is absent: everything local.
_BUILTIN_CONFIG = {
    "default": {"base_url": LOCAL_CHAT_URL, "model": "nano-bio", "api_key_env": None}
}


def load_endpoints(path=None) -> dict:
    """Load the per-agent endpoint config.

    Missing file -> built-in local default. Each agent entry is merged over
    "default" field-by-field. Returns a dict with at least "default".
    """
    p = Path(path) if path else CONFIG_PATH
    cfg = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    default = dict(_BUILTIN_CONFIG["default"])
    default.update(cfg.get("default") or {})
    endpoints = {"default": default}
    for name, ep in cfg.items():
        if name == "default" or not isinstance(ep, dict):
            continue
        merged = dict(default)
        merged.update(ep)
        endpoints[name] = merged
    return endpoints


def resolve_endpoint(agent: str, endpoints: dict = None) -> dict:
    """Endpoint dict for an agent (per-agent override or the default)."""
    eps = endpoints if endpoints is not None else load_endpoints()
    return eps.get(agent, eps["default"])


def is_local_endpoint(ep: dict) -> bool:
    """True when the endpoint is the local llava_server (localhost/127.0.0.1)."""
    url = ep.get("base_url", "")
    return "localhost" in url or "127.0.0.1" in url


def chat(agent: str, prompt: str, max_tokens: int = 6144, temperature: float = 0.1,
         timeout: int = 1800, retries: int = 3, retry_on_timeout: bool = True,
         endpoints: dict = None) -> str:
    """Send one user-prompt chat completion for an agent, return the raw text.

    Retry policy (mirrors the existing scripts): 502/503 wait 10s and retry;
    connection errors wait 5s and retry; ReadTimeout retries too unless
    retry_on_timeout=False (task_100_materials relies on that: the local
    server is likely still generating, so a retry would queue a duplicate).
    Non-retryable HTTP statuses return an "ERROR <status>: ..." string.
    A configured-but-missing API key returns a clear ERROR string immediately.
    """
    ep = resolve_endpoint(agent, endpoints)
    local = is_local_endpoint(ep)

    headers = {}
    key_env = ep.get("api_key_env")
    if key_env:
        key = os.getenv(key_env)
        if not key:
            return (f"ERROR: endpoint for agent '{agent}' requires API key env "
                    f"var '{key_env}', but it is not set")
        headers["Authorization"] = f"Bearer {key}"

    body = {
        "model": ep.get("model", "nano-bio"),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if local:
        body["agent"] = agent  # llava_server switches LoRA adapters on this

    for attempt in range(retries):
        try:
            r = httpx.post(ep["base_url"], json=body, headers=headers or None,
                           timeout=timeout)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code in (502, 503):
                print(f"  {agent} got {r.status_code}, retrying in 10s ({attempt+1}/{retries})")
                time.sleep(10)
            else:
                return f"ERROR {r.status_code}: {r.text[:300]}"
        except httpx.ReadTimeout:
            if not retry_on_timeout:
                return f"ERROR: generation exceeded timeout ({timeout}s)"
            print(f"  {agent} ReadTimeout, retrying ({attempt+1}/{retries})")
            time.sleep(5)
        except httpx.TransportError as e:
            # ConnectError / ConnectTimeout / network resets etc.
            print(f"  {agent} {type(e).__name__}: {e}, retrying ({attempt+1}/{retries})")
            time.sleep(5)
    return f"ERROR: failed after {retries} retries"
