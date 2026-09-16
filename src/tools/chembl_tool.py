#!/usr/bin/env python3
"""
ChEMBL database query tool via REST API.

ChEMBL database query tool — queries small-molecule drug/compound information
via the ChEMBL REST API, supports exact/flexible structure search by SMILES,
and retrieves bioactivity data by target. No API key required.

Base URL: https://www.ebi.ac.uk/chembl/api/data (JSON format)

All public functions follow a unified contract: return None or [] on
miss/network failure, and never raise exceptions to the caller.
Style aligned with src/tools/pubchem_tool.py (synchronous requests +
polite rate limiting + retries).
"""

# ---- Standard library and third-party imports ----
import requests                  # HTTP library, used to call the ChEMBL REST API
import logging                   # Logging
import time                      # Time handling, for request rate control and retry intervals
import random                    # Random numbers, to add jitter on retries (avoid thundering herd)
from urllib.parse import quote   # URL encoding (SMILES contains special characters and must be encoded)
from typing import Any, Dict, List, Optional  # Type annotations

# ---- Logging configuration ----
# WARNING level: only log warnings and errors to reduce log noise during normal operation
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---- API constants ----
BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"
HEADERS = {"User-Agent": "ECOMATS-ChEMBL-Tool/1.0"}

# ---- Request rate control ----
# Key-free public API, polite rate limiting: minimum 0.4 s between requests (>= 0.3 s required)
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.4
_MAX_RETRIES = 3  # 1 initial attempt + 2 retries, then return None


