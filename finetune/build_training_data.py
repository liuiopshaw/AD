#!/usr/bin/env python3
"""
Build instruction-tuning training data from PDF literature.
Maps topic → agent → extracts text → generates JSONL training pairs.
"""

import csv
import hashlib
import json
import os
import random
import re
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = os.environ.get("CU_AGENT_ROOT", "E:/Cu-agent")
BASE_DIR = Path(PROJECT_ROOT) / "智能体建库文献"
OUTPUT_DIR = Path(PROJECT_ROOT) / "data" / "training"
V2_OUTPUT_DIR = Path(PROJECT_ROOT) / "data" / "training_v2"
LITERATURE_DIR = Path(PROJECT_ROOT) / "data" / "literature"
TEXT_DIR = LITERATURE_DIR / "texts"
INDEX_CSV = LITERATURE_DIR / "literature_index.csv"
MIX_CONFIG = Path(__file__).with_name("data_mix_config.json")

# Topic → Agent mapping (all 16 topic dirs covered; duplicates below)
TOPIC_AGENTS = {
    "1 阿尔兹海默症": ["mma", "ea"],            # basic info (medicine-related)
    "2 阿尔兹海默症的治疗": ["bsa", "mma", "ca"],  # treatment (incl. small molecules/biologics)
    "3 肠道菌群": ["apa", "mma", "ea"],
    "4 纳米材料的纳米医学应用": ["ea", "epa", "bsa", "ca"],
    "5 纳米材料抗菌": ["apa", "ea"],
    "6 金属纳米团簇的合成策略": ["ea", "epa"],
    "7 注射治疗方式": ["bsa"],                   # administration route → biosafety
    "8环糊精": ["ea", "mma"],
    "9团簇结构": ["ea", "epa"],
    "10 选择性抗菌": ["apa", "mma"],
    "DFT": ["epa", "mma"],
    "酶活性": ["epa"],
    "铜环糊精": ["ea", "apa", "epa", "mma"],
    # Cu x gut-microbiome cross-domain supplement (finetune/fetch_cross_lit.py)
    "11 补充-Cu菌群交叉": ["ea", "apa", "epa", "bsa", "mma", "ca"],
}

# Duplicate topic dirs (byte-identical content per finetune/literature_index.py).
# Exact-name match, checked BEFORE TOPIC_AGENTS substring matching; only the
# canonical dir is mapped, consistent with the index's is_duplicate flag.
DUPLICATE_TOPIC_DIRS = {
    "7 注射治疗方式×": "7 注射治疗方式",
    "DFT理论（10篇）": "DFT理论",
    "铜环糊精（10篇）": "铜环糊精",
}


def match_agents(topic_name: str):
    """Return (agents, skip_note). skip_note is non-empty when the dir is skipped."""
    if topic_name in DUPLICATE_TOPIC_DIRS:
        return [], f"duplicate of '{DUPLICATE_TOPIC_DIRS[topic_name]}' — skipped"
    for pattern, agents in TOPIC_AGENTS.items():
        if pattern in topic_name:
            return agents, ""
    return [], "no agent mapping"

