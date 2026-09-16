#!/usr/bin/env python3
"""
UniProt database query tool via REST API.

UniProt database query tool — validates protein accessions and searches
protein entries by gene name via the UniProtKB REST API. No API key required.

Base URL: https://rest.uniprot.org/uniprotkb

All public functions follow a unified contract: return None or [] on
miss/network failure, never raise exceptions to the caller.
Style aligned with src/tools/pubchem_tool.py (synchronous requests +
polite rate limiting + retries).
"""

# ---- Standard library and third-party imports ----
import requests       # HTTP library for calling the UniProt REST API
import logging        # Logging
import time           # Time handling, for request rate limiting and retry intervals
import random         # Random numbers, for adding jitter to retries (avoid thundering herd)
from typing import Any, Dict, List, Optional  # Type annotations

# ---- Logging configuration ----
# WARNING level: only log warnings and errors to reduce log noise during normal runs
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---- API constants ----
BASE_URL = "https://rest.uniprot.org/uniprotkb"
HEADERS = {"User-Agent": "ECOMATS-UniProt-Tool/1.0"}

# ---- Request rate limiting ----
# Key-free public API; polite rate limiting: minimum 0.4 s between requests (>= 0.3 s required)
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.4
_MAX_RETRIES = 3  # 1 initial attempt + 2 retries, then return None


def _get(url: str, params: Optional[Dict[str, Any]] = None,
         timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    Send a GET request (with rate limiting and retries) — the low-level method
    for all UniProt API calls.

    Retry strategy: exponential backoff + random jitter on network
    errors/5xx, up to 2 retries.
    404 is treated as a "miss" and returns None (no retry).

    Args:
        url: Full URL
        params: Query parameter dict
        timeout: Request timeout in seconds, default 20

    Returns:
        Dict: Parsed JSON dict returned by the API; None on miss or after all retries fail
    """
    global _last_request_time

    # ---- Request rate limiting ----
    # Compute the time elapsed since the last request; wait if below the minimum interval
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    for attempt in range(_MAX_RETRIES):
        try:
            logger.debug(f"Requesting UniProt API: {url} params={params}")

            _last_request_time = time.time()
            response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)

            # ---- 4xx: client errors (including 404 miss, 400 invalid params), no retry ----
            if 400 <= response.status_code < 500:
                return None

            # ---- 5xx errors: server busy, retry ----
            if response.status_code >= 500:
                logger.warning(f"UniProt server error {response.status_code} "
                               f"(attempt {attempt + 1}/{_MAX_RETRIES})")
                if attempt < _MAX_RETRIES - 1:
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    time.sleep(delay)
                    continue
                return None

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.warning(f"UniProt request failed (attempt {attempt + 1}/{_MAX_RETRIES}): {e}")
            if attempt < _MAX_RETRIES - 1:
                delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                time.sleep(delay)
            else:
                logger.error(f"UniProt request finally failed: {e}")
                return None
        except Exception as e:
            logger.error(f"Error processing UniProt response: {e}")
            return None
    return None


def _entry_summary(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Extract summary fields from a UniProtKB entry record."""
    # Protein name: prefer recommendedName.fullName, fall back to the first submittedNames
    protein_name = None
    desc = entry.get("proteinDescription") or {}
    rec = (desc.get("recommendedName") or {}).get("fullName") or {}
    protein_name = rec.get("value")
    if not protein_name:
        submitted = desc.get("submittedNames") or []
        if submitted:
            protein_name = ((submitted[0].get("fullName") or {}).get("value"))

    # Gene name: geneName of the first gene
    gene = None
    genes = entry.get("genes") or []
    if genes:
        gene = ((genes[0].get("geneName") or {}).get("value"))

    # Function annotation: the first comment with commentType == FUNCTION
    function_comment = None
    for c in entry.get("comments") or []:
        if c.get("commentType") == "FUNCTION":
            texts = c.get("texts") or []
            if texts:
                function_comment = texts[0].get("value")
            break

    return {
        "accession": entry.get("primaryAccession"),
        "protein_name": protein_name,
        "gene": gene,
        "organism": (entry.get("organism") or {}).get("scientificName"),
        "function_comment": function_comment,
    }


def get_entry(accession: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a UniProtKB entry by accession (also validates that the accession exists).

    Args:
        accession: UniProt accession, e.g. "P05067" (APP)

    Returns:
        Dict: {"accession", "protein_name", "gene", "organism",
               "function_comment"}; None if the accession does not exist or on failure
    """
    if not accession or not accession.strip():
        return None
    entry = _get(f"{BASE_URL}/{accession.strip()}.json")
    if not entry:
        return None
    return _entry_summary(entry)


def search_gene(gene: str, organism: str = "Homo sapiens",
                limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search UniProtKB entries by gene name (restricted to human, reviewed/Swiss-Prot by default).

    Args:
        gene: Gene symbol, e.g. "APP"
        organism: Organism scientific name, default "Homo sapiens"
        limit: Maximum number of results, default 5

    Returns:
        List: List of entry summary dicts (same structure as get_entry); [] on miss or failure
    """
    if not gene or not gene.strip():
        return []
    query = f'gene:{gene.strip()} AND organism_name:"{organism}" AND reviewed:true'
    data = _get(f"{BASE_URL}/search",
                params={"query": query, "format": "json", "size": limit})
    results = (data or {}).get("results") or []
    return [_entry_summary(e) for e in results]


if __name__ == "__main__":
    # ---- Smoke test: live network query for APP (P05067) ----
    print("== get_entry('P05067') ==")
    entry = get_entry("P05067")
    print({k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v)
           for k, v in (entry or {}).items()})
    assert entry and "Amyloid" in (entry.get("protein_name") or ""), \
        "P05067 protein name does not contain 'Amyloid'"

    print("\n== search_gene('APP') ==")
    for e in search_gene("APP"):
        print(e["accession"], e["protein_name"], e["gene"], e["organism"])

    print("\n== miss cases ==")
    print("bogus accession:", get_entry("P000000000"))
    print("bogus gene:", search_gene("NOTAREALGENE123"))
    print("\nSmoke test OK")
