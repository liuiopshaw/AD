#!/usr/bin/env python3
"""
ChEMBL database query tool via REST API.

ChEMBL 数据库查询工具 —— 通过 ChEMBL REST API 查询小分子药物/化合物信息、
按 SMILES 精确/柔性结构检索、按靶点查生物活性数据。免 API key。

Base URL: https://www.ebi.ac.uk/chembl/api/data (JSON 格式)

所有公开函数遵循统一契约：未命中/网络失败返回 None 或 []，不向调用方抛异常。
风格对齐 src/tools/pubchem_tool.py（同步 requests + 礼貌限速 + 重试）。
"""

# ---- 标准库与第三方库导入 ----
import requests                  # HTTP 请求库，用于调用 ChEMBL REST API
import logging                   # 日志记录
import time                      # 时间处理，用于请求频率控制和重试间隔
import random                    # 随机数，用于重试时增加随机延迟（避免惊群效应）
from urllib.parse import quote   # URL 编码（SMILES 含特殊字符，必须编码）
from typing import Any, Dict, List, Optional  # 类型注解

# ---- 日志配置 ----
# WARNING 级别：只记录警告和错误，减少正常运行时的日志噪音
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---- API 常量 ----
BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"
HEADERS = {"User-Agent": "ECOMATS-ChEMBL-Tool/1.0"}

# ---- 请求频率控制 ----
# 免 key 公共 API，礼貌限速：每次请求最小间隔 0.4 秒（>= 0.3s 要求）
_last_request_time = 0.0
_MIN_REQUEST_INTERVAL = 0.4
_MAX_RETRIES = 3  # 1 次首发 + 2 次重试，之后返回 None


def _get(endpoint: str, params: Optional[Dict[str, Any]] = None,
         timeout: int = 20) -> Optional[Dict[str, Any]]:
    """
    发送 GET 请求（带限速与重试）—— 所有 ChEMBL API 调用的底层方法。

    重试策略：网络异常/5xx 时指数退避 + 随机 jitter，最多重试 2 次。
    404 视为"未命中"，返回 None（不重试）。

    Args:
        endpoint: API 端点路径（追加到 base_url 后面，如 "molecule.json"）
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
            url = f"{BASE_URL}/{endpoint}"
            logger.debug(f"Requesting ChEMBL API: {url} params={params}")

            _last_request_time = time.time()
            response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)

            # ---- 4xx：客户端错误（含 404 未命中、400 非法参数），不重试 ----
            if 400 <= response.status_code < 500:
                return None

            # ---- 5xx 错误：服务器繁忙，重试 ----
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
    """从 ChEMBL molecule 记录中提取摘要字段。"""
    structures = m.get("molecule_structures") or {}
    return {
        "chembl_id": m.get("molecule_chembl_id"),
        "pref_name": m.get("pref_name"),
        "smiles": structures.get("canonical_smiles"),
        "max_phase": m.get("max_phase"),
    }


def search_molecule(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    按名称搜索小分子。

    检索 pref_name 与同义词（均大小写不敏感精确匹配），结果合并去重。
    不用裸 `q` 参数做兜底——实测其语义不可靠（查 "donepezil" 返回结构
    相似物而非本体），查证工具宁缺毋滥。

    Args:
        query: 化合物名称，如 "donepezil"
        limit: 最多返回条数，默认 5

    Returns:
        List: [{"chembl_id", "pref_name", "smiles", "max_phase"}, ...]；
              未命中或失败返回 []
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
    按 SMILES 结构检索化合物：先 exact 精确匹配，失败后 flexmatch
    （柔性匹配，忽略立体化学/互变异构差异）。

    用于验证 agent 给出的 SMILES 是否对应 ChEMBL 已知化合物。

    Args:
        smiles: canonical SMILES 字符串

    Returns:
        Dict: {"chembl_id", "pref_name", "smiles", "max_phase", "match_type"}
              match_type ∈ {"exact", "flexmatch"}；未命中或失败返回 None
    """
    if not smiles or not smiles.strip():
        return None
    s = smiles.strip()

    # SMILES 含 ()=# 等特殊字符，必须 URL 编码后走路径参数式过滤
    encoded = quote(s, safe="")

    # ---- 第一步：exact 精确结构匹配 ----
    data = _get("molecule.json",
                params={"molecule_structures__canonical_smiles__exact": encoded,
                        "limit": 1})
    molecules = (data or {}).get("molecules") or []
    if molecules:
        result = _molecule_summary(molecules[0])
        result["match_type"] = "exact"
        return result

    # ---- 第二步：flexmatch 柔性结构匹配 ----
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
    按靶点名称查询生物活性数据（activity 记录）。

    先在 target 资源中按名称检索取第一个命中的 target_chembl_id，
    再查该靶点的 activity 记录（标准活性类型/数值/pChEMBL 值）。

    Args:
        target_name: 靶点名称或基因符号，如 "Acetylcholinesterase"
        limit: 最多返回条数，默认 10

    Returns:
        List: [{"target_chembl_id", "molecule_chembl_id", "standard_type",
                "standard_value", "standard_units", "pchembl_value"}, ...]；
              未命中或失败返回 []
    """
    if not target_name or not target_name.strip():
        return []

    # ---- 第一步：按名称解析靶点 ID ----
    tdata = _get("target.json", params={"q": target_name.strip(), "limit": 1})
    targets = (tdata or {}).get("targets") or []
    if not targets:
        return []
    target_chembl_id = targets[0].get("target_chembl_id")
    if not target_chembl_id:
        return []

    # ---- 第二步：查该靶点的活性记录 ----
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
    # ---- 冒烟测试：真实网络查询 donepezil / AChE ----
    print("== search_molecule('donepezil') ==")
    hits = search_molecule("donepezil")
    for h in hits:
        print(h)
    assert any(h["chembl_id"] == "CHEMBL502" for h in hits), "CHEMBL502 not in results"

    print("\n== molecule_by_smiles(donepezil canonical SMILES) ==")
    # donepezil canonical SMILES（ChEMBL 记录值）
    smi = "COc1cc2c(cc1OC)C(=O)C(Cc3ccc(OC)c(OC)c3)C2"
    # 注：上面是近似结构，直接用 ChEMBL 返回的 canonical SMILES 更稳妥
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
