#!/usr/bin/env python3
"""
ADTB-100 blind benchmark evaluation.

Feeds the 100 compounds from benchmark/ADTB-100_v1.0_Alzheimer_Therapeutics_Benchmark.json
to the Nano-Bio agent ensemble WITHOUT revealing Category / Label / any preset score
(blind protocol). Each batch is scored by domain agents:

  EPA -> Efficacy (1-10)
  MMA -> Mechanism_score (1-10)
  BSA -> Safety_score (1-10) + BBB_score (1-10, CNS delivery)
  CA  -> Clinical_score (1-10) + Overall_score (1-10), given the subscores above

Raw agent outputs are saved unmodified (project iron rule); parsed scores go to
adtb100_scores_<TS>.json in the same run dir. Compare against ground truth with
scripts/compare_adtb100.py.

Requires llava_server.py running on localhost:8000.

Usage: python scripts/benchmark_adtb100.py [--batch-size 20] [--only epa,mma,bsa,ca]
"""

import argparse
import json
import os
import re
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from output_utils import run_dir

SERVER = "http://localhost:8000/v1/chat/completions"
BENCHMARK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "benchmark", "ADTB-100_v1.0_Alzheimer_Therapeutics_Benchmark.json")


def load_records(path):
    """Load a benchmark JSON and normalize records to
    {ID, Compound, Class, Mechanism}. Supports v1 (ADTB-100) and v3
    (AD-TxBench-100) schemas. v3 anonymized placeholders (Candidate_NN with
    'To be curated' fields) carry zero information for blind scoring and are
    skipped — reported in the payload."""
    with open(path, encoding="utf-8") as f:
        bench = json.load(f)
    recs = bench["records"]
    is_v3 = "Therapeutic" in recs[0]
    norm, skipped = [], 0
    for r in recs:
        if is_v3:
            name, cls, mech = r["Therapeutic"], r["Therapeutic_class"], r["Mechanism"]
            if name.startswith("Candidate_") or cls == "To be curated" or mech == "To be curated":
                skipped += 1
                continue
            norm.append({"ID": r["ID"], "Compound": name, "Class": cls, "Mechanism": mech})
        else:
            norm.append({"ID": r["ID"], "Compound": r["Compound"], "Class": r["Class"],
                         "Mechanism": r["Mechanism"]})
    bench["_norm_records"] = norm
    bench["_skipped"] = skipped
    bench["_schema"] = "v3" if is_v3 else "v1"
    return bench

TS = int(time.time())
RUN_DIR = run_dir(TS)

AGENT_OVERRIDE = None  # "base" = raw Qwen3-VL-8B without any LoRA adapter


def call_agent(agent: str, prompt: str, max_tokens: int = 6144, temperature: float = 0.1,
               retries: int = 3, timeout: int = 1800) -> str:
    agent = AGENT_OVERRIDE or agent
    for attempt in range(retries):
        try:
            r = httpx.post(SERVER, json={
                "model": "nano-bio", "agent": agent,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens, "temperature": temperature,
            }, timeout=timeout)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code in (502, 503):
                print(f"  {agent} got {r.status_code}, retrying in 10s ({attempt+1}/{retries})")
                time.sleep(10)
            else:
                return f"ERROR {r.status_code}: {r.text[:300]}"
        except (httpx.ReadTimeout, httpx.ConnectError) as e:
            print(f"  {agent} {type(e).__name__}, retrying ({attempt+1}/{retries})")
            time.sleep(5)
    return f"ERROR: failed after {retries} retries"


def save_raw(filename: str, content: str):
    path = RUN_DIR / filename
    path.write_text(content, encoding="utf-8")
    print(f"  -> {path}")


# ---------------------------------------------------------------------------
# Prompts — blind: only Compound / Class / Mechanism are disclosed
# (--name-only reduces disclosure to Compound alone).
# Strict machine-parseable output: "N. name | dim: X | reasoning"
# ---------------------------------------------------------------------------

NAME_ONLY = False


def drug_lines(batch):
    if NAME_ONLY:
        return "\n".join(f"{j+1}. {d['Compound']}" for j, d in enumerate(batch))
    return "\n".join(
        f"{j+1}. {d['Compound']} (Class: {d['Class']}; Mechanism: {d['Mechanism']})"
        for j, d in enumerate(batch))


