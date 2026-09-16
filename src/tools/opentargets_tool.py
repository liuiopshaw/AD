#!/usr/bin/env python3
"""
Open Targets Platform query tool via GraphQL API.

Open Targets database query tool -- queries target-disease associations,
target tractability, and known drug evidence via the Open Targets Platform
GraphQL API. No API key required.

Endpoint: https://api.platform.opentargets.org/api/v4/graphql

All public functions follow a unified contract: return None or [] on
miss/network failure, never raise exceptions to the caller.
Style aligned with src/tools/pubchem_tool.py (synchronous requests +
polite rate limiting + retries).
"""

# ---- Standard library and third-party imports ----
import requests       # HTTP library, used to call the Open Targets GraphQL API
import logging        # Logging
import time           # Time handling, for request rate limiting and retry intervals
import random         # Random numbers, for adding jitter to retry delays (avoids thundering herd)
from typing import Any, Dict, List, Optional  # Type annotations

# ---- Logging configuration ----
# WARNING level: only log warnings and errors, reducing log noise during normal operation
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---- API constants ----
GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"
HEADERS = {
    "User-Agent": "ECOMATS-OpenTargets-Tool/1.0",
    "Content-Type": "application/json",
}

# ---- Request rate limiting ----
# Key-free public API; polite rate limit: minimum 0.4 s between requests (>= 0.3 s required)
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.4
_MAX_RETRIES = 3  # 1 initial attempt + 2 retries, then return None


