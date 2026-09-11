#!/usr/bin/env python3
"""
Targeted fetch of open-access literature at the Cu-nanocluster x gut-microbiome
intersection (and mechanism-adjacent topics) from Europe PMC.

Step 1 (query): runs a set of query strings, dedups hits by PMID, and dumps a
screening table (title/year/journal/OA/PMCID/abstract snippet) to
data/literature/cross_search_hits.json for manual relevance screening.

No fabrication: only real Europe PMC hits are recorded; download step saves the
publisher PDF (or PMC OA package PDF) verbatim.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
OUT_JSON = Path("E:/Cu-agent/data/literature/cross_search_hits.json")

QUERIES = {
    "Q1_cuNC_x_gut": (
        '("copper nanocluster" OR "copper nanoclusters" OR "Cu nanocluster" '
        'OR "Cu nanoclusters" OR "copper nanozyme") '
        'AND ("gut microbiota" OR "gut microbiome" OR "intestinal flora")'
    ),
    "Q2_cuNC_x_AD_gutbrain": (
        '"copper nanocluster" AND (Alzheimer OR "gut-brain axis")'
    ),
    "Q3_cd_cu_x_microbiota": (
        'cyclodextrin AND copper AND (nanocluster OR nanozyme) '
        'AND (microbiota OR microbiome OR antibacterial)'
    ),
    "Q4_cu_nanozyme_dysbiosis": (
        '("Cu nanozyme" OR "copper nanozyme") AND (dysbiosis OR microbiome)'
    ),
    "Q5_cu_nano_IBD_microbiome": (
        'copper AND (nanoparticle OR nanomaterial OR nanozyme OR nanocluster) '
        'AND (colitis OR "inflammatory bowel") AND (microbiota OR microbiome)'
    ),
    "Q6_cuNC_antibacterial": (
        '("copper nanoclusters" OR "Cu nanoclusters") AND antibacterial'
    ),
    "Q7_cu_nanozyme_colitis": (
        '("copper nanozyme" OR "Cu nanozyme" OR "copper-based nanozyme") AND colitis'
    ),
    "Q8_cuNC_intestinal": (
        '("copper nanocluster" OR "Cu nanocluster") '
        'AND (intestinal OR intestine OR gut)'
    ),
    "Q9_cu_nanozyme_gut": (
        '("copper nanozyme" OR "Cu-based nanozyme") '
        'AND ("gut microbiota" OR "intestinal microbiota")'
    ),
    "Q10_cu_single_atom_microbiome": (
        '("copper single-atom" OR "Cu single-atom" OR "copper single atom") '
        'AND (microbiota OR microbiome)'
    ),
}


def epmc_search(query: str, page_size: int = 100) -> dict:
    params = urllib.parse.urlencode({
        "query": query,
        "format": "json",
        "pageSize": str(page_size),
        "resultType": "core",
    })
    url = f"{EPMC_SEARCH}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "cu-agent-lit-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    hits = {}  # pmid -> record
    counts = {}
    for tag, q in QUERIES.items():
        try:
            data = epmc_search(q)
        except Exception as e:
            print(f"{tag}: QUERY FAILED: {e}")
            counts[tag] = -1
            continue
        n = data.get("hitCount", 0)
        counts[tag] = n
        print(f"{tag}: hitCount={n}")
        for r in data.get("resultList", {}).get("result", []):
            pmid = r.get("pmid") or r.get("id")
            if not pmid:
                continue
            rec = hits.setdefault(pmid, {
                "pmid": pmid,
                "pmcid": r.get("pmcid", ""),
                "doi": r.get("doi", ""),
                "title": r.get("title", ""),
                "journal": r.get("journalTitle", ""),
                "year": r.get("pubYear", ""),
                "is_open_access": r.get("isOpenAccess", "N"),
                "in_epmc": r.get("inEPMC", "N"),
                "has_pdf": r.get("hasPDF", "N"),
                "pub_type": r.get("pubType", ""),
                "abstract": (r.get("abstractText") or "")[:1500],
                "queries": [],
            })
            rec["queries"].append(tag)
        time.sleep(1)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"query_hit_counts": counts, "unique_hits": len(hits),
         "hits": sorted(hits.values(), key=lambda x: (x["year"], x["pmid"]), reverse=True)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nUnique hits: {len(hits)} -> {OUT_JSON}")

    # Screening table
    for h in hits.values():
        oa = f"OA={h['is_open_access']}/PDF={h['has_pdf']}"
        print(f"\nPMID {h['pmid']} | {h['pmcid'] or '-'} | {h['year']} | {oa} | {','.join(h['queries'])}")
        print(f"  {h['title']}")
        ab = h["abstract"].replace("\n", " ")
        print(f"  {ab[:300]}")


if __name__ == "__main__":
    sys.exit(main())