def drug_label(d):
    """Single-item label respecting the disclosure level."""
    if NAME_ONLY:
        return d["Compound"]
    return f"{d['Compound']} (Class: {d['Class']}; Mechanism: {d['Mechanism']})"


def epa_prompt(batch):
    return f"""Evaluate the following Alzheimer's disease (AD) therapeutic candidates for THERAPEUTIC EFFICACY.

For EACH candidate, give an Efficacy score from 1 to 10 (1 = no meaningful AD efficacy, 10 = proven strong efficacy in AD patients), based on known clinical/preclinical evidence for THIS compound in AD. Give a one-line reasoning.

Candidates:
{drug_lines(batch)}

Output format (ONE LINE per candidate, numbered, no other text):
1. <name> | efficacy: <1-10> | <one-line reasoning>
2. ..."""


def mma_prompt(batch):
    return f"""Evaluate the following Alzheimer's disease (AD) therapeutic candidates for MECHANISM quality.

For EACH candidate, give a Mechanism score from 1 to 10 (1 = no plausible AD-relevant mechanism, 10 = well-validated AD disease-modifying mechanism), based on whether the stated mechanism genuinely addresses AD pathology. Give a one-line reasoning.

Candidates:
{drug_lines(batch)}

Output format (ONE LINE per candidate, numbered, no other text):
1. <name> | mechanism: <1-10> | <one-line reasoning>
2. ..."""


def bsa_prompt(batch):
    return f"""Evaluate the following Alzheimer's disease (AD) therapeutic candidates for SAFETY and BLOOD-BRAIN-BARRIER (BBB) suitability.

For EACH candidate give TWO scores from 1 to 10:
- safety: 1 = severe safety concerns, 10 = excellent established safety profile
- bbb: 1 = cannot reach CNS targets, 10 = excellent CNS exposure for its modality (for biologics that act peripherally or are delivered intrathecally, judge effective CNS target engagement, not passive diffusion)
Give a one-line reasoning covering both.

Candidates:
{drug_lines(batch)}

Output format (ONE LINE per candidate, numbered, no other text):
1. <name> | safety: <1-10> | bbb: <1-10> | <one-line reasoning>
2. ..."""


def ca_prompt(batch, subscores):
    # subscores: list of dicts with parsed dimension scores (may contain None)
    lines = []
    for j, d in enumerate(batch):
        s = subscores[j]
        def fmt(v):
            return str(v) if v is not None else "NA"
        lines.append(
            f"{j+1}. {drug_label(d)} "
            f"| efficacy: {fmt(s.get('efficacy'))} | mechanism: {fmt(s.get('mechanism'))} "
            f"| safety: {fmt(s.get('safety'))} | bbb: {fmt(s.get('bbb'))}")
    return f"""You are the Comparison & Ranking agent. Below are AD therapeutic candidates with subscores from domain expert agents (efficacy, mechanism, safety, bbb; each 1-10, NA = missing).

For EACH candidate give TWO scores from 1 to 10:
- clinical: clinical maturity/promise for AD (1 = no clinical rationale, 10 = approved/late-stage AD therapy)
- overall: your fused overall judgment as an AD therapeutic candidate, weighing efficacy and clinical evidence most, then mechanism, safety, and BBB/CNS suitability. Missing (NA) subscores mean you must judge that aspect yourself.
Give a one-line reasoning.

Candidates with expert subscores:
{chr(10).join(lines)}

Output format (ONE LINE per candidate, numbered, no other text):
1. <name> | clinical: <1-10> | overall: <1-10> | <one-line reasoning>
2. ..."""


