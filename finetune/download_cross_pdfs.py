#!/usr/bin/env python3
"""
Download the screened open-access PDFs for the Cu x gut-microbiome cross-domain
supplement and write SOURCES.csv next to them.

Download route per paper:
  1. PMC OA web service (oa.fcgi?id=PMCxxxx) -> tar.gz -> extract .pdf
  2. Europe PMC fullTextUrlList direct PDF link
Papers that fail both are reported, never substituted.
"""

import csv
import io
import json
import re
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

DEST = Path("E:/Cu-agent/智能体建库文献/11 补充-Cu菌群交叉")
SOURCES_CSV = DEST / "SOURCES.csv"
UA = {"User-Agent": "cu-agent-lit-fetch/1.0 (literature supplement)"}

# (pmid, pmcid, query_tag, one-line relevance note)
SELECTED = [
    ("40114178", "PMC11924796", "Q5/R1/R7",
     "ZnO-Cu/Mn tandem nanozyme restores intestinal homeostasis in Salmonella colitis and modulates gut microbiota - core Cu nanozyme x microbiota crossover"),
    ("39760067", "PMC11697280", "Q5/R3",
     "Copper-luteolin nanocomplex (CuL NCs) treats IBD via multi-target regulation of oxidative stress/gut barrier/gut microbiota - core Cu nano x microbiota crossover"),
    ("41732380", "PMC12924754", "R1/R7",
     "Cu-doped Mn3O4 nanozyme hydrogel microspheres for oral targeted IBD therapy - Cu nanozyme x intestinal inflammation"),
    ("41896865", "PMC13151254", "R1",
     "Probiotic-CuPt nanozyme hybrid system penetrates mucus, eradicates Helicobacter pylori biofilms and modulates microbiota"),
    ("39858184", "PMC11758615", "R5",
     "Dietary nano-copper-carbon composite regulates antioxidant/immune/cecal microbiota in weaned rabbits - Cu nano x gut microbiota (livestock model)"),
    ("41892335", "PMC13024964", "Q1/R6",
     "Review of copper homeostasis and gut health: from molecular mechanisms to therapeutic intervention - Cu x gut mechanistic background (adjacent)"),
    ("39135557", "PMC11317476", "R4",
     "Review of metabolic interplay between toxic/essential metals (incl. copper) and gut microbiota and its health impacts - Cu x microbiota mechanism (adjacent)"),
    ("38741962", "PMC11089525", "Q6",
     "Ultrasmall Cu30 nanoclusters as highly efficient antibacterial agents for primary peritonitis - Cu cluster antibacterial (mechanistically adjacent)"),
    ("31459656", "PMC6648608", "Q6",
     "Cu-nanocluster-doped luminescent hydroxyapatite nanoparticles with antibacterial/antibiofilm activity - Cu cluster antibacterial (mechanistically adjacent)"),
    ("41080727", "PMC12512988", "Q1/Q6",
     "Vitamin C-functionalized copper nanozyme against drug-resistant intracellular infections and hyperinflammation - Cu nanozyme antibacterial (mechanistically adjacent)"),
    ("41537187", "PMC12798781", "Q6/R2",
     "Cu-nanocluster-decorated magnesium silicate microneedles enhance antibacterial activity and diabetic wound tissue remodeling - Cu cluster antibacterial (mechanistically adjacent)"),
    ("41254219", "PMC12627415", "R2",
     "BSA-protected Cu nanocluster label-free biosensor for bacterial strain discrimination - Cu cluster x bacterial identification (mechanistically adjacent)"),
]


def fetch(url: str, binary: bool = True, timeout: int = 120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def oa_tar_pdf(pmcid: str):
    """Return (pdf_bytes, suggested_name) via PMC OA service, or None."""
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmcid}"
    try:
        xml = fetch(url, timeout=60)
    except Exception as e:
        print(f"    oa.fcgi error: {e}")
        return None
    root = ET.fromstring(xml)
    link = root.find(".//link[@format='tgz']")
    if link is None:
        err = root.find(".//error")
        print(f"    OA service: no tgz link ({err.text if err is not None else 'not in OA subset'})")
        return None
    ftp = link.attrib["href"].replace("ftp://", "https://")
    try:
        blob = fetch(ftp)
    except Exception as e:
        print(f"    tar download error: {e}")
        return None
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        pdfs = [m for m in tf.getmembers() if m.name.lower().endswith(".pdf")]
        if not pdfs:
            print("    OA package has no PDF")
            return None
        m = max(pdfs, key=lambda x: x.size)
        return tf.extractfile(m).read(), Path(m.name).name


def epmc_pdf(pmid: str, pmcid: str):
    """Fallback: Europe PMC fullTextUrlList PDF link."""
    url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
           + urllib.parse.urlencode({"query": f"EXT_ID:{pmid} AND SRC:MED",
                                     "format": "json", "resultType": "core"}))
    try:
        d = json.loads(fetch(url, timeout=60).decode())
        urls = (d["resultList"]["result"][0].get("fullTextUrlList", {})
                .get("fullTextUrl", []))
    except Exception as e:
        print(f"    fullTextUrlList error: {e}")
        return None
    for u in urls:
        if u.get("documentStyle") == "pdf" and u.get("availability", "").startswith("Open"):
            try:
                data = fetch(u["url"])
                if data[:4] == b"%PDF":
                    return data, None
                print(f"    {u['url']} did not return a PDF")
            except Exception as e:
                print(f"    pdf fetch error ({u['url']}): {e}")
    return None


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    rows, failures = [], []
    for pmid, pmcid, qtag, note in SELECTED:
        print(f"PMID {pmid} / {pmcid}:")
        got = oa_tar_pdf(pmcid) if pmcid else None
        if got is None:
            got = epmc_pdf(pmid, pmcid)
        if got is None:
            print("    FAILED — no OA PDF obtained")
            failures.append(pmid)
            continue
        pdf_bytes, orig_name = got
        fname = f"PMID{pmid}_{pmcid}.pdf"
        (DEST / fname).write_bytes(pdf_bytes)
        print(f"    saved {fname} ({len(pdf_bytes)//1024} KB)")
        rows.append({"filename": fname, "pmid": pmid, "pmcid": pmcid,
                     "doi": "", "title": "", "query": qtag, "relevance": note})
        time.sleep(1)

    # fill doi/title from Europe PMC
    for r in rows:
        try:
            url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
                   + urllib.parse.urlencode({"query": f"EXT_ID:{r['pmid']} AND SRC:MED",
                                             "format": "json", "resultType": "core"}))
            d = json.loads(fetch(url, timeout=60).decode())
            rec = d["resultList"]["result"][0]
            r["doi"] = rec.get("doi", "")
            r["title"] = re.sub(r"<[^>]*>", "", rec.get("title", ""))
            time.sleep(0.5)
        except Exception as e:
            print(f"    metadata error for {r['pmid']}: {e}")

    with open(SOURCES_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "pmid", "pmcid", "doi",
                                          "title", "query", "relevance"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nDownloaded {len(rows)}/{len(SELECTED)} → {DEST}")
    print(f"SOURCES.csv → {SOURCES_CSV}")
    if failures:
        print(f"FAILED (no OA PDF): {failures}")


if __name__ == "__main__":
    sys.exit(main())
