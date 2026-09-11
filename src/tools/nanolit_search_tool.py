#!/usr/bin/env python3
"""
NanoLitSearchTool — PubMed literature search for nanomaterial/nanozyme topics.

Uses NCBI E-utilities (esearch + esummary). No API key required, but
NCBI_API_KEY (env) raises the rate limit from 3 to 10 requests/sec.

Public interface:
    tool = NanoLitSearchTool()
    result = tool.run(query="nanozyme NADH oxidase", query_type="comprehensive")

Returns a JSON-serializable dict; failures are reported as
{"success": False, "error": ...} rather than raising.
"""

import os
import re
import time
import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class NanoLitSearchTool:
    """Search PubMed for nanomaterial / nanozyme literature."""

    name = "nanolit_search"
    description = "Search PubMed for nanomaterial and nanozyme literature"

    def __init__(self, max_results: int = 10, timeout: int = 30):
        self.max_results = max_results
        self.timeout = timeout
        self.api_key = os.getenv("NCBI_API_KEY")
        # NCBI: 3 req/s without key, 10 req/s with key
        self._min_interval = 0.11 if self.api_key else 0.34
        self._last_request = 0.0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(self, query: str, query_type: str = "comprehensive", max_results: Optional[int] = None) -> Dict[str, Any]:
        """Run a PubMed search. query_type is accepted for interface
        compatibility ('comprehensive', 'title', ...) and currently maps to
        a standard PubMed keyword search."""
        limit = max_results or self.max_results
        if not query or not query.strip():
            return {"success": False, "error": "Empty query", "results": []}

        try:
            pmids = self._esearch(query.strip(), limit)
            if not pmids:
                return {"success": True, "query": query, "count": 0, "results": []}
            articles = self._esummary(pmids)
            return {
                "success": True,
                "query": query,
                "count": len(articles),
                "results": articles,
            }
        except requests.RequestException as e:
            logger.warning(f"PubMed request failed: {e}")
            return {"success": False, "error": str(e), "results": []}

    # ------------------------------------------------------------------
    # NCBI E-utilities
    # ------------------------------------------------------------------
    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    def _params(self, extra: Dict[str, Any]) -> Dict[str, Any]:
        params = {"tool": "cu-agent", "email": os.getenv("NCBI_EMAIL", "cu-agent@example.com")}
        if self.api_key:
            params["api_key"] = self.api_key
        params.update(extra)
        return params

    def _esearch(self, query: str, limit: int) -> List[str]:
        self._throttle()
        resp = requests.get(
            f"{EUTILS_BASE}/esearch.fcgi",
            params=self._params({
                "db": "pubmed",
                "term": query,
                "retmax": limit,
                "retmode": "json",
                "sort": "relevance",
            }),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("esearchresult", {}).get("idlist", [])

    def _esummary(self, pmids: List[str]) -> List[Dict[str, Any]]:
        self._throttle()
        resp = requests.get(
            f"{EUTILS_BASE}/esummary.fcgi",
            params=self._params({
                "db": "pubmed",
                "id": ",".join(pmids),
                "retmode": "json",
            }),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json().get("result", {})

        articles = []
        for pmid in data.get("uids", []):
            item = data.get(pmid, {})
            if not item:
                continue
            authors = [a.get("name", "") for a in item.get("authors", [])[:5]]
            articles.append({
                "pmid": pmid,
                "title": item.get("title", ""),
                "journal": item.get("fulljournalname", item.get("source", "")),
                "pub_date": item.get("pubdate", ""),
                "authors": authors,
                "doi": self._extract_doi(item),
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            })
        return articles

    @staticmethod
    def _extract_doi(item: Dict[str, Any]) -> Optional[str]:
        for aid in item.get("articleids", []):
            if aid.get("idtype") == "doi":
                return aid.get("value")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tool = NanoLitSearchTool(max_results=3)
    result = tool.run(query="nanozyme NADH oxidase")
    print(f"success={result['success']} count={result.get('count')}")
    for art in result.get("results", []):
        print(f"  [{art['pmid']}] {art['title'][:80]}")