def solo_prompt(batch):
    """Condition 3/4: single consolidated scoring prompt — the dimension
    definitions copied verbatim from the harness agent prompts (epa/mma/bsa/ca),
    but NO multi-agent chain: one call scores all six dimensions directly."""
    return f"""Evaluate the following Alzheimer's disease (AD) therapeutic candidates. For EACH candidate give SIX scores from 1 to 10:

- efficacy: 1 = no meaningful AD efficacy, 10 = proven strong efficacy in AD patients, based on known clinical/preclinical evidence for THIS compound in AD.
- mechanism: 1 = no plausible AD-relevant mechanism, 10 = well-validated AD disease-modifying mechanism, based on whether the stated mechanism genuinely addresses AD pathology.
- safety: 1 = severe safety concerns, 10 = excellent established safety profile.
- bbb: 1 = cannot reach CNS targets, 10 = excellent CNS exposure for its modality (for biologics that act peripherally or are delivered intrathecally, judge effective CNS target engagement, not passive diffusion).
- clinical: clinical maturity/promise for AD (1 = no clinical rationale, 10 = approved/late-stage AD therapy).
- overall: your fused overall judgment as an AD therapeutic candidate, weighing efficacy and clinical evidence most, then mechanism, safety, and BBB/CNS suitability.

Give a one-line reasoning per candidate.

Candidates:
{drug_lines(batch)}

Output format (ONE LINE per candidate, numbered, no other text):
1. <name> | efficacy: <1-10> | mechanism: <1-10> | safety: <1-10> | bbb: <1-10> | clinical: <1-10> | overall: <1-10> | <one-line reasoning>
2. ..."""


# ---------------------------------------------------------------------------
# Rubric mode — anchors from 评分标准/标准.md (5-dim weighted framework)
# injected VERBATIM. Deterministic overall = weighted sum (rubric weights),
# mechanical, never modifies agent output.
# ---------------------------------------------------------------------------

RUBRIC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                           "评分标准", "标准.md")

RUBRIC_DIMS = ["delivery", "synergy", "duration", "manufacturability", "safety"]
RUBRIC_WEIGHTS = {"delivery": 0.30, "synergy": 0.15, "duration": 0.10,
                  "manufacturability": 0.25, "safety": 0.20}

RUBRIC_DIM_PATTERNS = {
    "ad_relevance": r"ad_relevance",
    "delivery": r"delivery",
    "synergy": r"synergy",
    "duration": r"duration",
    "manufacturability": r"manufacturability",
    "safety": r"safety",
    "overall": r"overall",
}


def load_rubric():
    with open(RUBRIC_PATH, encoding="utf-8") as f:
        return f.read()


def r_bsa_prompt(batch, rubric):
    return f"""你是 AD 治疗剂评估专家。严格按以下评分标准（逐字引用，必须遵守其锚点）：

{rubric}

请评估以下候选治疗剂的两个维度（各 1-10 分）：
- delivery: 维度一「靶组织递送效率」
- safety: 维度五「生物安全性」

候选（每行一个）：
{drug_lines(batch)}

输出格式（每行一个，编号，不要其他文字）：
1. <name> | delivery: <1-10> | safety: <1-10> | <一句理由>
2. ..."""


def r_mma_prompt(batch, rubric):
    return f"""你是 AD 治疗机制分析专家。严格按以下评分标准（逐字引用，必须遵守其锚点）：

{rubric}

请评估以下候选治疗剂的两个维度（各 1-10 分）：
- synergy: 维度二「多靶点协同潜力」
- duration: 维度三「效应持续时间」

候选（每行一个）：
{drug_lines(batch)}

输出格式（每行一个，编号，不要其他文字）：
1. <name> | synergy: <1-10> | duration: <1-10> | <一句理由>
2. ..."""


GATE = "off"  # off = additive (锚定加性版), hard = ×(ad/10), soft = ×(0.5+0.5·ad/10)

GATE_FORMULA = {
    "off": "五维加权（递送30%、多靶点15%、持续时间10%、生产质控25%、安全性20%）",
    "hard": "五维加权（递送30%、多靶点15%、持续时间10%、生产质控25%、安全性20%）再乘以门控（AD相关性÷10）",
    "soft": "五维加权（递送30%、多靶点15%、持续时间10%、生产质控25%、安全性20%）再乘以软门控（0.5 + 0.5×AD相关性÷10）",
}


