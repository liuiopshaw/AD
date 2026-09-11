import requests
import logging
import time
import random
import os
from typing import Dict, Any, List, Optional

# 配置日志：设置默认级别为 WARNING，减少运行时的日志噪音
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class MolPortTool:
    """MolPort database query tool.

    MolPort 是一个商业化学品数据库，提供化合物的供应商、库存和价格信息。
    本工具封装了 MolPort API 的核心功能，用于评估化合物的商业可获得性。

    Supported features:
    1. 通过 SMILES 搜索化合物（精确匹配、相似性搜索、子结构搜索等）
    2. 通过 MolPort ID 获取详细信息
    3. 获取供应商、库存和价格信息
    4. 评估化合物的商业可获得性
    """

    # 搜索类型常量定义
    # MolPort API 使用整数编码不同的搜索模式
    SEARCH_TYPE_EXACT = 3        # 精确匹配搜索
    SEARCH_TYPE_SIMILARITY = 4   # 相似性搜索（默认模式）
    SEARCH_TYPE_SUBSTRUCTURE = 1 # 子结构搜索：查找包含指定子结构的化合物
    SEARCH_TYPE_SUPERSTRUCTURE = 2 # 超结构搜索：查找被指定结构包含的化合物
    SEARCH_TYPE_PERFECT = 5      # 完美匹配：包括立体化学
    SEARCH_TYPE_EXACT_FRAGMENT = 6 # 精确片段搜索

    def __init__(self, api_key: str = None):
        """
        Initialize MolPort tool.
        初始化 MolPort 工具，配置 API 连接和请求控制。

        Args:
            api_key: MolPort API 密钥，如果未提供则从环境变量 MOLPORT_API_KEY 中读取
                     使用环境变量存储 API 密钥是一种安全最佳实践，
                     避免将敏感信息硬编码在代码中
        """
        # MolPort API 的基础 URL
        self.base_url = "https://api.molport.com/api"
        # API 密钥：优先使用传入参数，其次读取环境变量，都没有则为空字符串
        self.api_key = api_key or os.getenv('MOLPORT_API_KEY', '')
        # 创建可复用的 HTTP 会话对象
        self.session = requests.Session()

        # 设置 HTTP 请求头
        # User-Agent 标识工具来源，Content-Type 和 Accept 指定 JSON 格式的数据交换
        self.session.headers.update({
            "User-Agent": "ECOMATS-MolPort-Tool/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

        # 请求频率控制
        # last_request_time 记录上次请求的时间戳，用于实现最小请求间隔
        self.last_request_time = 0
        # 最小请求间隔 1.0 秒：MolPort API 的速率限制相对宽松
        self.min_request_interval = 1.0

    def _make_get_request(self, endpoint: str, params: Dict = None, timeout: int = 30, max_retries: int = 3) -> Dict[str, Any]:
        """
        Send GET request with retry mechanism.
        发送 GET 请求，内置重试和频率控制机制。

        设计要点：
        1. 频率控制：确保请求间隔不小于 min_request_interval，避免触发 API 速率限制
        2. 指数退避重试：网络故障时自动重试，重试间隔逐渐增加
        3. 随机抖动：在退避延迟中加入随机因子，避免"惊群效应"

        Args:
            endpoint: API 端点路径
            params: URL 查询参数字典
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数

        Returns:
            API 响应数据字典，失败时返回 {"error": ...}
        """
        # 频率控制：如果距离上次请求时间不足最小间隔，则等待剩余时间
        # 这是客户端侧的限流保护，确保不会对 API 服务端造成过大压力
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last_request)

        for attempt in range(max_retries):
            try:
                # 构造完整的请求 URL
                url = f"{self.base_url}/{endpoint}"
                logger.debug(f"请求 MolPort API (GET): {url}")

                # 更新上次请求时间（在发送请求前更新，确保频繁请求得到正确限流）
                self.last_request_time = time.time()

                # 发送 GET 请求
                response = self.session.get(url, params=params, timeout=timeout)
                # 检查 HTTP 状态码，4xx/5xx 会抛出异常
                response.raise_for_status()

                # 返回解析后的 JSON 数据
                return response.json()

            except requests.exceptions.RequestException as e:
                # 网络请求异常（连接错误、超时、服务器错误等）
                logger.warning(f"MolPort API请求失败（第 {attempt + 1}/{max_retries} 次尝试）: {e}")
                if attempt < max_retries - 1:
                    # 指数退避延迟：2^attempt 秒 + 0-1 秒的随机抖动
                    # 这样第1次重试等待约1-2秒，第2次等待约2-3秒，第3次等待约4-5秒
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    logger.info(f"等待 {delay:.2f} 秒后重试")
                    time.sleep(delay)
                else:
                    # 所有重试都失败，记录最终错误日志
                    logger.error(f"MolPort API请求最终失败: {e}")
                    return {"error": f"API请求失败: {str(e)}"}
            except Exception as e:
                # 其他异常（如 JSON 解析错误等）
                logger.error(f"处理响应时出错: {e}")
                return {"error": f"处理响应时出错: {str(e)}"}

        # 理论上不会执行到这里（循环内总会返回或最后一次迭代返回错误），
        # 但作为防御性编程保留此兜底返回
        return {"error": "请求失败"}

    def _make_post_request(self, endpoint: str, data: Dict = None, timeout: int = 60, max_retries: int = 3) -> Dict[str, Any]:
        """
        Send POST request with retry mechanism.
        发送 POST 请求，内置重试和频率控制机制。

        与 _make_get_request 的区别：
        - 使用 POST 方法发送 JSON 请求体
        - 默认超时时间更长（60 秒），因为化学结构搜索可能较耗时
        - 数据通过 json=data 参数发送（自动序列化为 JSON 并设置 Content-Type）

        Args:
            endpoint: API 端点路径
            data: 请求体数据字典
            timeout: 请求超时时间（秒），默认 60 秒
            max_retries: 最大重试次数

        Returns:
            API 响应数据字典，失败时返回 {"error": ...}
        """
        # 频率控制：确保遵守最小请求间隔
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last_request)

        for attempt in range(max_retries):
            try:
                url = f"{self.base_url}/{endpoint}"
                logger.debug(f"请求 MolPort API (POST): {url}")

                # 更新上次请求时间
                self.last_request_time = time.time()

                # 发送 POST 请求，json=data 自动将字典序列化为 JSON
                # requests 库会自动设置 Content-Type 为 application/json
                response = self.session.post(url, json=data, timeout=timeout)
                response.raise_for_status()

                return response.json()

            except requests.exceptions.RequestException as e:
                logger.warning(f"MolPort API请求失败（第 {attempt + 1}/{max_retries} 次尝试）: {e}")
                if attempt < max_retries - 1:
                    # 指数退避 + 随机抖动
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    logger.info(f"等待 {delay:.2f} 秒后重试")
                    time.sleep(delay)
                else:
                    logger.error(f"MolPort API请求最终失败: {e}")
                    return {"error": f"API请求失败: {str(e)}"}
            except Exception as e:
                logger.error(f"处理响应时出错: {e}")
                return {"error": f"处理响应时出错: {str(e)}"}

        return {"error": "请求失败"}

    def load_molecule_by_id(self, molecule_id: str) -> Dict[str, Any]:
        """
        Load molecule details by MolPort ID.
        通过 MolPort ID 加载分子详细信息。

        MolPort ID 格式：
        - 简短格式：如 "2325020"
        - 长格式：如 "Molport-002-325-020"
        方法内部会自动处理格式转换。

        Args:
            molecule_id: MolPort 分子 ID（支持两种格式）

        Returns:
            包含 SMILES、供应商、价格、库存等信息的分子详情字典
        """
        # 检查 API 密钥是否已配置
        if not self.api_key:
            return {"error": "MOLPORT_API_KEY 未配置，请在 .env 文件中设置"}

        # 处理 MolPort ID 格式：去除 "Molport-" 前缀和所有 "-" 符号
        # 例如 "Molport-002-325-020" → "002325020"
        if isinstance(molecule_id, str) and molecule_id.startswith("Molport-"):
            molecule_id = molecule_id.replace("Molport-", "").replace("-", "")

        # MolPort API 的 molecule/load 端点
        endpoint = "molecule/load"
        params = {
            "molecule": molecule_id,  # 分子 ID
            "apikey": self.api_key     # API 密钥作为查询参数传递
        }

        # 发送 GET 请求获取分子信息
        return self._make_get_request(endpoint, params=params)

    def search_by_smiles(
        self,
        smiles: str,
        search_type: int = None,
        similarity_index: float = 0.9,
        max_results: int = 100,
        max_search_time: int = 60000
    ) -> Dict[str, Any]:
        """
        Search by SMILES structure.
        通过 SMILES（Simplified Molecular Input Line Entry System）结构搜索化合物。

        SMILES 是一种用 ASCII 字符串表示化学结构的线性符号系统，
        是化学信息学中最常用的分子结构表示方法之一。

        Args:
            smiles: SMILES 字符串，例如 "CCO" 表示乙醇，"c1ccccc1" 表示苯
            search_type: 搜索类型（1-6），默认使用相似性搜索（类型 4）
            similarity_index: 相似度阈值（0-1），仅适用于相似性搜索
                             0.9 表示要求 90% 以上的结构相似度
            max_results: 最大返回结果数（上限 10000）
            max_search_time: 最大搜索时间（毫秒），默认 60000ms（60秒）

        Returns:
            包含匹配的分子 ID、SMILES 和相似度指数的搜索结果列表
        """
        # 检查 API 密钥
        if not self.api_key:
            return {"error": "MOLPORT_API_KEY 未配置，请在 .env 文件中设置"}

        # 如果未指定搜索类型，默认使用相似性搜索（最常用的搜索模式）
        if search_type is None:
            search_type = self.SEARCH_TYPE_SIMILARITY

        # 参数校验：确保 max_results 不超过 API 的上限 10000
        if max_results > 10000:
            max_results = 10000
        # 相似度指数必须在 0 到 1 之间
        if similarity_index < 0 or similarity_index > 1:
            similarity_index = 0.9

        # MolPort 化学结构搜索的端点
        endpoint = "chemical-search/search"
        # 构造 POST 请求体
        data = {
            "API Key": self.api_key,
            "Structure": smiles,                    # SMILES 结构字符串
            "Search Type": search_type,              # 搜索类型（1-6）
            "Maximum Result Count": max_results,     # 最大结果数
            "Maximum Search Time": max_search_time,  # 最大搜索时间
            "Chemical Similarity Index": similarity_index  # 化学相似度指数
        }

        # 结构搜索使用 POST 请求，因为 SMILES 数据可能较长且包含特殊字符
        return self._make_post_request(endpoint, data=data)

    def get_availability_info(self, molecule_id: str) -> Dict[str, Any]:
        """
        Get commercial availability info (simplified version).
        获取化合物的商业可获得性信息（简化版）。

        整合了以下信息：
        - 分子基本信息（SMILES、IUPAC 名称、分子式、分子量）
        - 供应商数量和详细信息
        - 价格范围和货币单位
        - 库存数量

        Args:
            molecule_id: MolPort 分子 ID

        Returns:
            包含可获得性、供应商数量、价格范围等信息的字典
        """
        # 先通过 MolPort ID 加载分子完整数据
        molecule_data = self.load_molecule_by_id(molecule_id)

        # 如果加载失败则直接返回错误
        if "error" in molecule_data:
            return molecule_data

        try:
            # MolPort API 响应结构：Data.Molecule 包含分子核心信息
            data = molecule_data.get("Data", {}).get("Molecule", {})

            # 提取关键可获得性信息
            availability_info = {
                "molport_id": data.get("Molport Id", ""),
                "status": data.get("Status", ""),        # 分子状态（如活跃/非活跃）
                "type": data.get("Type", ""),            # 分子类型（如 screening/building block）
                "largest_stock": data.get("Largest Stock", ""),     # 最大库存量
                "largest_stock_measure": data.get("Largest Stock Measure", ""),  # 库存计量单位
                "smiles": data.get("SMILES", ""),
                "iupac": data.get("IUPAC", ""),
                "formula": data.get("Formula", ""),
                "molecular_weight": data.get("Molecular Weight", ""),
                "supplier_count": 0,   # 供应商计数器
                "min_price": None,     # 最低价格
                "max_price": None,     # 最高价格
                "currency": None       # 货币单位
            }

            # 统计供应商信息和价格信息
            # Catalogues 包含不同类别的供应商目录
            catalogues = data.get("Catalogues", {})
            all_suppliers = []

            # 遍历三种供应商类别：
            # - Screening Block Suppliers：筛选化合物供应商
            # - Building Block Suppliers：构建块供应商
            # - Virtual Suppliers：虚拟供应商（可能没有现货）
            for category in ["Screening Block Suppliers", "Building Block Suppliers", "Virtual Suppliers"]:
                suppliers = catalogues.get(category, [])
                # extend 将列表元素逐一添加到 all_suppliers，而不是嵌套列表
                all_suppliers.extend(suppliers)

            # 记录供应商总数
            availability_info["supplier_count"] = len(all_suppliers)

            # 收集所有供应商提供的价格信息
            # 价格结构：供应商 → 目录 → 包装规格 → 单价
            prices = []
            for supplier in all_suppliers:
                for catalogue in supplier.get("Catalogues", []):
                    for packing in catalogue.get("Available Packings", []):
                        price = packing.get("Price")
                        currency = packing.get("Currency")
                        if price is not None:
                            # 记录价格、货币、数量和单位
                            prices.append({
                                "price": price,
                                "currency": currency,
                                "amount": packing.get("Amount", ""),
                                "measure": packing.get("Measure", "")
                            })

            # 如果有价格数据，计算汇总统计信息
            if prices:
                # 假设所有价格使用相同货币（通常是 USD）
                # 取第一个价格条目的货币作为默认货币
                availability_info["currency"] = prices[0]["currency"]
                # 提取纯价格数值列表用于计算最小/最大值
                price_values = [p["price"] for p in prices]
                availability_info["min_price"] = min(price_values)
                availability_info["max_price"] = max(price_values)
                # 仅保留前 5 个价格条目作为示例，避免返回数据过大
                availability_info["price_details"] = prices[:5]

            return availability_info

        except Exception as e:
            # 解析数据过程中出现异常
            logger.error(f"解析可获得性信息时出错: {e}")
            return {"error": f"解析数据失败: {str(e)}"}

    def check_compound_availability(self, smiles: str, similarity_threshold: float = 0.95) -> Dict[str, Any]:
        """
        Check compound commercial availability by SMILES.
        通过 SMILES 检查化合物的商业可获得性。

        采用两阶段搜索策略：
        1. 首先尝试精确匹配搜索（找到完全相同的化合物）
        2. 如果没有精确匹配，再尝试相似性搜索（找到结构相似的替代品）

        这种策略可以最大化找到可购买化合物的概率。

        Args:
            smiles: SMILES 字符串
            similarity_threshold: 相似度阈值（0-1），决定"可获得"的判定标准
                                  默认 0.95，表示结构相似度 95% 以上认为可获得

        Returns:
            可获得性评估结果字典，包含匹配状态、最佳匹配等
        """
        # 第一阶段：精确搜索
        # 精确匹配是最高质量的匹配，化合物结构完全一致
        exact_result = self.search_by_smiles(smiles, search_type=self.SEARCH_TYPE_EXACT, max_results=10)

        # 如果精确搜索本身出错，直接返回错误
        if "error" in exact_result:
            return exact_result

        # 提取搜索结果
        result_data = exact_result.get("Data", {})
        molecules = result_data.get("Molecules", [])

        # 初始化评估结果对象
        assessment = {
            "query_smiles": smiles,
            "exact_match_found": len(molecules) > 0,  # 是否存在精确匹配
            "match_count": len(molecules),
            "availability_status": "unknown",  # 可获得性状态：available/similar_available/not_available
            "best_match": None
        }

        if molecules:
            # 找到精确匹配：化合物可直接从供应商购买
            assessment["availability_status"] = "available"
            best_match = molecules[0]  # 取第一个（通常是最佳）匹配
            assessment["best_match"] = {
                "molport_id": best_match.get("Molport Id", ""),
                "smiles": best_match.get("SMILES", ""),
                "canonical_smiles": best_match.get("Canonical SMILES", ""),
                "verified_amount": best_match.get("Verified Amount", 0),    # 已验证的库存量
                "unverified_amount": best_match.get("Unverified Amount", 0) # 未验证的库存量
            }
        else:
            # 第二阶段：无精确匹配，尝试相似性搜索
            # 相似性搜索可以找到结构相似但不完全相同的替代品
            similar_result = self.search_by_smiles(
                smiles,
                search_type=self.SEARCH_TYPE_SIMILARITY,
                similarity_index=similarity_threshold,
                max_results=10
            )

            if "error" not in similar_result:
                similar_molecules = similar_result.get("Data", {}).get("Molecules", [])
                if similar_molecules:
                    # 存在相似结构化合物：可以买到类似物
                    assessment["availability_status"] = "similar_available"
                    assessment["match_count"] = len(similar_molecules)
                    best_match = similar_molecules[0]
                    assessment["best_match"] = {
                        "molport_id": best_match.get("Molport Id", ""),
                        "smiles": best_match.get("SMILES", ""),
                        "canonical_smiles": best_match.get("Canonical SMILES", ""),
                        "similarity_index": best_match.get("Similarity Index", 0),  # 相似度指数
                        "verified_amount": best_match.get("Verified Amount", 0),
                        "unverified_amount": best_match.get("Unverified Amount", 0)
                    }
                else:
                    # 既没有精确匹配也没有相似匹配：化合物不可购买
                    assessment["availability_status"] = "not_available"

        return assessment


# 单例模式：全局唯一实例
# 使用模块级变量保存 MolPortTool 的实例，确保全局复用
_molport_tool_instance = None

def get_molport_tool(api_key: str = None) -> MolPortTool:
    """
    Get MolPort tool singleton.
    获取 MolPort 工具的单例实例。

    单例模式的优势：
    - HTTPSession 复用：避免为每次调用创建新的 TCP 连接
    - 请求频率控制：全局统一管理 API 请求间隔
    - 内存高效：只有一个实例及其缓存数据

    Args:
        api_key: MolPort API 密钥（可选）
                 仅在首次创建实例时使用，后续调用会忽略此参数

    Returns:
        MolPortTool 的单例实例
    """
    global _molport_tool_instance
    # 惰性初始化：只有在首次调用时才创建实例
    if _molport_tool_instance is None:
        _molport_tool_instance = MolPortTool(api_key=api_key)
    return _molport_tool_instance
