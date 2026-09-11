#!/usr/bin/env python3
"""
Materials Project API Tool.
Provides access to Materials Project materials database.
Uses official mp-api client.

Materials Project API 工具 —— 提供对 Materials Project 材料数据库（无机材料）的访问。
使用官方 mp-api 客户端进行查询。
"""

import os
import logging
import time
from typing import Dict, List, Optional, Any

# ---- 日志配置 ----
# 将日志级别设为 WARNING，减少正常查询时的日志噪音
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---- 全局调用频率控制 ----
# 为防止 API 调用过于频繁而触发限流，使用全局变量记录上次调用时间
_last_call_time = 0                 # 记录上次 API 调用的时间戳（Unix 时间）
_call_interval = 2.0               # 调用间隔：提高到 2 秒，避免频繁调用触发限流
_max_retries = 3                   # 单次操作的最大重试次数

# ---- 可选依赖检查 ----
# mp-api 不是必装依赖，如果未安装则标记不可用
try:
    from mp_api.client import MPRester
    MP_API_AVAILABLE = True
except ImportError:
    # mp-api 客户端未安装，Materials Project 工具将不可用
    MP_API_AVAILABLE = False
    logger.warning("mp-api client not installed, Materials Project tool will be unavailable")

class MaterialsProjectTool:
    """Materials Project API 工具类。

    支持对以下各类无机材料进行查询和验证：
    1. 纯金属材料 (Pure metal materials)
    2. 金属氧化物 (Metal oxides)
    3. 金属硫化物 (Metal sulfides)
    4. 金属氮化物/碳化物 (Metal nitrides/carbides)
    5. MOF/COF 材料 (Metal-Organic Frameworks / Covalent Organic Frameworks)
    6. 其他无机化合物 (Other inorganic compounds)
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化 Materials Project 工具。

        Args:
            api_key (str, optional): Materials Project API 密钥。
                                     如果未提供，则从环境变量 MATERIALS_PROJECT_API_KEY 读取。

        Raises:
            ImportError: 如果 mp-api 客户端未安装
            ValueError: 如果 API 密钥未设置
        """
        # 检查 mp-api 依赖是否安装
        if not MP_API_AVAILABLE:
            raise ImportError("mp-api client not installed, please run 'pip install mp-api'")

        # 获取 API 密钥：优先使用传入的 key，其次从环境变量读取
        self.api_key = api_key or os.getenv('MATERIALS_PROJECT_API_KEY')
        if not self.api_key:
            raise ValueError("Materials Project API key not set")

        # 初始化 MPRester 客户端 —— 与 Materials Project API 通信的核心对象
        self.mpr = MPRester(self.api_key)

        # ---- 本地缓存系统 ----
        # 为避免重复 API 调用，使用内存字典缓存查询结果。
        # 缓存按查询类型分桶，每个桶存储 {key: value} 映射。
        # TTL (Time-To-Live) 为 600 秒（10 分钟），过期后重新查询。
        self._cache = {
            "search": {},        # 搜索结果的缓存（精确匹配 limit/skip/fields）
            "search_norm": {},   # 搜索结果的归一化缓存（忽略 limit/skip，用于子集切片）
            "by_id": {},         # 按 ID 查询的缓存
            "verify": {}         # ID 验证结果的缓存
        }
        self._ttl_seconds = 600  # 缓存有效期：600 秒

    def search_materials(self,
                        formula: Optional[str] = None,
                        elements: Optional[List[str]] = None,
                        exclude_elements: Optional[List[str]] = None,
                        crystal_system: Optional[str] = None,
                        limit: int = 100,
                        skip: int = 0,
                        fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        搜索材料 —— 最全面的材料查询入口。

        支持多条件组合查询：化学式、包含元素、排除元素、晶体系统等。

        Args:
            formula (str, optional): 化学式，如 "C3N4"
            elements (List[str], optional): 必须包含的元素列表，如 ["Fe", "O"]
            exclude_elements (List[str], optional): 必须排除的元素列表
            crystal_system (str, optional): 晶体系统，如 "cubic"
            limit (int): 返回结果的最大数量，默认 100
            skip (int): 跳过的结果数，用于分页
            fields (List[str], optional): 需要返回的数据字段列表

        Returns:
            Dict: 包含 data（材料列表）和 meta（元信息）的搜索结果字典
        """
        try:
            # ---- 调用频率控制 + 重试机制 ----
            global _last_call_time, _call_interval, _max_retries
            retries = 0

            while retries < _max_retries:
                try:
                    # 如果距离上次调用时间过短，则等待到间隔满足为止
                    current_time = time.time()
                    time_since_last_call = current_time - _last_call_time
                    if time_since_last_call < _call_interval:
                        time.sleep(_call_interval - time_since_last_call)
                    _last_call_time = time.time()  # 更新调用时间

                    # ---- 构建搜索参数 ----
                    # MPRester.materials.search 接受关键字参数形式的过滤条件
                    kwargs = {}

                    if formula:
                        kwargs["formula"] = formula
                    if elements:
                        kwargs["elements"] = elements
                    if exclude_elements:
                        kwargs["exclude_elements"] = exclude_elements
                    if crystal_system:
                        kwargs["crystal_system"] = crystal_system

                    # chunk_size: 每次从 API 拉取的数据块大小。
                    # 如果按元素查询则限制为 50（可能返回量大），否则上限 100
                    chunk_size = min(limit, 50) if elements else min(limit, 100)

                    # ---- 默认返回字段 ----
                    # 只请求必要的字段，节省带宽和 API 调用时间
                    default_fields = [
                        "material_id",        # 材料唯一标识符，如 "mp-1234"
                        "formula_pretty"      # 美化后的化学式，如下标格式
                    ]
                    fields = fields or default_fields

                    # ---- 构建归一化缓存键 ----
                    # 归一化缓存键不包含 limit/skip/fields，用于跨查询复用相同条件的结果
                    normalized_key = (
                        formula or "",
                        tuple(elements) if elements else (),
                        tuple(exclude_elements) if exclude_elements else (),
                        crystal_system or ""
                    )

                    # ---- 检查归一化缓存 ----
                    # 如果命中，则从缓存中按 skip/limit 切片返回，避免重复 API 调用
                    norm_entry = self._cache["search_norm"].get(normalized_key)
                    now = time.time()
                    if norm_entry and now - norm_entry["timestamp"] < self._ttl_seconds:
                        cached_materials = norm_entry["materials"]
                        cached_fields_set = norm_entry.get("fields_set", set())
                        requested_fields_set = set(fields)
                        # 只有当缓存包含所有请求字段、且缓存数据量足够覆盖请求的 skip+limit 时才复用
                        if requested_fields_set.issubset(cached_fields_set) and len(cached_materials) >= (skip + limit):
                            slice_materials = cached_materials[skip:skip+limit]
                            # 只返回请求的字段（但始终保留 material_id 和 formula 作为标识）
                            subset_list = []
                            for m in slice_materials:
                                subset = {k: v for k, v in m.items() if k in requested_fields_set or k in {"material_id", "formula"}}
                                # 确保 formula 字段存在（兼容旧数据）
                                if "formula" not in subset and "formula" in m:
                                    subset["formula"] = m.get("formula")
                                subset_list.append(subset)
                            return {
                                "data": subset_list,
                                "meta": {
                                    "total_count": len(subset_list),
                                    "limit": limit
                                }
                            }

                    # ---- 构建精确缓存键 ----
                    # 包含完整查询参数（包括 limit/skip/fields）的缓存键
                    cache_key = (
                        formula or "",
                        tuple(elements) if elements else (),
                        tuple(exclude_elements) if exclude_elements else (),
                        crystal_system or "",
                        limit,
                        skip,
                        tuple(fields)
                    )
                    now = time.time()
                    cached = self._cache["search"].get(cache_key)
                    # 精确缓存存储 (timestamp, result) 元组
                    if cached and now - cached[0] < self._ttl_seconds:
                        return cached[1]

                    # ---- 执行搜索 ----
                    # 调用 mp-api 的 materials.search 方法
                    docs = self.mpr.materials.search(
                        **kwargs,
                        num_chunks=1,         # 只请求 1 个数据块
                        chunk_size=chunk_size,
                        fields=fields
                    )

                    # 手动限制返回结果数量（mp-api 返回的数量可能超过 limit）
                    if len(docs) > limit:
                        docs = docs[:limit]

                    # 手动应用 skip 参数，跳过前 skip 条结果
                    if skip > 0:
                        docs = docs[skip:]

                    # ---- 将 API 返回的文档对象转换为字典格式 ----
                    # getattr 的安全获取方式避免缺少属性时报错
                    materials_data = []
                    for doc in docs:
                        material_dict = {
                            "material_id": str(getattr(doc, "material_id", "N/A")),
                            "formula": getattr(doc, "formula_pretty", getattr(doc, "formula", "N/A")),
                            "chemsys": getattr(doc, "chemsys", "N/A")
                        }
                        # 如果请求了 volume 字段，附加单位 A^3
                        if "volume" in fields:
                            volume_value = getattr(doc, "volume", "N/A")
                            material_dict["volume"] = f"{volume_value} A^3" if volume_value != "N/A" else "N/A"
                        # 如果请求了 density 字段，附加单位 g/cm^3
                        if "density" in fields:
                            density_value = getattr(doc, "density", "N/A")
                            material_dict["density"] = f"{density_value} g/cm^3" if density_value != "N/A" else "N/A"
                        # 如果请求了 nsites 字段（晶胞原子位点数）
                        if "nsites" in fields:
                            material_dict["nsites"] = getattr(doc, "nsites", "N/A")
                        materials_data.append(material_dict)

                    # 构建标准返回格式
                    result = {
                        "data": materials_data,
                        "meta": {
                            "total_count": len(materials_data),
                            "limit": limit
                        }
                    }

                    # ---- 更新精确缓存 ----
                    self._cache["search"][cache_key] = (time.time(), result)

                    # ---- 更新归一化缓存 ----
                    # 归一化缓存保存更大的结果列表，以便后续不同 limit/skip 的请求可以复用
                    prev = self._cache["search_norm"].get(normalized_key)
                    merged_list = materials_data
                    # 收集当前结果中所有出现的字段名
                    fields_set = set()
                    for item in merged_list:
                        fields_set.update(item.keys())
                    if prev and now - prev["timestamp"] < self._ttl_seconds:
                        # 如果已有缓存且结果更多，保留更大的结果集
                        if len(prev["materials"]) > len(merged_list):
                            merged_list = prev["materials"]
                            fields_set.update(prev.get("fields_set", set()))
                    self._cache["search_norm"][normalized_key] = {
                        "timestamp": time.time(),
                        "materials": merged_list,
                        "fields_set": fields_set
                    }
                    return result

                except Exception as e:
                    # ---- 重试逻辑 ----
                    retries += 1
                    if retries >= _max_retries:
                        # 达到最大重试次数，记录错误并返回错误信息
                        logger.error(f"Error searching materials: {e}")
                        return {"error": f"Error searching materials: {str(e)}"}
                    else:
                        # 未达到最大重试，记录警告后等待并进行指数退避
                        logger.warning(f"Error searching materials, retrying ({retries}/{_max_retries}): {e}")
                        time.sleep(_call_interval * retries)  # 指数退避：第N次重试等待 N * interval 秒

        except Exception as e:
            # 最外层异常捕获，确保不会因未预期异常导致程序崩溃
            logger.error(f"Error searching materials: {e}")
            return {"error": f"Error searching materials: {str(e)}"}

    def get_material_by_id(self, material_id: str) -> Dict[str, Any]:
        """
        根据材料 ID 获取详细信息。

        典型用法：先通过 search_materials 得到 material_id 列表，
        再调用此方法获取某个材料的详细属性（体积、密度、晶体对称性等）。

        Args:
            material_id (str): 材料唯一标识符，格式如 "mp-1234"

        Returns:
            Dict: 材料详细信息字典，包含 material_id、formula、chemsys、
                  volume、density、nsites、crystal_system 等字段
        """
        try:
            # ---- 验证 material_id 的基本格式 ----
            if not material_id or material_id == "N/A" or material_id == "":
                return {"error": f"Invalid material ID: {material_id}"}

            # ---- 调用频率控制 + 重试机制 ----
            global _last_call_time, _call_interval, _max_retries
            retries = 0

            while retries < _max_retries:
                try:
                    # 先检查 by_id 缓存
                    now = time.time()
                    cached = self._cache["by_id"].get(material_id)
                    if cached and now - cached[0] < self._ttl_seconds:
                        return cached[1]

                    # 频率控制等待
                    current_time = time.time()
                    time_since_last_call = current_time - _last_call_time
                    if time_since_last_call < _call_interval:
                        time.sleep(_call_interval - time_since_last_call)
                    _last_call_time = time.time()

                    # ---- 定义所需字段 ----
                    # 只请求需要的字段以减少 API 负载
                    fields = [
                        "material_id",
                        "formula_pretty",
                        "chemsys",
                        "volume",      # 晶胞体积
                        "density",     # 密度
                        "nsites",      # 原子位点数
                        "symmetry"     # 对称性信息（包含 crystal_system）
                    ]

                    # 按 material_ids 精确查询
                    docs = self.mpr.materials.search(material_ids=[material_id], fields=fields)

                    # 无结果返回错误
                    if not docs:
                        return {"error": f"Material ID not found: {material_id}"}

                    doc = docs[0]

                    # ---- 验证返回的 material_id 是否匹配 ----
                    # 防止 API 返回了错误的材料
                    retrieved_material_id = str(getattr(doc, "material_id", ""))
                    if retrieved_material_id != material_id:
                        return {"error": f"Material ID mismatch: queried {material_id}, got {retrieved_material_id}"}

                    # ---- 安全属性获取辅助函数 ----
                    def safe_getattr(obj, attr, default="N/A"):
                        """安全获取属性值，确保结果可 JSON 序列化。
                        处理 None、空字符串等异常情况。"""
                        try:
                            value = getattr(obj, attr, default)
                            if value is None or value == "":
                                return default
                            # 转为字符串以确保 JSON 可序列化
                            return str(value)
                        except Exception:
                            return default

                    def safe_get_nested_attr(obj, attr_chain, default="N/A"):
                        """安全获取嵌套属性值。
                        例如 safe_get_nested_attr(doc, ["symmetry", "crystal_system"])"""
                        try:
                            current = obj
                            for attr in attr_chain:
                                if current is None:
                                    return default
                                current = getattr(current, attr, None)
                            if current is None or current == "":
                                return default
                            return str(current)
                        except Exception:
                            return default

                    # ---- 提取材料属性并附加单位 ----
                    # 体积附加 Angstrom^3 单位
                    volume_value = safe_getattr(doc, "volume", "N/A")
                    volume_with_unit = f"{volume_value} A^3" if volume_value != "N/A" else "N/A"

                    # 密度附加 g/cm^3 单位
                    density_value = safe_getattr(doc, "density", "N/A")
                    density_with_unit = f"{density_value} g/cm^3" if density_value != "N/A" else "N/A"

                    # 从嵌套的 symmetry 对象中提取 crystal_system
                    crystal_system_value = safe_get_nested_attr(doc, ["symmetry", "crystal_system"], "N/A")

                    # ---- 构建材料信息字典 ----
                    material_info = {
                        "material_id": safe_getattr(doc, "material_id", "N/A"),
                        "formula": safe_getattr(doc, "formula_pretty", safe_getattr(doc, "formula", "N/A")),
                        "chemsys": safe_getattr(doc, "chemsys", "N/A"),
                        "volume": volume_with_unit,
                        "density": density_with_unit,
                        "nsites": safe_getattr(doc, "nsites", "N/A"),
                        "crystal_system": crystal_system_value,
                        "validated": True,               # 标记已通过 MP API 验证
                        "validation_time": time.time()   # 记录验证时间戳
                    }

                    # 更新缓存
                    self._cache["by_id"][material_id] = (time.time(), material_info)
                    return material_info

                except Exception as e:
                    # ---- 重试逻辑 ----
                    retries += 1
                    if retries >= _max_retries:
                        logger.error(f"Error getting material details: {e}")
                        return {"error": f"Error getting material details: {str(e)}"}
                    else:
                        logger.warning(f"Error getting material details, retrying ({retries}/{_max_retries}): {e}")
                        time.sleep(_call_interval * retries)  # 指数退避

        except Exception as e:
            logger.error(f"Error getting material details: {e}")
            return {"error": f"Error getting material details: {str(e)}"}

    def validate_material_id(self, material_id: Any) -> bool:
        """
        验证 material ID 的格式是否有效（仅格式校验，不调用 API）。

        有效的 material_id 格式：
        - 非空
        - 非 "N/A"
        - 以 "mp-" 前缀开头
        - 长度大于 3（至少包含 1 个有效数字字符）

        Args:
            material_id: 待验证的材料 ID

        Returns:
            bool: 格式是否有效
        """
        try:
            # 排除空值和占位符
            if material_id is None or material_id == "" or material_id == "N/A":
                return False
            material_id_str = str(material_id)
            # 必须以 "mp-" 开头，且长度大于 3
            return material_id_str.startswith("mp-") and len(material_id_str) > 3
        except (ValueError, TypeError):
            return False

    def verify_material_id_exists(self, material_id: str) -> bool:
        """
        验证 material_id 是否真实存在于 Materials Project 数据库中（通过 API 查询）。

        先检查本地缓存（by_id 和 verify 缓存），
        未命中时通过 Materials Project API 按 ID 查询确认存在性。

        Args:
            material_id (str): 待验证的材料 ID

        Returns:
            bool: 该 ID 是否存在于 MP 数据库
        """
        try:
            # 先做基础格式校验
            if not self.validate_material_id(material_id):
                return False

            # ---- 缓存检查 ----
            global _last_call_time, _call_interval
            now = time.time()
            # 先从 by_id 缓存检查：如果已有该材料的详细信息且无错误，说明存在
            cached_by_id = self._cache["by_id"].get(material_id)
            if cached_by_id and now - cached_by_id[0] < self._ttl_seconds and isinstance(cached_by_id[1], dict) and not cached_by_id[1].get("error"):
                return True
            # 检查 verify 专用缓存
            cached_verify = self._cache["verify"].get(material_id)
            if cached_verify and now - cached_verify[0] < self._ttl_seconds:
                return cached_verify[1]

            # ---- 频率控制等待 ----
            current_time = time.time()
            time_since_last_call = current_time - _last_call_time
            if time_since_last_call < _call_interval:
                time.sleep(_call_interval - time_since_last_call)
            _last_call_time = time.time()

            # ---- API 验证：只请求 material_id 字段以减少数据量 ----
            docs = self.mpr.materials.search(material_ids=[material_id], fields=["material_id"])

            # 如果有返回结果且 material_id 匹配，则存在
            if docs and len(docs) > 0:
                retrieved_material_id = str(getattr(docs[0], "material_id", ""))
                result = retrieved_material_id == material_id
                self._cache["verify"][material_id] = (time.time(), result)
                return result

            # 无结果，缓存 False
            self._cache["verify"][material_id] = (time.time(), False)
            return False
        except Exception as e:
            logger.warning(f"Error verifying material ID: {e}")
            return False

    def get_materials_summary(self,
                             elements: Optional[List[str]] = None,
                             limit: int = 100) -> Dict[str, Any]:
        """
        获取材料摘要信息 —— 比 search_materials 更轻量的查询。

        只返回最基本的材料标识和密度信息，适用于快速浏览。

        Args:
            elements (List[str], optional): 限制元素列表，如 ["Fe"]
            limit (int): 最大返回数量，默认 100

        Returns:
            Dict: 包含 data 和 meta 的摘要信息字典
        """
        try:
            # ---- 构建搜索参数 ----
            kwargs = {}
            if elements:
                kwargs["elements"] = elements

            # ---- 只请求核心字段，提升查询速度 ----
            fields = [
                "material_id",
                "formula_pretty",
                "chemsys",
                "density"
            ]

            # 执行搜索（chunk_size 给定较大的值以一次性获取更多结果）
            docs = self.mpr.materials.search(
                **kwargs,
                chunk_size=min(limit, 1000),
                fields=fields
            )

            # ---- 转换为摘要格式 ----
            materials_data = []
            for doc in docs:
                # 密度附加 g/cm^3 单位
                density_value = getattr(doc, "density", "N/A")
                density_with_unit = f"{density_value} g/cm^3" if density_value != "N/A" else "N/A"

                material_dict = {
                    "material_id": str(getattr(doc, "material_id", "N/A")),
                    "formula": getattr(doc, "formula_pretty", getattr(doc, "formula", "N/A")),
                    "chemsys": getattr(doc, "chemsys", "N/A"),
                    "density": density_with_unit
                }
                materials_data.append(material_dict)

            return {
                "data": materials_data,
                "meta": {
                    "total_count": len(materials_data),
                    "limit": limit
                }
            }

        except Exception as e:
            logger.error(f"Error getting material summary: {e}")
            return {"error": f"Error getting material summary: {str(e)}"}

# ---- 全局单例管理 ----
# 使用模块级变量存储工具实例，避免重复创建（单例模式）

# 全局 MaterialsProjectTool 实例，初始为 None
materials_project_tool = None

def get_materials_project_tool(api_key: Optional[str] = None) -> MaterialsProjectTool:
    """
    获取 Materials Project 工具单例实例。
    首次调用时创建，后续调用返回同一个实例。

    Args:
        api_key (str, optional): Materials Project API 密钥（仅首次创建时使用）

    Returns:
        MaterialsProjectTool: 工具实例
    """
    global materials_project_tool
    if materials_project_tool is None:
        materials_project_tool = MaterialsProjectTool(api_key)
    return materials_project_tool
