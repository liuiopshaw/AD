#!/usr/bin/env python3
"""
Literature library indexer and rule-based tagger (Phase 1).

Walks the PDF library, deduplicates by SHA-256 file hash, extracts full text
with PyMuPDF (fitz, lazy import) into data/literature/texts/<sha256>.txt
(resumable: existing text files are skipped), tags each document from
filename + first 3000 chars, and writes data/literature/literature_index.csv.

Usage:
    python finetune/literature_index.py            # full run
    python finetune/literature_index.py --stats    # only re-print stats from CSV
"""

import argparse
import csv
import hashlib
import os
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = os.environ.get("CU_AGENT_ROOT", "E:/Cu-agent")
BASE_DIR = Path(PROJECT_ROOT) / "智能体建库文献"
OUT_DIR = Path(PROJECT_ROOT) / "data" / "literature"
TEXT_DIR = OUT_DIR / "texts"
CSV_PATH = OUT_DIR / "literature_index.csv"

# filename + first N chars of body feed the tagger.
# 8000 (was 3000): open-access PDFs (e.g. BMC journals) prepend a long
# license/copyright boilerplate page that pushed title+abstract beyond the
# old 3000-char window, causing missed gut_microbiome/is_cu tags.
TAG_TEXT_CHARS = 8000

# ---------------------------------------------------------------------------
# Tagging rules (Chinese + English keywords)
# ---------------------------------------------------------------------------

BIOLOGIC_KEYWORDS = [
    "antibody", "monoclonal", "mab", "immunoglobulin", "peptide", "protein",
    "enzyme replacement", "vaccine", "immunization", "aav", "adeno-associated",
    "sirna", "small interfering rna", "mrna", "aptamer", "oligonucleotide",
    "antisense", "gene therapy", "stem cell", "exosome",
    "抗体", "单抗", "单克隆", "多肽", "肽类", "蛋白", "疫苗", "适配体",
    "核酸适配体", "基因治疗", "干细胞", "外泌体", "寡核苷酸",
]

SMALL_MOLECULE_KEYWORDS = [
    "small molecule", "small-molecule", "inhibitor", "agonist", "antagonist",
    "donepezil", "memantine", "rivastigmine", "galantamine", "aducanumab",
    "lecanemab", "drug candidate", "pharmacokinetic", "bioavailability",
    "小分子", "抑制剂", "激动剂", "拮抗剂", "多奈哌齐", "美金刚", "卡巴拉汀",
    "加兰他敏", "药代动力学", "生物利用度",
]

NANOMATERIAL_KEYWORDS = [
    "nanoparticle", "nanomaterial", "nanocluster", "nano-cluster", "nanozyme",
    "nanocomposite", "nanostructure", "nanocarrier", "nanodrug", "nanosheet",
    "nanorod", "nanowire", "nanotube", "quantum dot", "nano ", "nano-",
    "纳米",
]

NANOCLUSTER_KEYWORDS = ["nanocluster", "nano-cluster", "cluster", "团簇"]

MECHANISM_KEYWORDS = {
    "gut_microbiome": [
        "gut microbiota", "gut microbiome", "gut-brain", "gut brain axis",
        "intestinal flora", "intestinal microbiota", "microbiota-gut-brain",
        "肠道菌群", "肠道微生物", "肠脑轴", "肠-脑轴", "菌群",
    ],
    "amyloid": [
        "amyloid", "aβ", "abeta", "β-amyloid", "淀粉样", "β淀粉样",
    ],
    "tau": [
        "tau protein", "tau phosphorylation", "phosphorylated tau",
        "p-tau", "tau pathology", "tau ", "tau蛋白", "磷酸化tau", "tau磷酸化",
    ],
    "neuroinflammation": [
        "neuroinflammation", "microglia", "astrocyte", "neuroimmune",
        "神经炎症", "小胶质细胞", "星形胶质细胞",
    ],
    "autophagy": ["autophagy", "autophagic", "自噬"],
    "antioxidant": [
        "antioxidant", "reactive oxygen", "ros ", "oxidative stress",
        "superoxide", "抗氧化", "活性氧", "氧化应激",
    ],
}

CU_PATTERN = re.compile(r"\bCu\b")
CU_KEYWORDS = ["copper", "铜"]
CYCLODEXTRIN_KEYWORDS = ["cyclodextrin", "环糊精"]