def _get(endpoint: str, params: Optional[Dict[str, Any]] = None,
         timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    Send a GET request (with rate limiting and retries) — the low-level method
    for all ChEMBL API calls.

    Retry policy: exponential backoff + random jitter on network errors/5xx,
    at most 2 retries. 404 is treated as a "miss" and returns None (no retry).

    Args:
        endpoint: API endpoint path (appended to base_url, e.g. "molecule.json")
        params: query parameter dict
        timeout: request timeout in seconds, default 20 s

    Returns:
        Dict: parsed JSON dict from the API response; None on miss or when all
        retries fail
    """
    global _last_request_time

    # ---- Request rate control ----
    # Compute the time since the last request; if too short, wait until the
    # minimum interval is satisfied
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    for attempt in range(_MAX_RETRIES):
        try:
            url = f"{BASE_URL}/{endpoint}"
            logger.debug(f"Requesting ChEMBL API: {url} params={params}")

            _last_request_time = time.time()
            response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)

            # ---- 4xx: client error (including 404 miss, 400 invalid params), no retry ----
            if 400 <= response.status_code < 500:
                return None

            # ---- 5xx error: server busy, retry ----
            if response.status_code >= 500:
                logger.warning(f"ChEMBL server error {response.status_code} "
                               f"(attempt {attempt + 1}/{_MAX_RETRIES})")
                if attempt < _MAX_RETRIES - 1:
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    time.sleep(delay)
                    continue
                return None

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.warning(f"ChEMBL request failed (attempt {attempt + 1}/{_MAX_RETRIES}): {e}")
            if attempt < _MAX_RETRIES - 1:
                delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                time.sleep(delay)
            else:
                logger.error(f"ChEMBL request finally failed: {e}")
                return None
        except Exception as e:
            logger.error(f"Error processing ChEMBL response: {e}")
            return None
    return None


def _molecule_summary(m: Dict[str, Any]) -> Dict[str, Any]:
    """Extract summary fields from a ChEMBL molecule record."""
    structures = m.get("molecule_structures") or {}
    return {
        "chembl_id": m.get("molecule_chembl_id"),
        "pref_name": m.get("pref_name"),
        "smiles": structures.get("canonical_smiles"),
        "max_phase": m.get("max_phase"),
    }


def search_molecule(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Search small molecules by name.

    Searches pref_name and synonyms (both case-insensitive exact matches);
    results are merged and deduplicated. The bare `q` parameter is not used
    as a fallback — its semantics proved unreliable in practice (querying
    "donepezil" returns structural analogs rather than the compound itself);
    a verification tool should rather miss than mislead.

    Args:
        query: compound name, e.g. "donepezil"
        limit: maximum number of results, default 5

    Returns:
        List: [{"chembl_id", "pref_name", "smiles", "max_phase"}, ...];
              [] on miss or failure
    """
    if not query or not query.strip():
        return []
    q = query.strip()

    seen = set()
    out = []

    def _collect(params):
        data = _get("molecule.json", params=params)
        for m in (data or {}).get("molecules") or []:
            cid = m.get("molecule_chembl_id")
            if cid and cid not in seen:
                seen.add(cid)
                out.append(_molecule_summary(m))

    _collect({"pref_name__iexact": q, "limit": limit})
    _collect({"molecule_synonyms__molecule_synonym__iexact": q, "limit": limit})

    return out[:limit]


def molecule_by_smiles(smiles: str) -> Optional[Dict[str, Any]]:
    """
    Look up a compound by SMILES structure: first try exact match, then
    flexmatch (flexible match, ignoring stereochemistry/tautomerism
    differences).

    Used to verify whether the SMILES given by an agent corresponds to a
    known ChEMBL compound.

    Args:
        smiles: canonical SMILES string

    Returns:
        Dict: {"chembl_id", "pref_name", "smiles", "max_phase", "match_type"}
              match_type in {"exact", "flexmatch"}; None on miss or failure
    """
    if not smiles or not smiles.strip():
        return None
    s = smiles.strip()

    # SMILES contains special characters like ()=# and must be URL-encoded
    # before being used in path-parameter-style filtering
    encoded = quote(s, safe="")

    # ---- Step 1: exact structure match ----
    data = _get("molecule.json",
                params={"molecule_structures__canonical_smiles__exact": encoded,
                        "limit": 1})
    molecules = (data or {}).get("molecules") or []
    if molecules:
        result = _molecule_summary(molecules[0])
        result["match_type"] = "exact"
        return result

    # ---- Step 2: flexmatch flexible structure match ----
    data = _get("molecule.json",
                params={"molecule_structures__canonical_smiles__flexmatch": encoded,
                        "limit": 1})
    molecules = (data or {}).get("molecules") or []
    if molecules:
        result = _molecule_summary(molecules[0])
        result["match_type"] = "flexmatch"
        return result

    return None


def bioactivities_for_target(target_name: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Query bioactivity data (activity records) by target name.

    First searches the target resource by name and takes the target_chembl_id
    of the first hit, then queries the activity records for that target
    (standard activity type/value/pChEMBL value).

    Args:
        target_name: target name or gene symbol, e.g. "Acetylcholinesterase"
        limit: maximum number of results, default 10

    Returns:
        List: [{"target_chembl_id", "molecule_chembl_id", "standard_type",
                "standard_value", "standard_units", "pchembl_value"}, ...];
              [] on miss or failure
    """
    if not target_name or not target_name.strip():
        return []

    # ---- Step 1: resolve the target ID by name ----
    tdata = _get("target.json", params={"q": target_name.strip(), "limit": 1})
    targets = (tdata or {}).get("targets") or []
    if not targets:
        return []
    target_chembl_id = targets[0].get("target_chembl_id")
    if not target_chembl_id:
        return []

    # ---- Step 2: query activity records for that target ----
    adata = _get("activity.json",
                 params={"target_chembl_id": target_chembl_id, "limit": limit})
    activities = (adata or {}).get("activities") or []
    return [
        {
            "target_chembl_id": a.get("target_chembl_id"),
            "molecule_chembl_id": a.get("molecule_chembl_id"),
            "standard_type": a.get("standard_type"),
            "standard_value": a.get("standard_value"),
            "standard_units": a.get("standard_units"),
            "pchembl_value": a.get("pchembl_value"),
        }
        for a in activities
    ]


if __name__ == "__main__":
    # ---- Smoke test: real network queries for donepezil / AChE ----
    print("== search_molecule('donepezil') ==")
    hits = search_molecule("donepezil")
    for h in hits:
        print(h)
    assert any(h["chembl_id"] == "CHEMBL502" for h in hits), "CHEMBL502 not in results"

    print("\n== molecule_by_smiles(donepezil canonical SMILES) ==")
    # donepezil canonical SMILES (value from the ChEMBL record)
    smi = "COc1cc2c(cc1OC)C(=O)C(Cc3ccc(OC)c(OC)c3)C2"
    # Note: the above is an approximate structure; using the canonical SMILES
    # returned by ChEMBL is safer
    smi = hits[0]["smiles"] if hits and hits[0]["smiles"] else smi
    print(f"query SMILES: {smi}")
    hit = molecule_by_smiles(smi)
    print(hit)
    assert hit and hit["chembl_id"] == "CHEMBL502", "SMILES lookup did not hit CHEMBL502"

    print("\n== bioactivities_for_target('Acetylcholinesterase') (first 3) ==")
    acts = bioactivities_for_target("Acetylcholinesterase")
    for a in acts[:3]:
        print(a)

    print("\n== miss cases ==")
    print("bogus name:", search_molecule("notarealmolecule12345"))
    print("bogus smiles:", molecule_by_smiles("not_a_smiles"))
    print("\nSmoke test OK")
