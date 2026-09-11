#!/usr/bin/env python3
"""
Open Targets Platform query tool via GraphQL API.

Open Targets 数据库查询工具 —— 通过 Open Targets Platform GraphQL API 查询
靶点-疾病关联、靶点可成药性 (tractability) 与已知药物证据。免 API key。

Endpoint: https://api.platform.opentargets.org/api/v4/graphql

所有公开函数遵循统一契约：未命中/网络失败返回 None 或 []，不向调用方抛异常。
风格对齐 src/tools/pubchem_tool.py（同步 requests + 礼貌限速 + 重试）。
"""

# ---- 标准库与第三方库导入 ----
import requests       # HTTP 请求库，用于调用 Open Targets GraphQL API
import logging        # 日志记录
import time           # 时间处理，用于请求频率控制和重试间隔
import random         # 随机数，用于重试时增加随机延迟（避免惊群效应）
from typing import Any, Dict, List, Optional  # 类型注解

# ---- 日志配置 ----
# WARNING 级别：只记录警告和错误，减少正常运行时的日志噪音
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---- API 常量 ----
GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"
HEADERS = {
    "User-Agent": "ECOMATS-OpenTargets-Tool/1.0",
    "Content-Type": "application/json",
}

# ---- 请求频率控制 ----
# 免 key 公共 API，礼貌限速：每次请求最小间隔 0.4 秒（>= 0.3s 要求）
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.4
_MAX_RETRIES = 3  # 1 次首发 + 2 次重试，之后返回 None


def _graphql(query: str, variables: Optional[Dict[str, Any]] = None,
             timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    发送 GraphQL 查询（带限速与重试）—— 所有 Open Targets 调用的底层方法。

    重试策略：网络异常/5xx 时指数退避 + 随机 jitter，最多重试 2 次。

    Args:
        query: GraphQL 查询字符串
        variables: 查询变量字典
        timeout: 请求超时时间（秒），默认 20 秒

    Returns:
        Dict: GraphQL 响应的 "data" 字段；失败或含 errors 时返回 None
    """
    global _last_request_time

    # ---- 请求频率控制 ----
    # 计算距离上次请求的时间差，不足则等待到满足最小间隔
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    payload = {"query": query, "variables": variables or {}}

    for attempt in range(_MAX_RETRIES):
        try:
            _last_request_time = time.time()
            response = requests.post(GRAPHQL_URL, json=payload,
                                     headers=HEADERS, timeout=timeout)

            # ---- 5xx 错误：服务器繁忙，重试 ----
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

            # GraphQL 层面错误（查询语法、字段不存在等）不重试，直接失败
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
    按名称搜索实体（disease 或 target），返回第一个命中的 {id, name}。

    使用 Open Targets 的 search 查询，entityNames 限定实体类别。

    Args:
        name: 实体名称（如 "Alzheimer disease"、"APOE"）
        entity: 实体类别（"disease" 或 "target"）

    Returns:
        Dict: {"id": ..., "name": ...}；未命中返回 None
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
    # 优先完全匹配（大小写不敏感），否则取第一个命中
    for h in hits:
        if (h.get("name") or "").lower() == name.lower():
            return {"id": h.get("id"), "name": h.get("name")}
    if hits:
        return {"id": hits[0].get("id"), "name": hits[0].get("name")}
    return None


def get_disease_id(name: str) -> Optional[str]:
    """
    按疾病名称查询 Open Targets 疾病 ID（如 "Alzheimer disease" -> EFO id）。

    Args:
        name: 疾病英文名称

    Returns:
        str: 疾病 ID（如 "EFO_0000249"）；未命中返回 None
    """
    if not name or not name.strip():
        return None
    hit = _search_entity(name.strip(), "disease")
    return hit["id"] if hit else None


def _get_target_ensembl_id(symbol: str) -> Optional[str]:
    """按基因符号搜索靶点，返回 Ensembl gene ID（如 APOE -> ENSG00000130203）。"""
    hit = _search_entity(symbol.strip(), "target")
    return hit["id"] if hit else None


def target_disease_association(target_symbol: str,
                               disease_name: str = "Alzheimer disease") -> Optional[Dict[str, Any]]:
    """
    查询靶点-疾病关联评分。

    先解析疾病 ID，再在该疾病的关联靶点列表中按基因符号过滤
    （BFilter 文本过滤 + approvedSymbol 精确比对）。

    Args:
        target_symbol: 基因符号（如 "APOE"）
        disease_name: 疾病英文名称，默认 "Alzheimer disease"

    Returns:
        Dict: {"target", "disease", "disease_id", "score", "datatype_scores"}
              datatype_scores 为 {datatype_id: score} 字典；未命中返回 None
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
    查询靶点可成药性（tractability）评估。

    先按基因符号解析 Ensembl ID，再取 target.tractability
    （各 modality 下 label/value 的评估条目列表）。

    Args:
        target_symbol: 基因符号（如 "APOE"）

    Returns:
        List: [{"modality": ..., "label": ..., "value": bool}, ...]；
              未命中返回 None
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
    查询某疾病下针对指定靶点的已知药物证据。

    注意：Open Targets 现行 API（2025 重写版）已移除旧 `knownDrugs` 字段。
    这里改查疾病的 drugAndClinicalCandidates（全量行），再按药物作用机制
    （mechanismsOfAction.targets.approvedSymbol）在客户端过滤出作用于
    指定靶点的药物。

    Args:
        target_symbol: 基因符号（如 "ACHE"）
        disease_name: 疾病英文名称，默认 "Alzheimer disease"

    Returns:
        List: [{"drug", "drug_id", "drug_type", "max_clinical_stage",
                "mechanism_of_action"}, ...]；疾病未找到返回 None，
              疾病存在但该靶点无药物证据返回 []
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
        # ---- 按作用机制中的靶点符号过滤 ----
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
    # ---- 冒烟测试：真实网络查询 Alzheimer disease 相关数据 ----
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

    print("\n== known_drugs('ACHE') — Alzheimer 临床药物 ==")
    drugs = known_drugs("ACHE")
    print(drugs)
    assert drugs is not None, "known_drugs query failed"
    assert any((d.get("drug") or "").startswith("DONEPEZIL") for d in drugs), \
        "donepezil not found among ACHE drugs for Alzheimer disease"

    print("\n== miss cases ==")
    print("bogus disease:", target_disease_association("APOE", "Not a real disease 12345"))
    print("bogus target:", target_tractability("NOTAREALGENE123"))
    print("\nSmoke test OK")