def r_epa_prompt(batch, rubric):
    if GATE == "off":
        dims_txt = "请评估以下候选治疗剂的一个维度（1-10 分）：\n- manufacturability: 维度四「生产质控与精准调控能力」"
        fmt = "1. <name> | manufacturability: <1-10> | <一句理由>"
    else:
        dims_txt = ("请评估以下候选治疗剂的两个维度（各 1-10 分）：\n"
                    "- ad_relevance: 维度零「AD 相关性」（门控维度）\n"
                    "- manufacturability: 维度四「生产质控与精准调控能力」")
        fmt = "1. <name> | ad_relevance: <1-10> | manufacturability: <1-10> | <一句理由>"
    return f"""你是 AD 治疗剂评估专家。严格按以下评分标准（逐字引用，必须遵守其锚点）：

{rubric}

{dims_txt}

候选（每行一个）：
{drug_lines(batch)}

输出格式（每行一个，编号，不要其他文字）：
{fmt}
2. ..."""


def r_ca_prompt(batch, subscores, rubric):
    lines = []
    for j, d in enumerate(batch):
        s = subscores[j]
        def fmt(v):
            return str(v) if v is not None else "NA"
        line = (f"{j+1}. {drug_label(d)} "
                f"| delivery: {fmt(s.get('delivery'))} "
                f"| synergy: {fmt(s.get('synergy'))} | duration: {fmt(s.get('duration'))} "
                f"| manufacturability: {fmt(s.get('manufacturability'))} "
                f"| safety: {fmt(s.get('safety'))}")
        if GATE != "off":
            line += f" | ad_relevance: {fmt(s.get('ad_relevance'))}"
        lines.append(line)
    return f"""你是 Comparison & Ranking agent。评分标准（逐字引用，必须遵守其锚点与权重）：

{rubric}

以下是 AD 候选治疗剂及三个领域专家给出的子分（1-10，NA=缺失，缺失维度由你自行判断）：

{chr(10).join(lines)}

对每个候选给出 overall 综合分（1-10），须与标准中的综合分公式一致：{GATE_FORMULA[GATE]}。一句理由。

输出格式（每行一个，编号，不要其他文字）：
1. <name> | overall: <1-10> | <一句理由>
2. ..."""


def r_solo_prompt(batch, rubric):
    if GATE == "off":
        dims_txt = """对每个候选治疗剂给出 SIX 个分数（各 1-10）：
- delivery: 维度一「靶组织递送效率」
- synergy: 维度二「多靶点协同潜力」
- duration: 维度三「效应持续时间」
- manufacturability: 维度四「生产质控与精准调控能力」
- safety: 维度五「生物安全性」"""
        fmt = "1. <name> | delivery: <1-10> | synergy: <1-10> | duration: <1-10> | manufacturability: <1-10> | safety: <1-10> | overall: <1-10> | <一句理由>"
    else:
        dims_txt = """对每个候选治疗剂给出 SEVEN 个分数（各 1-10）：
- ad_relevance: 维度零「AD 相关性」（门控维度）
- delivery: 维度一「靶组织递送效率」
- synergy: 维度二「多靶点协同潜力」
- duration: 维度三「效应持续时间」
- manufacturability: 维度四「生产质控与精准调控能力」
- safety: 维度五「生物安全性」"""
        fmt = "1. <name> | ad_relevance: <1-10> | delivery: <1-10> | synergy: <1-10> | duration: <1-10> | manufacturability: <1-10> | safety: <1-10> | overall: <1-10> | <一句理由>"
    return f"""你是 AD 治疗剂评估专家。严格按以下评分标准（逐字引用，必须遵守其锚点）：

{rubric}

{dims_txt}
- overall: 综合分，与标准中的综合分公式一致：{GATE_FORMULA[GATE]}

候选（每行一个）：
{drug_lines(batch)}

输出格式（每行一个，编号，不要其他文字）：
{fmt}
2. ..."""


def rubric_overall(scores):
    """Deterministic fusion per the rubric; GATE selects the formula.
    off: weighted sum. hard: × (ad/10). soft: × (0.5 + 0.5·ad/10).
    None if any required dim missing."""
    vals = [scores.get(d) for d in RUBRIC_DIMS]
    if any(v is None for v in vals):
        return None
    weighted = sum(RUBRIC_WEIGHTS[d] * v for d, v in zip(RUBRIC_DIMS, vals))
    if GATE == "off":
        return round(weighted, 2)
    gate = scores.get("ad_relevance")
    if gate is None:
        return None
    if GATE == "hard":
        return round(weighted * (gate / 10.0), 2)
    return round(weighted * (0.5 + 0.5 * gate / 10.0), 2)


