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
     "ZnO-Cu/Mn 串联纳米酶恢复沙门氏菌结肠炎肠道稳态并调节肠道菌群——Cu纳米酶×菌群核心交叉"),
    ("39760067", "PMC11697280", "Q5/R3",
     "铜-木犀草素纳米复合物(CuL NCs)多重调控氧化应激/肠屏障/肠道菌群治疗IBD——Cu纳米×菌群核心交叉"),
    ("41732380", "PMC12924754", "R1/R7",
     "Cu掺杂Mn3O4纳米酶水凝胶微球口服靶向治疗IBD——Cu纳米酶×肠道炎症"),
    ("41896865", "PMC13151254", "R1",
     "益生菌-CuPt纳米酶杂化系统穿透黏液、清除幽门螺杆菌生物膜并调节菌群"),
    ("39858184", "PMC11758615", "R5",
     "纳米铜-碳复合物日粮调控断奶兔抗氧化/免疫/盲肠菌群——Cu纳米×肠道菌群(畜牧模型)"),
    ("41892335", "PMC13024964", "Q1/R6",
     "铜稳态与肠道健康综述:分子机制到治疗干预——Cu×肠道机制教学(邻近)"),
    ("39135557", "PMC11317476", "R4",
     "有毒/必需金属(含铜)与肠道菌群代谢互作及健康影响综述——Cu×菌群机制(邻近)"),
    ("38741962", "PMC11089525", "Q6",
     "超小Cu30纳米团簇作为高效抗菌剂治疗原发性腹膜炎——Cu团簇抗菌(机制邻近)"),
    ("31459656", "PMC6648608", "Q6",
     "铜纳米团簇掺杂发光羟基磷灰石纳米粒抗菌/抗生物膜——Cu团簇抗菌(机制邻近)"),
    ("41080727", "PMC12512988", "Q1/Q6",
     "维生素C功能化铜纳米酶治疗耐药胞内感染与过度炎症——Cu纳米酶抗菌(机制邻近)"),
    ("41537187", "PMC12798781", "Q6/R2",
     "铜纳米团簇修饰硅酸镁微针增强抗菌与糖尿病创面组织重塑——Cu团簇抗菌(机制邻近)"),
    ("41254219", "PMC12627415", "R2",
     "BSA保护铜纳米团簇免标记生物传感器鉴别细菌菌株——Cu团簇×细菌鉴别(机制邻近)"),
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
