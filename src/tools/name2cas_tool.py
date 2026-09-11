#!/usr/bin/env python3
"""
Compound Name to CAS Number Tool.
Convert compound names to CAS numbers via PubChem API.

本模块实现化合物名称到 CAS 号的转换功能。
CAS 号（Chemical Abstracts Service Registry Number）是化学物质的全球唯一标识符，
每个 CAS 号对应一个特定的化学物质（包括其立体化学结构）。
"""

import logging
import requests
import time
import random
from typing import Dict, Any

# 配置日志：设置默认级别为 WARNING，避免过多的调试信息
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class NameToCASTool:
    """Compound Name to CAS Number Tool Class.

    通过 PubChem REST API（PUG）实现化合物名称到 CAS 号的转换。
    工作流程：
    1. 用化合物名称搜索 PubChem 获取 CID
    2. 用 CID 获取详细属性，从属性中的同义词列表提取 CAS 号
    """

    def __init__(self):
        """Initialize NameToCAS tool.

        初始化 HTTP 会话并设置请求头。
        使用 Session 对象可以复用 TCP 连接，提高多次请求的效率。
        """
        # PubChem PUG REST API 的基础 URL
        # PUG = Power User Gateway，是 PubChem 提供的 REST 风格编程接口
        self.base_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
        # 创建可复用的 HTTP 会话对象
        self.session = requests.Session()
        # 设置 User-Agent 头部，方便 PubChem 识别和追踪请求来源
        # 良好的 User-Agent 标识有助于 API 提供方进行使用统计和问题排查
        self.session.headers.update({
            "User-Agent": "ECOMATS-NameToCAS-Tool/1.0"
        })

    def _make_request(self, endpoint: str, timeout: int = 30, max_retries: int = 3) -> Dict[str, Any]:
        """
        Send API request with retry mechanism.
        发送 API 请求并内置重试机制。
        当网络请求失败时，使用指数退避（exponential backoff）策略自动重试，
        这是处理网络不稳定的标准做法。

        Args:
            endpoint: API endpoint (full URL)
            timeout: 超时时间（秒），默认 30 秒
            max_retries: 最大重试次数，默认 3 次

        Returns:
            API 响应数据字典，如果所有重试都失败则返回 {"error": ...}
        """
        for attempt in range(max_retries):
            try:
                # 发送 GET 请求，设置超时防止无限等待
                response = self.session.get(endpoint, timeout=timeout)
                # raise_for_status() 会在 HTTP 状态码为 4xx/5xx 时抛出异常
                response.raise_for_status()
                # 解析并返回 JSON 响应
                return response.json()
            except requests.exceptions.RequestException as e:
                # 记录警告日志，包含当前重试次数
                logger.warning(f"API请求失败（第 {attempt + 1}/{max_retries} 次尝试）: {e}")
                if attempt < max_retries - 1:  # 不是最后一次尝试，继续重试
                    # 指数退避策略：
                    # 第 1 次重试：等待 1-2 秒（2^0 + 随机 0-1 秒）
                    # 第 2 次重试：等待 2-3 秒（2^1 + 随机 0-1 秒）
                    # 第 3 次重试：等待 4-5 秒（2^2 + 随机 0-1 秒）
                    # 随机延迟可以避免多个并发请求同时重试导致的"惊群效应"
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    logger.info(f"等待 {delay:.2f} 秒后重试")
                    time.sleep(delay)
                else:
                    # 所有重试都失败，记录最终错误
                    logger.error(f"API请求最终失败: {e}")
                    return {"error": str(e)}

    def convert_name_to_cas(self, compound_name: str) -> Dict[str, Any]:
        """
        Convert chemical name to CAS number.
        将化学品名称转换为 CAS 号。

        转换流程：
        1. 用名称搜索 PubChem → 获得 Compound ID (CID)
        2. 用 CID 查询详细属性 → 从同义词列表中提取 CAS 号

        Args:
            compound_name (str): 化学物质名称
                                支持 IUPAC 命名、通用名、商品名等多种格式
                                例如 "aspirin"、"acetylsalicylic acid"、"2-acetoxybenzoic acid"

        Returns:
            Dict[str, Any]: 包含 CAS 号和其他相关信息的字典
                            success=True 时包含：compound_name, cid, cas_number,
                            iupac_name, molecular_formula, molecular_weight, synonyms
                            success=False 时包含 error 信息
        """
        try:
            # 第一步：使用 PubChem API 的名称搜索接口获取化合物 CID
            # PUG API 格式：/compound/name/{名称}/cids/JSON
            # 返回该名称对应的所有候选 CID 列表
            endpoint = f"{self.base_url}/compound/name/{compound_name}/cids/JSON"
            result = self._make_request(endpoint)

            # 第二步：从搜索结果中提取 CID
            # IdentifierList.CID 包含了 PubChem 内部数据库中找到的化合物 ID
            if "IdentifierList" in result and "CID" in result["IdentifierList"]:
                cids = result["IdentifierList"]["CID"]
                # CID 可能是单个整数或整数列表
                # 如果名称匹配到多个化合物，取第一个（通常是最佳匹配）
                if isinstance(cids, list):
                    cid = cids[0]
                else:
                    cid = cids

                # 第三步：使用 CID 获取详细属性和同义词列表
                # 注意：PubChem 的 property 接口不支持 CAS/Synonyms 属性
                # （请求会返回 400），CAS 号需通过 /synonyms/JSON 端点获取，
                # 再从同义词列表中按 CAS 格式过滤提取
                prop_endpoint = f"{self.base_url}/compound/cid/{cid}/property/IUPACName,MolecularFormula,MolecularWeight/JSON"
                details = self._make_request(prop_endpoint)
                synonyms_endpoint = f"{self.base_url}/compound/cid/{cid}/synonyms/JSON"
                synonyms_data = self._make_request(synonyms_endpoint)

                # 解析同义词列表（CAS 号藏于其中，格式如 50-78-2）
                synonyms = []
                if "InformationList" in synonyms_data and "Information" in synonyms_data["InformationList"]:
                    info_list = synonyms_data["InformationList"]["Information"]
                    if info_list:
                        synonyms = info_list[0].get("Synonym", [])

                # 第四步：从返回的详细属性中提取所需信息
                if "PropertyTable" in details and "Properties" in details["PropertyTable"]:
                    properties = details["PropertyTable"]["Properties"][0]
                    # 在同义词列表中搜索符合 CAS 格式的字符串
                    # CAS 格式：最多7位数字-2位数字-1位校验数字，如 50-78-2
                    cas_numbers = [syn for syn in synonyms if self._is_cas_number(syn)]
                    # 取第一个匹配的 CAS 号，如果找不到则返回 "N/A"
                    cas_number = cas_numbers[0] if cas_numbers else "N/A"

                    return {
                        "success": True,
                        "compound_name": compound_name,
                        "cid": cid,  # PubChem 化合物 ID
                        "cas_number": cas_number,
                        "iupac_name": properties.get("IUPACName", ""),
                        "molecular_formula": properties.get("MolecularFormula", ""),
                        "molecular_weight": properties.get("MolecularWeight", ""),
                        "synonyms": synonyms  # 完整的同义词列表
                    }
                else:
                    # PubChem 中存在该化合物但没有详细属性数据
                    return {
                        "success": False,
                        "compound_name": compound_name,
                        "error": "未找到该化合物的详细信息",
                        "details": details.get("error", "未知错误")
                    }
            else:
                # PubChem 中未找到该名称对应的化合物
                return {
                    "success": False,
                    "compound_name": compound_name,
                    "error": "未找到该化合物的CAS号信息",
                    "details": result.get("error", "未知错误")
                }

        except Exception as e:
            # 捕获所有未预期的异常，确保工具不会因例外情况而崩溃
            logger.error(f"化学品名称转CAS号时出错: {e}")
            return {
                "success": False,
                "compound_name": compound_name,
                "error": f"转换失败: {str(e)}"
            }

    def _is_cas_number(self, text: str) -> bool:
        """
        Determine if text is in CAS number format.
        判断文本是否为合法的 CAS 号格式。

        CAS 号的格式：
        - 由三个部分组成，用连字符 "-" 分隔
        - 第一部分：2-7 位数字
        - 第二部分：2 位数字
        - 第三部分：1 位数字（校验位）
        - 完整格式如：50-78-2（阿司匹林）、7440-02-0（镍）

        注意：这里只做格式验证，不验证校验位是否正确。

        Args:
            text: 待检查的文本

        Returns:
            bool: 是否符合 CAS 号格式
        """
        import re
        # CAS 号的正则表达式：
        # ^\d{2,7}  - 以 2-7 位数字开头
        # -\d{2}    - 连字符后跟 2 位数字
        # -\d$      - 连字符后跟 1 位数字，行尾
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'
        # re.match 从字符串开头匹配，匹配成功返回 match 对象，失败返回 None
        return bool(re.match(cas_pattern, text))

# 全局实例变量（单例模式）
# 使用模块级别的变量保存 NameToCASTool 的唯一实例
# Python 的模块导入是线程安全的，因此这种单例模式在多线程环境下也是安全的
_name2cas_tool = None

def get_name2cas_tool() -> NameToCASTool:
    """
    Get Name2CAS tool instance.
    获取 NameToCAS 工具实例（单例模式）。

    使用惰性初始化（Lazy Initialization）：
    - 首次调用时创建实例，后续调用复用同一实例
    - 避免了不必要的资源消耗（HTTP Session 等）
    - 确保全局状态一致性

    Returns:
        NameToCASTool: NameToCAS 工具的单例实例
    """
    global _name2cas_tool
    # 仅在实例为 None 时创建新实例（惰性初始化）
    if _name2cas_tool is None:
        _name2cas_tool = NameToCASTool()
    return _name2cas_tool