def _graphql(query: str, variables: Optional[Dict[str, Any]] = None,
             timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    Send a GraphQL query (with rate limiting and retries) -- the low-level
    method for all Open Targets calls.

    Retry policy: exponential backoff + random jitter on network errors/5xx,
    up to 2 retries.

    Args:
        query: GraphQL query string
        variables: query variables dict
        timeout: request timeout in seconds, default 20

    Returns:
        Dict: the "data" field of the GraphQL response; None on failure or errors
    """
    global _last_request_time

    # ---- Request rate limiting ----
    # Compute time elapsed since the last request; wait if below the minimum interval
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    payload = {"query": query, "variables": variables or {}}

    for attempt in range(_MAX_RETRIES):
        try:
            _last_request_time = time.time()
            response = requests.post(GRAPHQL_URL, json=payload,
                                     headers=HEADERS, timeout=timeout)

            # ---- 5xx errors: server busy, retry ----
            if response.status_code >= 500:
                logger.warning(f"Open Targets server error {response.status_code} "
                               f"(attempt {attempt + 1}/{_MAX_RETRIES})")
                if attempt < _MAX_RETRIES - 1:
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    time.sleep(delay)
                    continue
                return None

            response.raise_for_status()
            body = response.json()

            # GraphQL-level errors (query syntax, nonexistent fields, etc.)
            # are not retried; fail immediately
            if body.get("errors"):
                logger.warning(f"Open Targets GraphQL errors: {body['errors']}")
                return None
            return body.get("data")

        except requests.exceptions.RequestException as e:
            logger.warning(f"Open Targets request failed (attempt {attempt + 1}/{_MAX_RETRIES}): {e}")
            if attempt < _MAX_RETRIES - 1:
                delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                time.sleep(delay)
            else:
                logger.error(f"Open Targets request finally failed: {e}")
                return None
        except Exception as e:
            logger.error(f"Error processing Open Targets response: {e}")
            return None
    return None


def _search_entity(name: str, entity: str) -> Optional[Dict[str, str]]:
    """
    Search an entity (disease or target) by name; return the first hit as {id, name}.

    Uses the Open Targets search query with entityNames to restrict the entity type.

    Args:
        name: entity name (e.g. "Alzheimer disease", "APOE")
        entity: entity type ("disease" or "target")

    Returns:
        Dict: {"id": ..., "name": ...}; None if no hit
    """
    query = """
    query searchEntity($q: String!, $entity: String!) {
      search(queryString: $q, entityNames: [$entity], page: {index: 0, size: 5}) {
        hits { id name entity }
      }
    }
    """
    data = _graphql(query, {"q": name, "entity": entity})
    hits = ((data or {}).get("search") or {}).get("hits") or []
    # Prefer exact match (case-insensitive); otherwise take the first hit
    for h in hits:
        if (h.get("name") or "").lower() == name.lower():
            return {"id": h.get("id"), "name": h.get("name")}
    if hits:
        return {"id": hits[0].get("id"), "name": hits[0].get("name")}
    return None


def get_disease_id(name: str) -> Optional[str]:
    """
    Look up the Open Targets disease ID by disease name
    (e.g. "Alzheimer disease" -> EFO id).

    Args:
        name: English disease name

    Returns:
        str: disease ID (e.g. "EFO_0000249"); None if no hit
    """
    if not name or not name.strip():
        return None
    hit = _search_entity(name.strip(), "disease")
    return hit["id"] if hit else None


def _get_target_ensembl_id(symbol: str) -> Optional[str]:
    """Search a target by gene symbol; return the Ensembl gene ID
    (e.g. APOE -> ENSG00000130203)."""
    hit = _search_entity(symbol.strip(), "target")
    return hit["id"] if hit else None


def target_disease_association(target_symbol: str,
                               disease_name: str = "Alzheimer disease") -> Optional[Dict[str, Any]]:
    """
    Query the target-disease association score.

    First resolves the disease ID, then filters the disease's associated
    targets list by gene symbol (BFilter text filter + exact approvedSymbol
    comparison).

    Args:
        target_symbol: gene symbol (e.g. "APOE")
        disease_name: English disease name, default "Alzheimer disease"

    Returns:
        Dict: {"target", "disease", "disease_id", "score", "datatype_scores"}
              datatype_scores is a {datatype_id: score} dict; None if no hit
    """
    if not target_symbol or not target_symbol.strip():
        return None
    symbol = target_symbol.strip()

    disease_id = get_disease_id(disease_name)
    if not disease_id:
        logger.warning(f"Disease not found: {disease_name}")
        return None

    query = """
    query assocTargets($efoId: String!, $symbol: String!) {
      disease(efoId: $efoId) {
        id
        name
        associatedTargets(BFilter: $symbol, page: {index: 0, size: 10}) {
          rows {
            target { approvedSymbol approvedName }
            score
            datatypeScores { id score }
          }
        }
      }
    }
    """
    data = _graphql(query, {"efoId": disease_id, "symbol": symbol})
    disease = (data or {}).get("disease")
    if not disease:
        return None

    rows = (disease.get("associatedTargets") or {}).get("rows") or []
    for row in rows:
        t = row.get("target") or {}
        if (t.get("approvedSymbol") or "").upper() == symbol.upper():
            datatype_scores = {d["id"]: d["score"]
                               for d in (row.get("datatypeScores") or []) if d.get("id")}
            return {
                "target": t.get("approvedSymbol"),
                "target_name": t.get("approvedName"),
                "disease": disease.get("name"),
                "disease_id": disease.get("id"),
                "score": row.get("score"),
                "datatype_scores": datatype_scores,
            }
    return None


def target_tractability(target_symbol: str) -> Optional[List[Dict[str, Any]]]:
    """
    Query the target tractability assessment.

    First resolves the Ensembl ID by gene symbol, then fetches
    target.tractability (a list of label/value assessment entries per
    modality).

    Args:
        target_symbol: gene symbol (e.g. "APOE")

    Returns:
        List: [{"modality": ..., "label": ..., "value": bool}, ...];
              None if no hit
    """
    if not target_symbol or not target_symbol.strip():
        return None
    ensembl_id = _get_target_ensembl_id(target_symbol.strip())
    if not ensembl_id:
        logger.warning(f"Target not found: {target_symbol}")
        return None

    query = """
    query tractability($ensgId: String!) {
      target(ensemblId: $ensgId) {
        id
        approvedSymbol
        tractability { modality label value }
      }
    }
    """
    data = _graphql(query, {"ensgId": ensembl_id})
    target = (data or {}).get("target")
    if not target:
        return None
    return target.get("tractability") or []


def known_drugs(target_symbol: str,
                disease_name: str = "Alzheimer disease") -> Optional[List[Dict[str, Any]]]:
    """
    Query known drug evidence targeting a given target for a disease.

    Note: the current Open Targets API (2025 rewrite) removed the legacy
    `knownDrugs` field. Here we instead query the disease's
    drugAndClinicalCandidates (all rows), then filter client-side by drug
    mechanism of action (mechanismsOfAction.targets.approvedSymbol) to keep
    only drugs acting on the specified target.

    Args:
        target_symbol: gene symbol (e.g. "ACHE")
        disease_name: English disease name, default "Alzheimer disease"

    Returns:
        List: [{"drug", "drug_id", "drug_type", "max_clinical_stage",
                "mechanism_of_action"}, ...]; None if the disease is not
              found; [] if the disease exists but the target has no drug evidence
    """
    if not target_symbol or not target_symbol.strip():
        return None
    symbol = target_symbol.strip().upper()

    disease_id = get_disease_id(disease_name)
    if not disease_id:
        logger.warning(f"Disease not found: {disease_name}")
        return None

    query = """
    query knownDrugs($efoId: String!) {
      disease(efoId: $efoId) {
        id
        name
        drugAndClinicalCandidates {
          count
          rows {
            maxClinicalStage
            drug {
              id
              name
              drugType
              mechanismsOfAction {
                rows { mechanismOfAction targets { approvedSymbol } }
              }
            }
          }
        }
      }
    }
    """
    data = _graphql(query, {"efoId": disease_id}, timeout=30)
    disease = (data or {}).get("disease")
    if not disease:
        return None

    rows = (disease.get("drugAndClinicalCandidates") or {}).get("rows") or []
    out = []
    for row in rows:
        drug = row.get("drug") or {}
        # ---- Filter by target symbol in the mechanism of action ----
        moa_hit = None
        for moa in ((drug.get("mechanismsOfAction") or {}).get("rows") or []):
            for t in moa.get("targets") or []:
                if (t.get("approvedSymbol") or "").upper() == symbol:
                    moa_hit = moa.get("mechanismOfAction")
                    break
            if moa_hit:
                break
        if not moa_hit:
            continue
        out.append({
            "drug": drug.get("name"),
            "drug_id": drug.get("id"),
            "drug_type": drug.get("drugType"),
            "max_clinical_stage": row.get("maxClinicalStage"),
            "mechanism_of_action": moa_hit,
        })
    return out


if __name__ == "__main__":
    # ---- Smoke test: live network queries for Alzheimer disease data ----
    print("== get_disease_id('Alzheimer disease') ==")
    efo = get_disease_id("Alzheimer disease")
    print(efo)

    print("\n== target_disease_association('APOE') ==")
    assoc = target_disease_association("APOE")
    print(assoc)
    assert assoc and assoc["score"] and assoc["score"] > 0.5, \
        "APOE-Alzheimer association missing or score <= 0.5"

    print("\n== target_tractability('APOE') (first 5) ==")
    tract = target_tractability("APOE")
    print((tract or [])[:5])

    print("\n== known_drugs('ACHE') -- Alzheimer clinical drugs ==")
    drugs = known_drugs("ACHE")
    print(drugs)
    assert drugs is not None, "known_drugs query failed"
    assert any((d.get("drug") or "").startswith("DONEPEZIL") for d in drugs), \
        "donepezil not found among ACHE drugs for Alzheimer disease"

    print("\n== miss cases ==")
    print("bogus disease:", target_disease_association("APOE", "Not a real disease 12345"))
    print("bogus target:", target_tractability("NOTAREALGENE123"))
    print("\nSmoke test OK")
