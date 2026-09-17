# AD Multi-Agent Evaluator (ECOMATS / Nano-Bio)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](#)
[![CrewAI](https://img.shields.io/badge/CrewAI-1.7.0-green)](#)

A multi-agent system for Alzheimer's disease (AD) therapeutic candidate design and evaluation, built on CrewAI with a locally served Qwen3-VL-8B base model and per-agent LoRA adapters. The project ships two pipelines and a blind benchmark evaluation suite.

## Features

- 🤖 **Specialized agents** — task orchestration (coordinator), creative design (designer), manufacturability scoring (manufacturing), delivery-efficiency scoring (delivery), biosafety (safety), mechanism mining (mechanism), comparison/ranking (ranker), knowledge extraction (extractor)
- 🔬 **Per-agent LoRA adapters** — one base model loaded once; adapters switched per request by `scripts/llava_server.py` (FastAPI, OpenAI-compatible)
- ☁️ **Per-agent cloud LLM routing** — any agent can be rerouted to a cloud OpenAI-compatible API (DashScope / OpenAI / DeepSeek ...) via `scripts/llm_endpoints.json`, no code changes
- 📊 **Blind benchmark suite** — ADTB-100 / AD-TxBench-100 (drug scoring) and ADRD-Bench (caregiving QA), with harness-vs-prompt and LoRA-vs-base 2×2 protocols, rubric anchoring, AD-relevance gating, anonymization, and deterministic scoring
- 🌐 **Bilingual prompts** — English and Chinese locale data under `src/locales/`

## Pipelines

### 1. CrewAI pipeline (water-treatment / material design heritage)

`scripts/main.py` (sync) or `scripts/main_async.py` (async). Uses DashScope Qwen by default; see `src/utils/llm_config.py`.

### 2. Nano-Bio pipeline (task-100 AD candidate design)

```bash
# 1. Start the LoRA multi-adapter server (loads Qwen3-VL-8B once)
python scripts/llava_server.py          # port 8000; CU_AGENT_SEED="" disables deterministic seeding

# 2. Run the full pipeline: TOA -> CDA x4 -> APA/EPA/BSA/MMA -> CA
python scripts/task_100_materials.py --config scripts/pipeline_config.json
#    --base            control run with the raw base model (all LoRA adapters disabled)
#    --config ...      e.g. pipeline_config_ad100_free.json (no drug-type quotas)

# 3. Deterministic ranking (no agent involved; raw outputs never modified)
python scripts/extract_subscores.py <TS>
python scripts/rank_ad100.py <TS> --rubric scripts/asa_rubric.nobonus.json
```

## Cloud LLM per agent

`scripts/llm_client.py` routes every agent call. Default: everything local. To put a single agent (or all) on a cloud API, edit `scripts/llm_endpoints.json`:

```json
{
  "default": {"base_url": "http://localhost:8000/v1/chat/completions", "model": "nano-bio", "api_key_env": null},
  "epa": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
          "model": "qwen-plus", "api_key_env": "QWEN_API_KEY"}
}
```

- An agent entry overrides `default` field-by-field; unknown agents fall back to `default`.
- `api_key_env` names the environment variable holding the API key (sent as a Bearer token); `null` = no auth.
- Local endpoints keep the extra `agent` field (llava_server switches adapters on it); cloud endpoints receive a standard OpenAI request body.

## Blind benchmark suite

```bash
python scripts/benchmark_adtb100.py --rubric --gate hard --benchmark benchmark/<file>.json
#   --use-base            raw base model arm
#   --mode prompt         single consolidated scoring prompt (no agent chain)
#   --gate off|hard|soft  AD-relevance gating formula
#   --name-only           agents see ONLY the drug name
#   --anonymize           agents see Candidate_NNN codes + class/mechanism (name prior removed)
python scripts/compare_adtb100.py <TS>    # per-tier stats, Spearman, concordance, confusion, P@k
python scripts/adtb100_aggregate.py       # mean +/- std across repeated runs
python scripts/benchmark_adrd.py          # ADRD-Bench caregiving QA (MCQ + True/False)
```

All agent outputs are saved RAW and unmodified under `outputs/run_<TS>/`; scoring and ranking are mechanical extraction only.

## Scoring rubric

`评分标准/标准.md` — five weighted dimensions (target-tissue delivery 30%, multi-target synergy 15%, effect duration 10%, manufacturing control 25%, biosafety 20%) plus an optional AD-relevance gate (hard: ×ad/10; soft: ×(0.5+0.5·ad/10)). Mirrored in `scripts/asa_rubric.json` / `asa_rubric.nobonus.json` for deterministic ranking.

## Project Structure

```
├── src/
│   ├── agents/          # agent implementations
│   ├── tasks/           # task definitions
│   ├── tools/           # database query tools (PubChem, Materials Project, ChEMBL, ...)
│   ├── locales/         # EN/ZH prompts and task texts
│   └── utils/           # LLM config, logging, context store, tool specs
├── scripts/
│   ├── llava_server.py      # LoRA multi-adapter server (port 8000)
│   ├── llm_client.py        # unified per-agent LLM routing
│   ├── llm_endpoints.json   # per-agent endpoint config (local/cloud)
│   ├── task_100_materials.py    # nano-bio task-100 pipeline
│   ├── benchmark_adtb100.py     # blind drug-scoring benchmark harness
│   ├── compare_adtb100.py / adtb100_aggregate.py / adtb100_retry.py
│   ├── rank_ad100.py / extract_subscores.py / asa_scoring.py
│   └── main.py / main_async.py / workflow/
├── benchmark/           # ADTB-100 / AD-TxBench-100 / ADRD-Bench data
├── finetune/            # LoRA training data builders and training scripts
└── .env.example
```

## Configuration

API keys live in `.env` (see `.env.example`): `QWEN_API_KEY`, `MATERIALS_PROJECT_API_KEY`, optional `MOLPORT_API_KEY`, `DRUGBANK_API_KEY`, `NCBI_API_KEY`, `EAS_ENDPOINT`/`EAS_TOKEN`. Never commit `.env`.

## Requirements

- Python 3.11 or 3.12

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE). Derivative works must be open-sourced under the same license.
