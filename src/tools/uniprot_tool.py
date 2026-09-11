#!/usr/bin/env python3
"""
UniProt database query tool via REST API.

UniProt 数据库查询工具 —— 通过 UniProtKB REST API 校验蛋白 accession、
按基因名搜索蛋白条目。免 API key。

Base URL: https://rest.uniprot.org/uniprotkb

所有公开函数遵循统一契约：未命中/网络失败返回 None 或 []，不向调用方抛异常。
风格对齐 src/tools/pubchem_tool.py（同步 requests + 礼貌限速 + 重试）。
"""

# ---- 标准库与第三方库导入 ----
import requests       # HTTP 请求库，用于调用 UniProt REST API
import logging        # 日志记录
import time           # 时间处理，用于请求频率控制和重试间隔
import random         # 随机数，用于重试时增加随机延迟（避免惊群效应）
from typing import Any, Dict, List, Optional  # 类型注解

# ---- 日志配置 ----
# WARNING 级别：只记录警告和错误，减少正常运行时的日志噪音
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---- API 常量 ----
BASE_URL = "https://rest.uniprot.org/uniprotkb"
HEADERS = {"User-Agent": "ECOMATS-UniProt-Tool/1.0"}

# ---- 请求频率控制 ----
# 免 key 公共 API，礼貌限速：每次请求最小间隔 0.4 秒（>= 0.3s 要求）
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.4
_MAX_RETRIES = 3  # 1 次首发 + 2 次重试，之后返回 None


def _get(url: str, params: Optional[Dict[str, Any]] = None,
         timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    发送 GET 请求（带限速与重试）—— 所有 UniProt API 调用的底层方法。

    重试策略：网络异常/5xx 时指数退避 + 随机 jitter，最多重试 2 次。
    404 视为"未命中"，返回 None（不重试）。

    Args:
        url: 完整 URL
        params: 查询参数字典
        timeout: 请求超时时间（秒），默认 20 秒

    Returns:
        Dict: API 返回的 JSON 解析字典；未命中或全部重试失败返回 None
    """
    global _last_request_time

    # ---- 请求频率控制 ----
    # 计算距离上次请求的时间差，不足则等待到满足最小间隔
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    for attempt in range(_MAX_RETRIES):
        try:
            logger.debug(f"Requesting UniProt API: {url} params={params}")

            _last_request_time = time.time()
            response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)

            # ---- 4xx：客户端错误（含 404 未命中、400 非法参数），不重试 ----
            if 400 <= response.status_code < 500:
                return None

            # ---- 5xx 错误：服务器繁忙，重试 ----
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
    """从 UniProtKB entry 记录中提取摘要字段。"""
    # 蛋白名：优先 recommendedName.fullName，其次 submittedNames 第一个
    protein_name = None
    desc = entry.get("proteinDescription") or {}
    rec = (desc.get("recommendedName") or {}).get("fullName") or {}
    protein_name = rec.get("value")
    if not protein_name:
        submitted = desc.get("submittedNames") or []
        if submitted:
            protein_name = ((submitted[0].get("fullName") or {}).get("value"))

    # 基因名：取第一个基因的 geneName
    gene = None
    genes = entry.get("genes") or []
    if genes:
        gene = ((genes[0].get("geneName") or {}).get("value"))

    # 功能注释：commentType == FUNCTION 的第一条
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
    按 accession 获取 UniProtKB 条目（同时校验 accession 是否存在）。

    Args:
        accession: UniProt accession，如 "P05067"（APP）

    Returns:
        Dict: {"accession", "protein_name", "gene", "organism",
               "function_comment"}；accession 不存在或失败返回 None
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
    按基因名搜索 UniProtKB 条目（默认限定人源、reviewed/Swiss-Prot）。

    Args:
        gene: 基因符号，如 "APP"
        organism: 物种学名，默认 "Homo sapiens"
        limit: 最多返回条数，默认 5

    Returns:
        List: entry 摘要字典列表（结构同 get_entry）；未命中或失败返回 []
    """
    if not gene or not gene.strip():
        return []
    query = f'gene:{gene.strip()} AND organism_name:"{organism}" AND reviewed:true'
    data = _get(f"{BASE_URL}/search",
                params={"query": query, "format": "json", "size": limit})
    results = (data or {}).get("results") or []
    return [_entry_summary(e) for e in results]


if __name__ == "__main__":
    # ---- 冒烟测试：真实网络查询 APP (P05067) ----
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