# ---------------------------------------------------------------------------
# Parsing — never modifies the raw text; extraction only.
# ---------------------------------------------------------------------------

DIM_PATTERNS = {
    "efficacy": r"efficacy",
    "mechanism": r"mechanism",
    "safety": r"safety",
    "bbb": r"bbb",
    "clinical": r"clinical",
    "overall": r"overall",
}


def parse_scores(raw: str, n_items: int, dims):
    """Extract per-item scores for the given dims from numbered raw lines.
    Returns list of dicts {dim: int|None}; unparsed items get all None."""
    results = [{d: None for d in dims} for _ in range(n_items)]
    for line in raw.split("\n"):
        m = re.match(r"\s*(\d+)[.)]\s*(.*)", line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if not (0 <= idx < n_items):
            continue
        body = m.group(2)
        for dim, pat in dims.items():
            sm = re.search(pat + r"\s*(?:score)?\s*[:=]?\s*(\d+(?:\.\d+)?)(?:\s*/\s*10)?",
                         body, re.IGNORECASE)
            if sm:
                v = float(sm.group(1))
                if 0 < v <= 10:
                    results[idx][dim] = v
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=20)
    ap.add_argument("--use-base", action="store_true",
                    help="route all calls to the raw base model (no LoRA adapters)")
    ap.add_argument("--mode", choices=["harness", "prompt"], default="harness",
                    help="harness = 4-agent chain (epa/mma/bsa/ca); "
                         "prompt = single consolidated scoring prompt, no chain")
    ap.add_argument("--rubric", action="store_true",
                    help="anchor with 评分标准/标准.md (5-dim weighted framework); "
                         "overall = deterministic weighted sum, CA overall kept as ca_overall")
    ap.add_argument("--gate", choices=["off", "hard", "soft"], default="off",
                    help="AD-relevance gate: off = additive (default), "
                         "hard = ×(ad/10), soft = ×(0.5+0.5·ad/10)")
    ap.add_argument("--benchmark", default=BENCHMARK,
                    help="benchmark JSON path (v1 ADTB-100 or v3 AD-TxBench-100 schema)")
    ap.add_argument("--name-only", action="store_true",
                    help="further reduce disclosure: agents see ONLY the drug name")
    ap.add_argument("--anonymize", action="store_true",
                    help="replace drug names with Candidate_NNN codes; agents see "
                         "code + Class + Mechanism (tests scoring from facts, not name recall)")
    args = ap.parse_args()

    global AGENT_OVERRIDE, GATE, NAME_ONLY
    if args.use_base:
        AGENT_OVERRIDE = "base"
    GATE = args.gate
    NAME_ONLY = args.name_only

    rubric_text = load_rubric() if args.rubric else None
    if args.anonymize and rubric_text:
        # The rubric's anchor examples name real drugs (e.g. Donepezil in the
        # 维度零 section) — scrub any line mentioning a benchmark compound, or
        # anonymization is defeated.
        import re as _re
        names = [r["Compound"] for r in load_records(args.benchmark)["_norm_records"]]
        pats = [_re.compile(r"\b" + _re.escape(n) + r"\b", _re.IGNORECASE)
                for n in names if len(n) >= 6]
        before = len(rubric_text.splitlines())
        rubric_text = "\n".join(
            ln for ln in rubric_text.splitlines()
            if not any(p.search(ln) for p in pats))
        print(f"Anonymize: scrubbed {before - len(rubric_text.splitlines())} "
              f"rubric lines mentioning benchmark compounds")

    bench = load_records(args.benchmark)
    records = bench["_norm_records"]
    if bench["_skipped"]:
        print(f"NOTE: skipped {bench['_skipped']} anonymized/placeholder records "
              f"(no evaluable information for blind scoring)")
    print(f"Benchmark schema: {bench['_schema']}, evaluable records: {len(records)}")
    # Blind protocol: agents see ONLY these fields. --anonymize replaces the
    # name with a code (mapping stored in the payload for post-hoc decode only).
    blind_inputs = []
    anon_map = {}
    for k, r in enumerate(records):
        name = r["Compound"]
        if args.anonymize:
            code = f"Candidate_{k+1:03d}"
            anon_map[code] = name
            name = code
        blind_inputs.append({"Compound": name, "Class": r["Class"], "Mechanism": r["Mechanism"]})
    print(f"ADTB-100 blind eval: {len(blind_inputs)} compounds, batch size {args.batch_size}")
    print(f"Run dir: {RUN_DIR}")

    # all parsed scores aligned with records
    if args.rubric:
        score_keys = ["delivery", "synergy", "duration", "manufacturability",
                      "safety", "ca_overall", "overall"]
        if GATE != "off":
            score_keys.insert(0, "ad_relevance")
    else:
        score_keys = ["efficacy", "mechanism", "safety", "bbb", "clinical", "overall"]
    all_scores = [{k: None for k in score_keys} for _ in records]

    t0 = time.time()
    for i in range(0, len(blind_inputs), args.batch_size):
        batch = blind_inputs[i:i + args.batch_size]
        bnum = i // args.batch_size + 1
        n = len(batch)
        print(f"\n=== Batch {bnum}: {n} compounds ===")

        batch_sub = []
        if args.mode == "prompt" and args.rubric:
            # Rubric-anchored single prompt, no agent chain.
            raw = call_agent("ca", r_solo_prompt(batch, rubric_text), max_tokens=8192)
            save_raw(f"adtb100_rsolo_batch{bnum}_raw_{TS}.txt", raw)
            parsed = parse_scores(raw, n, RUBRIC_DIM_PATTERNS)
            for k in range(n):
                ca_ov = parsed[k].pop("overall", None)  # model's own overall
                all_scores[i + k].update(parsed[k])
                all_scores[i + k]["ca_overall"] = ca_ov
                all_scores[i + k]["overall"] = rubric_overall(parsed[k])
            missing = sum(1 for k in range(n) if all_scores[i + k]["overall"] is None)
            if missing:
                print(f"  WARNING: rubric-solo batch {bnum}: {missing}/{n} items incomplete")
            time.sleep(2)
            continue

        if args.mode == "prompt":
            # Single consolidated prompt, no agent chain. LoRA arm uses the ca
            # adapter (fusion/ranking role); --use-base routes to raw model.
            raw = call_agent("ca", solo_prompt(batch), max_tokens=8192)
            save_raw(f"adtb100_solo_batch{bnum}_raw_{TS}.txt", raw)
            parsed = parse_scores(raw, n, DIM_PATTERNS)
            missing = sum(1 for s in parsed if all(v is None for v in s.values()))
            if missing:
                print(f"  WARNING: solo batch {bnum}: {missing}/{n} items unparsed")
            for k in range(n):
                all_scores[i + k].update(parsed[k])
            time.sleep(2)
            continue

        if args.rubric:
            # Rubric-anchored harness: bsa(delivery+safety) / mma(synergy+duration)
            # / epa(manufacturability, +ad_relevance when gate on) -> ca(overall).
            epa_dims = {"manufacturability": RUBRIC_DIM_PATTERNS["manufacturability"]}
            if GATE != "off":
                epa_dims = {"ad_relevance": RUBRIC_DIM_PATTERNS["ad_relevance"], **epa_dims}
            for agent, pfunc, dims in [
                ("bsa", r_bsa_prompt, {"delivery": RUBRIC_DIM_PATTERNS["delivery"],
                                       "safety": RUBRIC_DIM_PATTERNS["safety"]}),
                ("mma", r_mma_prompt, {"synergy": RUBRIC_DIM_PATTERNS["synergy"],
                                       "duration": RUBRIC_DIM_PATTERNS["duration"]}),
                ("epa", r_epa_prompt, epa_dims),
            ]:
                raw = call_agent(agent, pfunc(batch, rubric_text))
                save_raw(f"adtb100_r_{agent}_batch{bnum}_raw_{TS}.txt", raw)
                parsed = parse_scores(raw, n, dims)
                if not batch_sub:
                    batch_sub = parsed
                else:
                    for k in range(n):
                        batch_sub[k].update(parsed[k])
                missing = sum(1 for s in parsed if all(v is None for v in s.values()))
                if missing:
                    print(f"  WARNING: {agent} batch {bnum}: {missing}/{n} items unparsed")
                time.sleep(2)

            raw = call_agent("ca", r_ca_prompt(batch, batch_sub, rubric_text))
            save_raw(f"adtb100_r_ca_batch{bnum}_raw_{TS}.txt", raw)
            ca_parsed = parse_scores(raw, n, {"overall": RUBRIC_DIM_PATTERNS["overall"]})
            for k in range(n):
                all_scores[i + k].update(batch_sub[k])
                all_scores[i + k]["ca_overall"] = ca_parsed[k]["overall"]
                all_scores[i + k]["overall"] = rubric_overall(batch_sub[k])
            time.sleep(2)
            continue

        for agent, pfunc, dims in [
            ("epa", epa_prompt, {"efficacy": DIM_PATTERNS["efficacy"]}),
            ("mma", mma_prompt, {"mechanism": DIM_PATTERNS["mechanism"]}),
            ("bsa", bsa_prompt, {"safety": DIM_PATTERNS["safety"], "bbb": DIM_PATTERNS["bbb"]}),
        ]:
            raw = call_agent(agent, pfunc(batch))
            save_raw(f"adtb100_{agent}_batch{bnum}_raw_{TS}.txt", raw)
            parsed = parse_scores(raw, n, dims)
            if not batch_sub:
                batch_sub = parsed
            else:
                for k in range(n):
                    batch_sub[k].update(parsed[k])
            missing = sum(1 for s in parsed if all(v is None for v in s.values()))
            if missing:
                print(f"  WARNING: {agent} batch {bnum}: {missing}/{n} items unparsed")
            time.sleep(2)

        raw = call_agent("ca", ca_prompt(batch, batch_sub))
        save_raw(f"adtb100_ca_batch{bnum}_raw_{TS}.txt", raw)
        ca_parsed = parse_scores(raw, n, {"clinical": DIM_PATTERNS["clinical"],
                                          "overall": DIM_PATTERNS["overall"]})
        for k in range(n):
            all_scores[i + k].update(batch_sub[k])
            all_scores[i + k].update(ca_parsed[k])
        time.sleep(2)

    variant = "base" if AGENT_OVERRIDE == "base" else "lora"
    out = {
        "benchmark": bench.get("dataset_name") or bench.get("dataset"),
        "benchmark_file": os.path.basename(args.benchmark),
        "schema": bench["_schema"],
        "skipped_placeholders": bench["_skipped"],
        "version": bench["version"],
        "protocol": ("blind, anonymized — agents saw Candidate_NNN codes + Class/Mechanism; "
                     "names and preset scores hidden" if args.anonymize else
                     "blind, name-only — agents saw ONLY the drug name; "
                     "class/mechanism/preset scores all hidden" if NAME_ONLY else
                     "blind — agents saw only Compound/Class/Mechanism; preset scores hidden"),
        "deanonymize": anon_map or None,
        "model_variant": "base (Qwen3-VL-8B, NO LoRA)" if variant == "base"
                         else "lora (per-agent adapters, lora_enhanced)",
        "mode": args.mode,
        "rubric": "评分标准/标准.md (AD相关性门控 × [delivery 30% / synergy 15% / "
                  "duration 10% / manufacturability 25% / safety 20%]; overall = "
                  "deterministic gated fusion, model's own overall in ca_overall)" if args.rubric else None,
        "gate": GATE if args.rubric else None,
        "agent_chain": ["solo-prompt (ca adapter)"] if args.mode == "prompt"
                       else ["epa", "mma", "bsa", "ca"],
        "timestamp": TS,
        "elapsed_s": round(time.time() - t0, 1),
        "results": [
            {"ID": r["ID"], "Compound": r["Compound"], "Class": r["Class"],
             "Mechanism": r["Mechanism"], "agent_scores": s}
            for r, s in zip(records, all_scores)
        ],
    }
    out_file = RUN_DIR / f"adtb100_scores_{TS}.json"
    out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    n_overall = sum(1 for s in all_scores if s["overall"] is not None)
    print(f"\nDone in {out['elapsed_s']}s. Overall score parsed for {n_overall}/{len(records)}.")
    print(f"-> {out_file}")
    print("Next: python scripts/compare_adtb100.py", TS)


if __name__ == "__main__":
    main()
