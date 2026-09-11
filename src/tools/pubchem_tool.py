#!/usr/bin/env python3
"""
PubChem database query tool via REST API.

PubChem 数据库查询工具 —— 通过 PubChem REST API (PUG-REST) 查询化合物信息。
支持按名称、分子式、CID、InChIKey 等多种方式检索有机化合物的物化性质。
"""

# ---- 标准库与第三方库导入 ----
import requests       # HTTP 请求库，用于调用 PubChem REST API
import logging        # 日志记录
import time           # 时间处理，用于请求频率控制和重试间隔
import random         # 随机数，用于重试时增加随机延迟（避免惊群效应）
import os             # 操作系统接口，用于读取环境变量
from typing import Dict, Any  # 类型注解

# ---- 日志配置 ----
# WARNING 级别：只记录警告和错误，减少正常运行时的日志噪音
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class PubChemTool:
    """
    PubChem 数据库查询工具 —— 封装 PubChem PUG-REST API 的所有查询方法。

    支持查询和验证的有机材料类型：
    1. 纯有机化合物 (Pure organic compounds)
    2. 生物基材料 (Bio-based materials)
    3. 碳基材料（部分）(Carbon-based materials)
    4. 其他含有机组分的材料 (Other materials containing organic components)

    使用 PubChem REST API (PUG-REST)：
    基础 URL: https://pubchem.ncbi.nlm.nih.gov/rest/pug
    """

    def __init__(self, api_key: str = None):
        """
        初始化 PubChem 工具。

        Args:
            api_key (str, optional): PubChem API 密钥。
                                      如果提供，可提高 API 调用频率限制。
                                      如果未提供，则从环境变量 PUBCHEM_API_KEY 读取。
        """
        # PubChem PUG-REST API 的基础地址
        self.base_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

        # API 密钥：优先参数传入，其次环境变量
        self.api_key = api_key or os.getenv('PUBCHEM_API_KEY')

        # ---- HTTP 请求头 ----
        # 设置 User-Agent 标识自己，符合 PubChem 使用规范
        self.headers = {
            "User-Agent": "ECOMATS-PubChem-Tool/1.0"
        }

        # 如果有 API Key，添加到请求头中（可提高请求频率上限）
        if self.api_key:
            self.headers["X-PubChem-API-Key"] = self.api_key

        # ---- 请求频率控制 ----
        # PubChem 对请求频率有限制，设置最小间隔以避免被限流/封禁
        self.last_request_time = 0             # 上次请求的时间戳
        self.min_request_interval = 1.0        # 最小请求间隔：1 秒（比默认更快，已有 API key 时允许）

    def _make_request(self, endpoint: str, timeout: int = 10, max_retries: int = 2) -> Dict[str, Any]:
        """
        发送 API 请求（带重试机制）—— 所有 PubChem API 调用的底层方法。

        重试策略：
        - 503 错误（服务器繁忙）：使用服务器返回的 Retry-After 延迟
        - 超时：固定 2 秒后重试
        - 其他请求异常：指数退避 + 随机 jitter 延迟

        Args:
            endpoint: API 端点路径（追加到 base_url 后面）
            timeout: 请求超时时间（秒），默认 10 秒
            max_retries: 最大重试次数，默认 2 次

        Returns:
            Dict: API 返回的 JSON 解析字典；如果全部重试失败，返回 {"error": ...}
        """
        # ---- 请求频率控制 ----
        # 计算距离上次请求的时间差，不足则等待到满足最小间隔
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last_request)

        for attempt in range(max_retries):
            try:
                # 构建完整的 API URL
                url = f"{self.base_url}/{endpoint}"
                logger.debug(f"Requesting PubChem API: {url}")

                # 更新最后请求时间（在发送请求前更新）
                self.last_request_time = time.time()

                # 发送 GET 请求
                response = requests.get(url, headers=self.headers, timeout=timeout)

                # ---- 503 错误特殊处理 ----
                # PubChem 服务器繁忙时会返回 503，并包含 Retry-After 头
                if response.status_code == 503:
                    retry_after = int(response.headers.get('Retry-After', 30))
                    logger.warning(f"PubChem server is busy, will retry after {retry_after} seconds")
                    if attempt < max_retries - 1:
                        logger.info(f"Waiting {retry_after} seconds before retry")
                        time.sleep(retry_after)
                        continue

                # 抛出 HTTP 错误异常（4xx/5xx，503 已在上面处理）
                response.raise_for_status()
                # 返回 JSON 解析结果
                return response.json()

            except requests.exceptions.Timeout:
                # ---- 超时处理 ----
                logger.warning(f"PubChem API request timeout (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    delay = 2  # 超时后等待 2 秒重试
                    logger.info(f"Waiting {delay} seconds before retry")
                    time.sleep(delay)
                else:
                    # 所有重试耗尽
                    logger.error(f"PubChem API request finally timed out")
                    return {"error": f"API request timeout: Please check network connection"}

            except requests.exceptions.RequestException as e:
                # ---- 其他请求异常 ----
                logger.warning(f"PubChem API request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:  # 不是最后一次尝试
                    # 指数退避 + 随机 jitter（1-3 秒随机延迟）
                    # 公式: 2^attempt + random(0, 1): 1s, 2-3s, ...
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    logger.info(f"Waiting {delay:.2f} seconds before retry")
                    time.sleep(delay)
                else:
                    logger.error(f"PubChem API request finally failed: {e}")
                    return {"error": f"API request failed: {str(e)}"}

            except Exception as e:
                # ---- 其他未知异常 ----
                logger.error(f"Error processing response: {e}")
                return {"error": f"Error processing response: {str(e)}"}

    # ============================================================================
    #  基础查询方法 —— 按不同标识符查询化合物属性
    # ============================================================================

    def get_basic_properties_by_name(self, compound_name: str) -> Dict[str, Any]:
        """
        按化合物名称查询基本物化性质。

        使用 PubChem API 的 compound/name/<name>/property/<properties>/JSON 端点。

        获取的属性包括：分子式、分子量、IUPAC名称、SMILES、InChI/InChIKey、
        XLogP（脂水分配系数）、氢键供体/受体数、可旋转键数、
        TPSA（拓扑极性表面积）、复杂度等。

        Args:
            compound_name: 化合物名称（英文），如 "caffeine"、"benzene"

        Returns:
            Dict: 化合物基本属性信息
        """
        # 构建 endpoint：一次请求获取所有关键属性
        endpoint = f"compound/name/{compound_name}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
        return self._make_request(endpoint, max_retries=3)

    def get_synonyms_with_cas(self, compound_name: str) -> Dict[str, Any]:
        """
        获取化合物同义词列表（包含 CAS 号）。

        CAS 号格式为 XXXXX-XX-X，可以从同义词列表中过滤提取。
        这是获取 CAS 号的主要方式，因为 PubChem 没有独立的 "CAS" 属性字段。

        Args:
            compound_name: 化合物名称

        Returns:
            Dict: 包含同义词列表的响应，其中可过滤出 CAS 号
        """
        endpoint = f"compound/name/{compound_name}/synonyms/JSON"
        return self._make_request(endpoint, max_retries=3)

    def get_properties_by_cid(self, cid: int) -> Dict[str, Any]:
        """
        按 PubChem CID（化合物唯一整数标识符）获取详细信息。

        当已经知道化合物的 CID 时，此方法比按名称查询更精确高效。

        Args:
            cid: PubChem 化合物 ID（正整数），如 2519（咖啡因）

        Returns:
            Dict: 化合物详细信息
        """
        endpoint = f"compound/cid/{cid}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
        return self._make_request(endpoint, max_retries=3)

    def search_by_molecular_formula(self, formula: str) -> Dict[str, Any]:
        """
        按分子式搜索化合物。

        使用 PubChem 的 fastformula 端点，该端点专为分子式搜索优化，
        比通用搜索更快。

        Args:
            formula: 化学分子式，如 "C8H10N4O2"（咖啡因）

        Returns:
            Dict: 匹配分子式的化合物列表及属性
        """
        endpoint = f"compound/fastformula/{formula}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
        return self._make_request(endpoint, max_retries=3)

    def search_by_inchikey(self, inchikey: str) -> Dict[str, Any]:
        """
        按 InChIKey 搜索化合物。

        InChIKey 是化合物的标准哈希标识符（27 字符），用于唯一标识化学结构。
        例如：RYYVLZVUVIJVGH-UHFFFAOYSA-N（咖啡因）

        Args:
            inchikey: InChIKey 标识符字符串

        Returns:
            Dict: 化合物信息
        """
        endpoint = f"compound/inchikey/{inchikey}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
        return self._make_request(endpoint, max_retries=3)

    # ============================================================================
    #  智能搜索 —— 自动识别查询类型并调用对应的端点
    # ============================================================================

    def search_compound(self, query: str, search_type: str = "auto") -> Dict[str, Any]:
        """
        智能化合物搜索 —— 自动判断查询类型并路由到合适的端点。

        当 search_type="auto" 时的判断逻辑：
        1. 如果是 InChIKey 格式（27 字符，含连字符）→ 使用 inchikey 端点
        2. 如果像分子式（含元素符号+数字） → 使用 fastformula 端点
        3. 否则 → 使用 name 端点

        Args:
            query: 查询内容（化合物名称、分子式或 InChIKey）
            search_type: 搜索类型（"auto": 自动, "name": 名称, "formula": 分子式, "inchikey": InChIKey）

        Returns:
            Dict: 化合物查询结果
        """
        if search_type == "auto":
            # 判断是否为 InChIKey 格式（27 个字符，至少 2 个连字符）
            if len(query) == 27 and query.count('-') >= 2:
                # 很可能是 InChIKey，使用 inchikey 端点查询
                return self.search_by_inchikey(query)
            # 判断是否为分子式格式（含元素符号和数字）
            elif self._is_molecular_formula(query):
                # 很可能是分子式，使用 fastformula 端点查询
                return self.search_by_molecular_formula(query)
            else:
                # 默认按化合物名称查询
                return self.get_basic_properties_by_name(query)
        elif search_type == "name":
            return self.get_basic_properties_by_name(query)
        elif search_type == "formula":
            return self.search_by_molecular_formula(query)
        elif search_type == "inchikey":
            return self.search_by_inchikey(query)
        else:
            return {"error": f"Unsupported search type: {search_type}"}

    def _is_molecular_formula(self, query: str) -> bool:
        """
        判断查询字符串是否为分子式格式。

        分子式特征：
        - 由元素符号（大写字母开头，可跟小写字母）和数字组成
        - 可能包含括号（如 Ca(OH)2）
        - 例如：H2O, C6H6, C12H22O11, Ca(OH)2, NaCl

        使用两个正则模式：
        - 模式1：纯元素-数字序列，如 NaCl, H2O, C6H12O6
        - 模式2：含括号的分子式，如 Ca(OH)2, Al2(SO4)3

        Args:
            query: 待判断的字符串

        Returns:
            bool: 是否看起来像分子式
        """
        import re
        # 模式1：纯元素符号+数字序列 —— 如 "NaCl", "H2O", "C6H12O6"
        # 模式2：含括号的分子式 —— 如 "Ca(OH)2", "Al2(SO4)3"
        # 每个元素符号：大写字母 [A-Z] 后跟 0-1 个小写字母 [a-z]?，再跟 0 或多个数字 [0-9]*
        formula_pattern = r'^([A-Z][a-z]?[0-9]*)+([A-Z][a-z]?[0-9]*)*$|^([A-Z][a-z]?[0-9]*)*\([A-Z][a-z]?[0-9]*\)[0-9]*([A-Z][a-z]?[0-9]*)*$'
        return bool(re.match(formula_pattern, query))

    # ============================================================================
    #  获取完整化合物信息 —— 整合多次查询结果
    # ============================================================================

    def get_compound_info(self, query: str) -> Dict[str, Any]:
        """
        获取完整化合物信息 —— 先搜索获取 CID，再按 CID 获取详细属性。

        这个方法是获取化合物完整信息的主要入口，它会：
        1. 先用智能搜索找到化合物
        2. 提取 CID
        3. 再按 CID 获取完整属性列表
        4. 对 SMILES 进行基本验证
        5. 合并所有信息返回

        Args:
            query: 化合物名称、CID、分子式或 InChIKey

        Returns:
            Dict: 完整化合物信息，格式为 {"Compound": {属性字典}}
        """
        try:
            # 第一步：智能搜索获取基本信息和 CID
            basic_info = self.search_compound(query)

            # 如果搜索返回错误，直接返回
            if "error" in basic_info:
                return basic_info

            try:
                # 第二步：从搜索结果中提取 CID
                if "PropertyTable" in basic_info and "Properties" in basic_info["PropertyTable"]:
                    properties = basic_info["PropertyTable"]["Properties"]
                    if properties and len(properties) > 0:
                        cid = properties[0].get("CID")
                        if cid:
                            # 第三步：按 CID 获取详细属性
                            endpoint = f"compound/cid/{cid}/property/CanonicalSMILES,IsomericSMILES,InChI,InChIKey,MolecularFormula,MolecularWeight,IUPACName,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
                            details = self._make_request(endpoint, max_retries=3)

                            if "PropertyTable" in details and "Properties" in details["PropertyTable"]:
                                detail_props = details["PropertyTable"]["Properties"][0]

                                # ---- 提取并验证 SMILES ----
                                canonical_smiles = detail_props.get("CanonicalSMILES", "N/A")
                                isomeric_smiles = detail_props.get("IsomericSMILES", "N/A")

                                # 对 SMILES 进行有效性检查
                                if canonical_smiles != "N/A" and self._is_valid_smiles(canonical_smiles):
                                    canonical_smiles_value = canonical_smiles
                                else:
                                    canonical_smiles_value = "N/A"

                                if isomeric_smiles != "N/A" and self._is_valid_smiles(isomeric_smiles):
                                    isomeric_smiles_value = isomeric_smiles
                                else:
                                    isomeric_smiles_value = "N/A"

                                # ---- 合并所有属性信息 ----
                                result = properties[0].copy()  # 保留第一次查询的基础属性
                                result.update({
                                    "canonical_smiles": canonical_smiles_value,
                                    "isomeric_smiles": isomeric_smiles_value,
                                    "inchi": detail_props.get("InChI", "N/A"),
                                    "inchi_key": detail_props.get("InChIKey", "N/A"),
                                    "molecular_formula": detail_props.get("MolecularFormula", "N/A"),
                                    "molecular_weight": detail_props.get("MolecularWeight", "N/A"),
                                    "iupac_name": detail_props.get("IUPACName", "N/A"),
                                    "xlogp": detail_props.get("XLogP", "N/A"),
                                    # XLogP：计算得到的辛醇-水分配系数，衡量亲脂性
                                    "hydrogen_bond_donor_count": detail_props.get("HBondDonorCount", "N/A"),
                                    # 氢键供体数：影响溶解性和药物活性
                                    "hydrogen_bond_acceptor_count": detail_props.get("HBondAcceptorCount", "N/A"),
                                    # 氢键受体数
                                    "rotatable_bond_count": detail_props.get("RotatableBondCount", "N/A"),
                                    # 可旋转键数：衡量分子柔韧性
                                    "tpsa": detail_props.get("TPSA", "N/A"),
                                    # TPSA: 拓扑极性表面积，预测细胞膜渗透性
                                    "complexity": detail_props.get("Complexity", "N/A")
                                    # 复杂度：分子结构复杂度评分
                                })
                                return {"Compound": result}
                            else:
                                return {"error": "Failed to get compound detailed information"}
                        else:
                            return {"error": "Failed to extract compound CID"}
                    else:
                        return {"error": "Compound property information not found"}
                else:
                    # 属性表中无数据，返回基础信息
                    return basic_info

            except Exception as e:
                logger.error(f"Error getting compound detailed information: {e}")
                return {"error": f"Error getting compound detailed information: {str(e)}"}

        except Exception as e:
            logger.error(f"Error getting complete compound information: {e}")
            return {"error": f"Error getting complete compound information: {str(e)}"}

    def _is_valid_smiles(self, smiles: str) -> bool:
        """
        简单验证 SMILES 字符串的有效性。

        SMILES (Simplified Molecular Input Line Entry System) 是用 ASCII 字符串
        表示化学结构的规范。该方法做基本检查，不依赖第三方化学库。

        验证规则：
        1. 不包含明显的无效值（N/A、None、null 等占位符）
        2. 至少包含一个字母（合法 SMILES 必然含元素符号）
        3. 至少包含一个常见化学元素符号（C, H, O, N 等）

        Args:
            smiles: 待验证的 SMILES 字符串

        Returns:
            bool: 是否通过基本验证
        """
        # 规则1：排除明显的无效占位值（精确匹配，不做子串匹配）
        # 注意：SMILES 中的 "#" 是合法字符（表示三键，如 C#N），不能据此判无效；
        # 空串用显式判断，因为 "" in smiles 对任何字符串都恒为 True
        invalid_placeholders = {"N/A", "None", "null", "NULL"}
        if not smiles or smiles.strip() in invalid_placeholders:
            return False

        # 规则2：必须至少包含一个字母字符
        if not any(c.isalpha() for c in smiles):
            return False

        # 规则3：至少包含一个常见的化学元素符号
        common_elements = ['C', 'H', 'O', 'N', 'P', 'S', 'F', 'Cl', 'Br', 'I', 'B', 'Si']
        if not any(element in smiles for element in common_elements):
            return False

        return True

    def validate_cid(self, cid: Any) -> bool:
        """
        验证 CID 格式是否有效（仅格式校验，不调用 API）。

        有效的 CID 必须是可以转换为正整数（> 0）的值。
        PubChem CID 是对每个化合物的唯一整数标识。

        Args:
            cid: 待验证的 CID 值

        Returns:
            bool: 格式是否有效
        """
        try:
            # 排除空值和占位符
            if cid is None or cid == "" or cid == "N/A":
                return False
            # CID 必须是正整数
            cid_int = int(cid)
            return cid_int > 0
        except (ValueError, TypeError):
            return False

    # ============================================================================
    #  已验证的化合物信息 —— 含数据校验和验证标记
    # ============================================================================

    def get_validated_compound_info(self, query: str) -> Dict[str, Any]:
        """
        获取经过验证的化合物信息。

        与 get_compound_info 相比，增加了：
        1. CID 格式有效性校验（正整数检查）
        2. 分子量合理性校验（必须为正数）
        3. 添加 validated=True 标记和 validation_time 时间戳

        Args:
            query: 查询内容

        Returns:
            Dict: 经过验证的化合物信息，失败时包含错误信息
        """
        try:
            # 先获取化合物完整信息
            compound_info = self.get_compound_info(query)

            # 如果底层查询已出错，直接返回
            if "error" in compound_info:
                return compound_info

            # ---- 执行验证 ----
            if "Compound" in compound_info:
                compound = compound_info["Compound"]
                cid = compound.get("CID")

                # 验证1：CID 格式
                if not self.validate_cid(cid):
                    return {
                        "success": False,
                        "query": query,
                        "error": f"Invalid CID: {cid}"
                    }

                # 验证2：分子量必须是正数
                molecular_weight = compound.get("MolecularWeight")
                if molecular_weight == "N/A" or molecular_weight is None:
                    # 分子量缺失是可以接受的（部分化合物可能没有此数据）
                    pass
                else:
                    try:
                        mw = float(molecular_weight)
                        if mw <= 0:
                            return {
                                "success": False,
                                "query": query,
                                "error": f"Invalid molecular weight: {molecular_weight}"
                            }
                    except (ValueError, TypeError):
                        # 分子量不是数字格式，但可能是特殊值，暂时放过
                        pass

                # ---- 添加验证标记 ----
                compound_info["validated"] = True                # 标记已通过验证
                compound_info["validation_time"] = time.time()   # 记录验证时间戳

            return compound_info

        except Exception as e:
            logger.error(f"Error validating compound information: {e}")
            return {
                "success": False,
                "query": query,
                "error": f"Validation failed: {str(e)}"
            }

    # ============================================================================
    #  含 CAS 号的完整化合物信息
    # ============================================================================

    def get_compound_info_with_cas(self, query: str) -> Dict[str, Any]:
        """
        获取包含 CAS 号的完整化合物信息。

        CAS (Chemical Abstracts Service) 号是化学物质的权威标识符。
        PubChem 没有独立的 CAS 字段，CAS 号藏于同义词列表中（格式: XXXXX-XX-X）。
        此方法先查基本属性获取 CID，再查同义词过滤出 CAS 号。

        Args:
            query: 化合物名称或分子式

        Returns:
            Dict: 包含 CASNumbers 数组的化合物信息
        """
        # 第一步：获取基本属性信息
        basic_info = self.search_compound(query)

        if "error" in basic_info:
            return basic_info

        try:
            # 第二步：从属性表中提取 CID
            if "PropertyTable" in basic_info and "Properties" in basic_info["PropertyTable"]:
                properties = basic_info["PropertyTable"]["Properties"]
                if properties and len(properties) > 0:
                    cid = properties[0].get("CID")
                    if cid:
                        # 第三步：获取同义词列表（包含 CAS 号）
                        synonyms_data = self.get_synonyms_with_cas(query)
                        cas_numbers = []

                        # 解析同义词响应，提取 CAS 号
                        if "InformationList" in synonyms_data and "Information" in synonyms_data["InformationList"]:
                            info_list = synonyms_data["InformationList"]["Information"]
                            if info_list and len(info_list) > 0:
                                synonyms = info_list[0].get("Synonym", [])
                                # 过滤出符合 CAS 格式的同义词（XXXXX-XX-X）
                                cas_numbers = [syn for syn in synonyms if self._is_cas_number(syn)]

                        # 第四步：合并 CAS 号到结果中
                        result = properties[0].copy()
                        result["CASNumbers"] = cas_numbers
                        return {"Compound": result}

            # 无 CAS 信息时返回基础信息
            return basic_info

        except Exception as e:
            logger.error(f"Error getting complete compound information: {e}")
            return {"error": f"Error getting complete compound information: {str(e)}"}

    def _is_cas_number(self, text: str) -> bool:
        """
        判断文本是否为 CAS 号格式。

        CAS 号由连字符分为三部分：XXXXX-XX-X
        - 第一部分：2-7 位数字
        - 第二部分：2 位数字
        - 第三部分：1 位校验数字

        例如：58-08-2（咖啡因）、7732-18-5（水）

        Args:
            text: 待判断的文本

        Returns:
            bool: 是否匹配 CAS 号格式
        """
        import re
        # CAS 正则：2-7位数字 - 2位数字 - 1位数字
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'
        return bool(re.match(cas_pattern, text))

# ============================================================================
#  全局单例管理
# ============================================================================

# 全局 PubChemTool 实例，初始为 None
pubchem_tool = None

def get_pubchem_tool(api_key: str = None) -> PubChemTool:
    """
    获取 PubChem 工具单例实例。
    采用惰性初始化模式：首次调用时创建，后续调用返回同一实例。

    Args:
        api_key (str, optional): PubChem API 密钥（仅首次创建时使用）

    Returns:
        PubChemTool: 工具实例
    """
    global pubchem_tool
    if pubchem_tool is None:
        pubchem_tool = PubChemTool(api_key)
    return pubchem_tool
