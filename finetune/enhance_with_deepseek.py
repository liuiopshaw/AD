#!/usr/bin/env python3
"""
Enhance training data using DeepSeek R1 V4 Pro as teacher model.
For each training pair (instruction + input), queries DeepSeek R1 to generate
a high-quality reasoning response, producing knowledge-distilled training data.
"""

import json, os, time, logging
from pathlib import Path
from dotenv import load_dotenv
import httpx

load_dotenv(Path(__file__).parent.parent / ".env")

API_KEY = os.getenv("DEEPSEEK_API_KEY")
API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com")
MODEL = "deepseek-v4-pro"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deepseek-enhance")

PROJECT_ROOT = os.environ.get("CU_AGENT_ROOT", "E:/Cu-agent")
DATA_DIR = Path(PROJECT_ROOT) / "data" / "training"
OUTPUT_DIR = Path(PROJECT_ROOT) / "data" / "training_enhanced"

RATE_LIMIT = 1.0  # seconds between requests
BATCH_SIZE = 5     # save every N responses


def call_deepseek_r1(instruction: str, input_text: str) -> str:
    """Query DeepSeek R1 Pro for a high-quality response."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = (
        "You are a senior scientist specializing in nanomaterials, gut microbiota, "
        "enzyme-like nanozyme activity, and Alzheimer's disease therapy via the gut-brain axis. "
        "Provide detailed, scientifically rigorous answers based on the instruction. "
        "Include specific data when available (MIC values, enzyme kinetics, mechanisms). "
        "Structure your response as JSON when requested. "
        "Be concise but thorough — each answer should be 200-500 words."
    )

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"### Instruction:\n{instruction}\n\n### Input:\n{input_text}"}
        ],
        "max_tokens": 2048,
        "temperature": 0.1,  # Low temp for factual accuracy
    }

    try:
        response = httpx.post(
            f"{API_BASE}/v1/chat/completions",
            json=payload, headers=headers, timeout=120
        )
        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        else:
            logger.error(f"API error {response.status_code}: {response.text[:200]}")
            return ""
    except Exception as e:
        logger.error(f"Request failed: {e}")
        return ""


def enhance_agent(agent_name: str):
    """Enhance all training pairs for a single agent."""
    input_path = DATA_DIR / f"{agent_name}_training_data.jsonl"
    output_path = OUTPUT_DIR / f"{agent_name}_training_data.jsonl"

    if not input_path.exists():
        logger.warning(f"No training data for {agent_name}")
        return

    # Load existing pairs
    pairs = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            pairs.append(json.loads(line))

    logger.info(f"\n{'='*60}")
    logger.info(f"Enhancing {agent_name.upper()}: {len(pairs)} pairs")
    logger.info(f"{'='*60}")

    enhanced = []
    existing_outputs = 0

    for i, pair in enumerate(pairs):
        # Skip if already has a good output
        if pair.get("output") and len(pair["output"]) > 100:
            enhanced.append(pair)
            existing_outputs += 1
            continue

        logger.info(f"  [{i+1}/{len(pairs)}] Querying DeepSeek R1...")

        instruction = pair["instruction"]
        input_text = pair["input"][:4000]  # Keep input manageable

        output = call_deepseek_r1(instruction, input_text)

        if output:
            pair["output"] = output
            pair["enhanced_by"] = MODEL
            pair["enhanced_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            enhanced.append(pair)
            logger.info(f"    -> {len(output)} chars response")
        else:
            enhanced.append(pair)  # Keep original if API fails
            logger.warning(f"    -> FAILED, keeping original")

        # Save periodically
        if (i + 1) % BATCH_SIZE == 0:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                for p in enhanced:
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
            logger.info(f"    Saved {len(enhanced)}/{len(pairs)}")

        time.sleep(RATE_LIMIT)

    # Final save
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for p in enhanced:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    new_outputs = len(enhanced) - existing_outputs
    logger.info(f"  {agent_name}: {new_outputs} new responses, {existing_outputs} existing")
    logger.info(f"  -> {output_path}")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import sys
    agents = ["ea", "apa", "epa", "bsa", "mma", "toa", "ca"]

    if len(sys.argv) > 1:
        agent = sys.argv[1]
        if agent in agents:
            enhance_agent(agent)
        elif agent == "all":
            for a in agents:
                enhance_agent(a)
        else:
            print(f"Unknown: {agent}. Options: {agents} + all")
    else:
        print(f"Usage: python enhance_with_deepseek.py [agent|all]")
        print(f"Agents: {agents}")