# Instruction templates per agent
INSTRUCTIONS = {
    "ea": (
        "Extract structured nanomaterial information from the following research text. "
        "Include: material name, type, core elements, coating, size (nm), shape, synthesis method, "
        "antibacterial data (MIC, MBC, selectivity ratio), enzyme activity data "
        "(CAT-like, SOD-like, NADH oxidase-like), and biosafety data. "
        "Output as JSON with these fields."
    ),
    "apa": (
        "Evaluate the selective antibacterial performance of the nanomaterial described in the text. "
        "Score on 4 dimensions (1-10): bactericidal potency (40%), pathogen-probiotic selectivity (35%), "
        "spectrum breadth (15%), resistance risk (10%). Note in-vitro vs in-vivo data. Output as JSON."
    ),
    "epa": (
        "Classify the enzyme-like catalytic activity of the nanomaterial in the text. "
        "Focus on: CAT-like (catalase), SOD-like (superoxide dismutase), NADH oxidase-like. "
        "Score: activity strength (65%, NADH-like gets bonus), substrate affinity (25%), "
        "condition window (10%). Note AD therapeutic relevance. Output as JSON."
    ),
    "bsa": (
        "Assess the biosafety of the nanomaterial in the text. "
        "Score: cytotoxicity (30%), major organ damage - liver/kidney/spleen/brain (25%), "
        "in-vivo toxicity (20%), environmental risk (15%), structural stability (10%). "
        "Output safety grade (A/B/C/D/F) and organ-specific risks as JSON."
    ),
    "mma": (
        "Explain the selective antibacterial mechanism of the nanomaterial in the text. "
        "Why differential activity against pathogens vs probiotics? "
        "Describe: ROS pathway, cell wall/membrane differential interaction, "
        "gut microbiota modulation pathway, and gut-brain axis relevance for Alzheimer's therapy. "
        "Output structured mechanism analysis as JSON."
    ),
    "toa": (
        "Analyze the research task described in the text. "
        "Determine: does it need antibacterial evaluation? enzyme activity classification? "
        "biosafety assessment? mechanism analysis? comparison? "
        "Output intent analysis as JSON."
    ),
    "ca": (
        "Compare the nanomaterial(s) described in the text across dimensions: "
        "antibacterial, enzyme activity, biosafety. "
        "Rank materials and recommend the best candidate. "
        "Include AD therapeutic potential assessment. Output comparison report as JSON."
    ),
}


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF file."""
    import fitz  # pymupdf — lazy import so --dry-run works without it
    try:
        doc = fitz.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        return text.strip()
    except Exception as e:
        print(f"  Failed to extract {pdf_path.name}: {e}")
        return ""


def clean_text(text: str) -> str:
    """Clean extracted text."""
    # Remove excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {3,}', '  ', text)
    # Remove reference-like patterns at end
    text = re.sub(r'\nReferences?\n.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Truncate very long texts
    if len(text) > 8000:
        text = text[:8000] + "\n...[truncated]"
    return text


def generate_training_pair(text: str, agent: str) -> dict:
    """Generate a training pair for a specific agent."""
    instruction = INSTRUCTIONS.get(agent, INSTRUCTIONS["ea"])
    return {
        "instruction": instruction,
        "input": text[:6000],  # Keep input manageable
        "output": "",  # To be filled by annotation or left empty for inference
    }


def scan_literature():
    """Scan the literature library and print topic dirs + PDF counts (dry-run).

    Unlike the real build, unmapped topic dirs are still counted/printed so the
    scan reflects the full library; the real build skips them silently.
    """
    total_pdfs = 0
    topic_count = 0
    for topic_dir in sorted(BASE_DIR.iterdir()):
        if not topic_dir.is_dir():
            continue

        topic_name = topic_dir.name
        matched_agents, skip_note = match_agents(topic_name)

        pdfs = list(topic_dir.glob("**/*.pdf"))
        topic_count += 1
        total_pdfs += len(pdfs)

        if skip_note:
            print(f"\n{topic_name}: {len(pdfs)} PDFs ({skip_note})")
            continue
        print(f"\n{topic_name}: {len(pdfs)} PDFs → {matched_agents}")

    print(f"\n{'='*60}")
    print(f"SCAN: {topic_count} topic directories, {total_pdfs} PDFs total")
    print(f"{'='*60}")
    return topic_count, total_pdfs


# ---------------------------------------------------------------------------
# --index mode: quota-aware v2 build from literature_index.csv
# ---------------------------------------------------------------------------

def _pair_hash(pair: dict) -> str:
    return hashlib.sha256(
        (pair["instruction"] + "\n" + pair["input"]).encode("utf-8")
    ).hexdigest()


def _load_existing_hashes(agent: str) -> set:
    """Hashes of instruction+input already present in data/training/<agent>."""
    path = OUTPUT_DIR / f"{agent}_training_data.jsonl"
    hashes = set()
    if not path.exists():
        return hashes
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            hashes.add(_pair_hash(obj))
    return hashes


def _is_cu_gut_nc(row: dict, pool_mode: str = "cu_gut_nanocluster") -> bool:
    """Quota flag. Modes:
    - cu_gut_nanocluster (strict): Cu x gut-microbiome x nanocluster keyword
    - cu_gut_nanomaterial (relaxed): Cu x gut-microbiome x any nanomaterial
      (the real cross-domain literature uses nanozymes/nanocomposites —
      CuL NCs, CuPt, Cu-Mn3O4 — which lack the literal 'cluster' keyword)
    """
    base = row["is_cu"] == "1" and "gut_microbiome" in row["mechanisms"].split(";")
    if pool_mode == "cu_gut_nanomaterial":
        return base and row["modality"] == "nanomaterial"
    return base and row["is_nanocluster"] == "1"


def build_from_index(index_path: Path, config_path: Path):
    """Build data/training_v2/<agent>.jsonl from literature_index.csv.

    Per-agent sampling honors data_mix_config.json:
      - per_agent_target: max NEW samples per agent (dedup vs data/training/)
      - cu_gut_microbiome_nanocluster_min_fraction: hard quota. Non-quota
        samples are capped so eligible/selected >= fraction. If the eligible
        pool is empty the shortfall is reported, never fabricated.
    """
    import math

    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    frac = float(cfg.get("cu_gut_microbiome_nanocluster_min_fraction", 0.25))
    pool_mode = cfg.get("quota_pool", "cu_gut_nanocluster")
    targets = cfg.get("per_agent_target", {})
    priority = set(cfg.get("priority_agents", []))

    with open(index_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # Candidate pool per agent: (pair, is_quota, relpath)
    pools = defaultdict(list)
    existing = {}
    n_skipped_dup_input = 0
    for row in rows:
        if row["is_duplicate"] == "1" or row["extract_status"] not in ("ok", "cached"):
            continue
        agents, skip_note = match_agents(row["topic_dir"])
        if not agents:
            continue
        text_path = TEXT_DIR / f"{row['sha256']}.txt"
        if not text_path.exists():
            continue
        text = text_path.read_text(encoding="utf-8", errors="replace")
        if len(text) < 200:
            continue
        text = clean_text(text)
        quota = _is_cu_gut_nc(row, pool_mode)
        for agent in agents:
            pair = generate_training_pair(text, agent)
            if agent not in existing:
                existing[agent] = _load_existing_hashes(agent)
            h = _pair_hash(pair)
            if h in existing[agent]:
                n_skipped_dup_input += 1
                continue
            existing[agent].add(h)  # also dedup within v2 itself
            pools[agent].append((pair, quota, row["relpath"]))

    print(f"Candidate pools built (skipped {n_skipped_dup_input} already-in-training pairs)")
    for agent in sorted(pools):
        n_q = sum(1 for _, q, _ in pools[agent] if q)
        print(f"  {agent}: pool={len(pools[agent])} (quota-eligible={n_q})"
              f"{' [priority]' if agent in priority else ''}")

    V2_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)

    print(f"\n{'='*60}")
    print(f"V2 BUILD (quota fraction >= {frac:.0%}) → {V2_OUTPUT_DIR}")
    print(f"{'='*60}")
    for agent in sorted(set(targets) | set(pools)):
        target = int(targets.get(agent, 0))
        pool = pools.get(agent, [])
        eligible = sorted((p for p in pool if p[1]), key=lambda p: p[2])
        others = sorted((p for p in pool if not p[1]), key=lambda p: p[2])
        rng.shuffle(eligible)
        rng.shuffle(others)

        take_eligible = min(math.ceil(target * frac), len(eligible))
        take_other = min(len(others), target - take_eligible)
        # Hard cap so eligible/selected >= frac whenever eligible exist
        if take_eligible > 0:
            max_other = math.floor(take_eligible * (1 - frac) / frac)
            take_other = min(take_other, max_other)

        selected = eligible[:take_eligible] + others[:take_other]
        total = len(selected)
        achieved = take_eligible / total if total else 0.0

        status = "OK"
        if take_eligible == 0 and total > 0:
            status = "WARNING: quota pool empty for this agent — 0% Cu×gut×nanocluster"
        elif achieved < frac:
            status = "WARNING: quota shortfall"

        if total == 0:
            print(f"  {agent}: 0 new samples (target={target}) — no file written {status}")
            continue
        output_path = V2_OUTPUT_DIR / f"{agent}.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for pair, _, _ in selected:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        print(f"  {agent}: {total} new samples (target={target}, "
              f"Cu×gut×nanocluster={take_eligible} = {achieved:.1%}) → {output_path} {status}")


def main(dry_run: bool = False, index_path: Path = None, config_path: Path = MIX_CONFIG):
    if index_path is not None:
        build_from_index(index_path, config_path)
        return
    if dry_run:
        # Scan only: no extraction, no writes
        print(f"DRY RUN — scanning {BASE_DIR}")
        scan_literature()
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Collect by agent
    agent_pairs = defaultdict(list)
    total_pdfs = 0
    total_extracted = 0

    for topic_dir in sorted(BASE_DIR.iterdir()):
        if not topic_dir.is_dir():
            continue

        topic_name = topic_dir.name
        matched_agents, skip_note = match_agents(topic_name)

        if not matched_agents:
            print(f"Skipping: {topic_name} ({skip_note})")
            continue

        pdfs = list(topic_dir.glob("**/*.pdf"))
        print(f"\n{topic_name}: {len(pdfs)} PDFs → {matched_agents}")

        for pdf_path in pdfs:
            total_pdfs += 1
            text = extract_text_from_pdf(pdf_path)
            if not text or len(text) < 200:
                continue

            text = clean_text(text)
            total_extracted += 1

            # Create training pair for each mapped agent
            for agent in matched_agents:
                pair = generate_training_pair(text, agent)
                agent_pairs[agent].append(pair)

    # Write JSONL files per agent
    print(f"\n{'='*60}")
    print(f"Writing training data...")
    print(f"Total PDFs: {total_pdfs}, Successfully extracted: {total_extracted}")
    print(f"{'='*60}")

    for agent, pairs in sorted(agent_pairs.items()):
        output_path = OUTPUT_DIR / f"{agent}_training_data.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for pair in pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        print(f"  {agent}: {len(pairs)} pairs → {output_path}")

    # Summary
    print(f"\n{'='*60}")
    print("TRAINING DATA SUMMARY")
    print(f"{'='*60}")
    for agent in ["ea", "apa", "epa", "bsa", "mma", "toa", "ca"]:
        count = len(agent_pairs.get(agent, []))
        status = "OK" if count > 30 else "NEEDS MORE DATA"
        print(f"  {agent}: {count} pairs ({status})")
    print(f"\nTotal: {sum(len(v) for v in agent_pairs.values())} training pairs")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan the literature library and print topic dirs + PDF counts; no extraction, no writes")
    parser.add_argument("--index", nargs="?", const=str(INDEX_CSV), default=None,
                        help="Build data/training_v2/<agent>.jsonl from literature_index.csv "
                             "(default: %(const)s) with quota sampling per data_mix_config.json")
    parser.add_argument("--config", default=str(MIX_CONFIG),
                        help="Path to data mix config JSON (default: %(default)s)")
    args = parser.parse_args()
    main(dry_run=args.dry_run,
         index_path=Path(args.index) if args.index else None,
         config_path=Path(args.config))