CSV_FIELDS = [
    "relpath", "topic_dir", "sha256", "is_duplicate", "pages", "chars",
    "extract_status", "modality", "is_nanocluster", "mechanisms",
    "is_cu", "is_cyclodextrin",
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text(pdf_path: Path):
    """Extract full text and page count. Returns (text, pages, status)."""
    import fitz  # pymupdf — lazy import so --stats works without it
    try:
        doc = fitz.open(str(pdf_path))
        pages = doc.page_count
        parts = [page.get_text() for page in doc]
        doc.close()
        text = "\n".join(parts).strip()
        if not text:
            return "", pages, "empty"
        return text, pages, "ok"
    except Exception as e:
        print(f"  [extract failed] {pdf_path.name}: {e}")
        return "", 0, "failed"


def _contains_any(haystack: str, keywords) -> bool:
    low = haystack.lower()
    return any(k.lower() in low for k in keywords)


def tag_document(filename: str, text_head: str) -> dict:
    """Rule-based tags from filename + first TAG_TEXT_CHARS chars of body."""
    hay = f"{filename}\n{text_head}"

    if _contains_any(hay, NANOMATERIAL_KEYWORDS):
        modality = "nanomaterial"
    elif _contains_any(hay, BIOLOGIC_KEYWORDS):
        modality = "biologic"
    elif _contains_any(hay, SMALL_MOLECULE_KEYWORDS):
        modality = "small_molecule"
    else:
        modality = "unknown"

    is_nanocluster = modality == "nanomaterial" and _contains_any(hay, NANOCLUSTER_KEYWORDS)

    mechanisms = [m for m, kws in MECHANISM_KEYWORDS.items() if _contains_any(hay, kws)]
    if not mechanisms:
        mechanisms = ["other"]

    is_cu = bool(CU_PATTERN.search(hay)) or _contains_any(hay, CU_KEYWORDS)
    is_cyclodextrin = _contains_any(hay, CYCLODEXTRIN_KEYWORDS)

    return {
        "modality": modality,
        "is_nanocluster": int(is_nanocluster),
        "mechanisms": ";".join(mechanisms),
        "is_cu": int(is_cu),
        "is_cyclodextrin": int(is_cyclodextrin),
    }


def build_index():
    TEXT_DIR.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(
        p for p in BASE_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf"
    )
    print(f"Found {len(pdfs)} PDF files under {BASE_DIR}")

    rows = []
    seen = {}  # sha256 -> canonical row (first occurrence)
    n_ok = n_cached = n_dup = n_failed = n_empty = 0

    for i, pdf in enumerate(pdfs, 1):
        rel = pdf.relative_to(BASE_DIR).as_posix()
        topic_dir = pdf.relative_to(BASE_DIR).parts[0]
        digest = sha256_of(pdf)

        if digest in seen:
            # Duplicate content: keep the canonical copy's tags (identical body).
            canon = seen[digest]
            row = {
                "relpath": rel, "topic_dir": topic_dir, "sha256": digest,
                "is_duplicate": 1, "pages": canon["pages"], "chars": canon["chars"],
                "extract_status": "duplicate",
                "modality": canon["modality"], "is_nanocluster": canon["is_nanocluster"],
                "mechanisms": canon["mechanisms"], "is_cu": canon["is_cu"],
                "is_cyclodextrin": canon["is_cyclodextrin"],
            }
            rows.append(row)
            n_dup += 1
            continue

        text_path = TEXT_DIR / f"{digest}.txt"
        if text_path.exists():
            text = text_path.read_text(encoding="utf-8", errors="replace")
            status = "cached"
            pages = ""  # unknown without reopening; left blank for cached texts
            n_cached += 1
        else:
            text, pages, status = extract_text(pdf)
            if status == "ok":
                text_path.write_text(text, encoding="utf-8")
                n_ok += 1
            elif status == "empty":
                n_empty += 1
            else:
                n_failed += 1

        tags = tag_document(pdf.name, text[:TAG_TEXT_CHARS])
        row = {
            "relpath": rel, "topic_dir": topic_dir, "sha256": digest,
            "is_duplicate": 0, "pages": pages, "chars": len(text),
            "extract_status": status, **tags,
        }
        rows.append(row)
        seen[digest] = row

        if i % 50 == 0 or i == len(pdfs):
            print(f"  [{i}/{len(pdfs)}] extracted={n_ok} cached={n_cached} "
                  f"dup={n_dup} failed={n_failed} empty={n_empty}", flush=True)

    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} rows → {CSV_PATH}")
    return rows


def print_stats(rows):
    total = len(rows)
    dups = sum(1 for r in rows if str(r["is_duplicate"]) == "1")
    unique = total - dups

    status_c = Counter(r["extract_status"] for r in rows)
    modality_c = Counter(r["modality"] for r in rows if str(r["is_duplicate"]) != "1")
    mech_c = Counter()
    for r in rows:
        if str(r["is_duplicate"]) == "1":
            continue
        for m in str(r["mechanisms"]).split(";"):
            if m:
                mech_c[m] += 1
    n_cu = sum(1 for r in rows if str(r["is_duplicate"]) != "1" and str(r["is_cu"]) == "1")
    n_cd = sum(1 for r in rows if str(r["is_duplicate"]) != "1" and str(r["is_cyclodextrin"]) == "1")
    n_nc = sum(1 for r in rows if str(r["is_duplicate"]) != "1" and str(r["is_nanocluster"]) == "1")
    n_cu_gut_nc = sum(
        1 for r in rows
        if str(r["is_duplicate"]) != "1" and str(r["is_cu"]) == "1"
        and str(r["is_nanocluster"]) == "1"
        and "gut_microbiome" in str(r["mechanisms"]).split(";")
    )

    print(f"\n{'='*60}\nLITERATURE INDEX STATS\n{'='*60}")
    print(f"Total rows: {total} | duplicates: {dups} | unique documents: {unique}")
    print(f"Extract status (all rows): {dict(status_c)}")
    print(f"\nModality distribution (unique docs):")
    for k, v in modality_c.most_common():
        print(f"  {k}: {v}")
    print(f"\nMechanism distribution (unique docs, multi-label):")
    for k, v in mech_c.most_common():
        print(f"  {k}: {v}")
    print(f"\nis_cu: {n_cu} | is_cyclodextrin: {n_cd} | is_nanocluster: {n_nc}")
    print(f"Cu ∩ gut_microbiome ∩ nanocluster (quota pool): {n_cu_gut_nc}")
    print(f"{'='*60}")


def load_csv():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", action="store_true",
                        help="Re-print statistics from the existing CSV without re-scanning")
    args = parser.parse_args()

    if args.stats:
        if not CSV_PATH.exists():
            sys.exit(f"No index at {CSV_PATH}; run without --stats first.")
        print_stats(load_csv())
        return

    rows = build_index()
    print_stats(rows)


if __name__ == "__main__":
    main()
