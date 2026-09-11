#!/usr/bin/env python3
# 指定 Python 解释器，确保脚本在 Unix 环境下直接执行时使用 python3

"""
Material Identifier Processing Tool.
Unified handling of metal materials and organic compound identifiers (MP-ID and CAS numbers).
"""
# 模块文档字符串：描述本工具的功能——统一处理金属材料和有机化合物的标识符（MP-ID 和 CAS 号）

import logging
# 导入 logging 模块，用于输出警告和错误日志

from typing import Dict, Any, Optional
# 从 typing 模块导入类型注解：Dict（字典）、Any（任意类型）、Optional（可选类型）

from src.tools.materials_project_tool import get_materials_project_tool
# 导入 Materials Project 工具的单例获取函数，用于查询金属材料的 MP-ID

from src.tools.pubchem_tool import get_pubchem_tool
# 导入 PubChem 工具的单例获取函数，用于查询有机化合物的 CAS 号

# Configure logging
logging.basicConfig(level=logging.WARNING)
# 配置日志基本设置：仅输出 WARNING 级别及以上的日志

logger = logging.getLogger(__name__)
# 创建以当前模块名命名的日志记录器，便于在日志中定位问题来源

class MaterialIdentifierTool:
    """Material Identifier Processing Tool - Unified handling of metal and organic material identifiers.
    # 材料标识符处理工具 —— 统一处理金属和有机材料标识符

    Supports identifier processing for multiple material types:
    1. Metal materials (get Materials Project ID)
    # 金属材料 —— 获取 Materials Project ID (MP-ID)
    2. Organic materials (get CAS number)
    # 有机材料 —— 获取 CAS 注册号
    3. Composite materials (identify by element composition)
    # 复合材料 —— 通过元素组成识别
    """

    def __init__(self):
        """Initialize material identifier processing tool."""
        # 初始化材料标识符处理工具实例
        try:
            # 尝试获取 Materials Project 工具实例
            self.materials_project_tool = get_materials_project_tool()
        except Exception as e:
            # 如果 Materials Project 工具不可用（如 API 密钥未配置），记录警告并将属性设为 None
            logger.warning(f"Materials Project tool not available: {e}")
            self.materials_project_tool = None
        # 获取 PubChem 工具实例（通常不需要 API 密钥，所以不会失败）
        self.pubchem_tool = get_pubchem_tool()

    def identify_material(self, query: str) -> Dict[str, Any]:
        """
        Identify material type and get corresponding identifier.
        # 识别材料类型并获取对应的标识符

        Args:
            query (str): Material query string (formula, element combination, or material name)
            # 材料查询字符串（化学式、元素组合或材料名称）

        Returns:
            Dict[str, Any]: Dictionary containing material type and identifier information
            # 包含材料类型和标识符信息的字典
        """
        try:
            # ==================== 初始化结果字典 ====================
            # 构建统一的结果结构，所有字段均预设默认值
            result = {
                "query": query,
                # 原始查询字符串，便于结果追溯
                "material_type": "unknown",
                # 材料类型：metal（金属）、organic（有机）、unknown（未知）
                "identifier": None,
                # 标识符值：MP-ID 或 CAS 号
                "identifier_type": None,
                # 标识符类型：MP-ID 或 CAS
                "additional_info": {},
                # 附加信息字典，存储从数据库返回的额外字段
                "validation_status": "not_found",
                # 验证状态：validated（已验证）、not_found（未找到）、error（错误）
                "is_verified": False
                # 是否已验证标志：True 表示已从可靠数据库获取到标识符
            }

            # ==================== 第一步：确定材料类型 ====================
            # 根据查询字符串的元素组成判断材料属于金属、有机还是未知类型
            material_type = self._determine_material_type(query)
            result["material_type"] = material_type

            # ==================== 第二步：根据材料类型获取标识符 ====================
            # --- 情况 A：金属材料 ---
            if material_type == "metal":
                # 使用 Materials Project 数据库获取金属材料的 MP-ID
                mp_result = self._get_mpid_for_metal(query)
                if mp_result and "material_id" in mp_result:
                    # 成功获取到 MP-ID
                    result["identifier"] = mp_result["material_id"]
                    result["identifier_type"] = "MP-ID"
                    result["additional_info"] = mp_result
                    result["validation_status"] = "validated"
                    result["is_verified"] = True
                else:
                    # 未在 Materials Project 中找到匹配材料
                    result["validation_status"] = "not_found"
                    result["is_verified"] = False
                    logger.info(f"Could not find material in Materials Project: {query}")

            # --- 情况 B：有机材料 ---
            elif material_type == "organic":
                # 使用 PubChem 数据库获取有机化合物的 CAS 号
                cas_result = self._get_cas_for_organic(query)
                if cas_result and "CASNumbers" in cas_result:
                    cas_numbers = cas_result["CASNumbers"]
                    if cas_numbers:
                        # 成功获取到 CAS 号（使用列表中的第一个）
                        result["identifier"] = cas_numbers[0]
                        result["identifier_type"] = "CAS"
                        result["additional_info"] = cas_result
                        result["validation_status"] = "validated"
                        result["is_verified"] = True
                    else:
                        # PubChem 返回了数据但没有 CAS 号
                        result["validation_status"] = "not_found"
                        result["is_verified"] = False
                        logger.info(f"Could not find CAS number in PubChem: {query}")
                else:
                    # PubChem 查询失败
                    result["validation_status"] = "not_found"
                    result["is_verified"] = False
                    logger.info(f"Could not find compound info in PubChem: {query}")

            # --- 情况 C：未知类型（兜底策略） ---
            else:
                # 类型不确定时，依次尝试金属和有机两种数据库
                # 先尝试 Materials Project
                mp_result = self._get_mpid_for_metal(query)
                if mp_result and "material_id" in mp_result:
                    result["identifier"] = mp_result["material_id"]
                    result["identifier_type"] = "MP-ID"
                    result["additional_info"] = mp_result
                    result["material_type"] = "metal"
                    # 回填正确的材料类型
                    result["validation_status"] = "validated"
                    result["is_verified"] = True
                else:
                    # Materials Project 无结果，再尝试 PubChem
                    cas_result = self._get_cas_for_organic(query)
                    if cas_result and "CASNumbers" in cas_result:
                        cas_numbers = cas_result["CASNumbers"]
                        if cas_numbers:
                            result["identifier"] = cas_numbers[0]
                            result["identifier_type"] = "CAS"
                            result["additional_info"] = cas_result
                            result["material_type"] = "organic"
                            # 回填正确的材料类型
                            result["validation_status"] = "validated"
                            result["is_verified"] = True
                        else:
                            result["validation_status"] = "not_found"
                            result["is_verified"] = False
                            logger.info(f"Could not find CAS number in PubChem: {query}")
                    else:
                        # 两个数据库都未找到匹配项
                        result["validation_status"] = "not_found"
                        result["is_verified"] = False
                        logger.info(f"Could not find material in any database: {query}")

            # ==================== 第三步：添加安全警告 ====================
            # 如果标识符未被验证，在结果中附加警告信息，提醒不要使用未验证的数据库标识符
            if not result["is_verified"]:
                result["warning"] = f"Warning: Could not verify identifier for material '{query}'. Do not use unverified database identifiers."

            return result

        except Exception as e:
            # 捕获所有异常，返回包含错误信息的结果字典，避免异常传播至调用方
            logger.error(f"Error identifying material identifier: {e}")
            return {
                "success": False,
                "query": query,
                "error": f"Identification failed: {str(e)}",
                "validation_status": "error",
                # 错误状态下验证状态标记为 error
                "is_verified": False,
                # 错误状态下自然未验证
                "warning": f"Warning: Error occurred while verifying identifier for material '{query}'. Do not use unverified database identifiers."
            }

    def _determine_material_type(self, query: str) -> str:
        """
        Determine material type (metal, organic, or other).
        # 根据查询字符串的元素组成判断材料类型

        Args:
            query (str): Query string

        Returns:
            str: Material type ("metal", "organic", "unknown")
            # 返回 "metal"（金属）、"organic"（有机）或 "unknown"（未知）
        """
        # 第一步：从查询字符串中提取元素符号
        elements = self._extract_elements(query)

        # 第二步：定义常见金属元素列表（包含碱金属、碱土金属、过渡金属、稀土等）
        metal_elements = ['Li', 'Be', 'Na', 'Mg', 'Al', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn',
                         'Ga', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Cs', 'Ba',
                         'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf', 'Ta',
                         'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U',
                         'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr']

        # 第三步：定义常见非金属元素列表（通常构成有机化合物的骨架元素）
        non_metal_elements = ['H', 'C', 'N', 'O', 'F', 'P', 'S', 'Cl', 'Br', 'I']

        # 第四步：计算查询中的金属元素和非金属元素情况
        has_metal = any(element in metal_elements for element in elements)
        # 检查查询中是否包含任意金属元素

        non_metal_count = sum(1 for element in elements if element in non_metal_elements)
        # 统计查询中非金属元素的数量

        total_elements = len(elements)
        # 查询中识别到的元素总数

        # 第五步：判断逻辑
        # 如果包含金属元素，优先判定为金属材料
        if has_metal:
            return "metal"

        # 如果非金属元素占比 >= 50%，判定为有机材料
        if total_elements > 0 and non_metal_count / total_elements >= 0.5:
            return "organic"

        # 以上条件都不满足，返回 unknown（未知类型）
        return "unknown"

    def _extract_elements(self, query: str) -> list:
        """
        Extract element symbols from query string.
        # 从查询字符串中提取化学元素符号

        Args:
            query (str): Query string

        Returns:
            list: List of element symbols
            # 去重后的元素符号列表
        """
        import re
        # 在方法内导入 re，仅在需要时加载，避免不必要的模块初始化

        # 使用正则表达式匹配大写字母 + 可选小写字母（标准元素符号格式）
        elements = re.findall(r'[A-Z][a-z]?', query)

        # 初始化有效元素列表
        valid_elements = []

        # 定义常见化学元素列表（简化版，覆盖常用元素）
        common_elements = ['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar',
                          'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr',
                          'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
                          'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
                          'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn']

        # 过滤：仅保留在已知元素列表中的符号（排除大写字母缩写等非元素字符串）
        for element in elements:
            if element in common_elements:
                valid_elements.append(element)

        # 通过 set 去重后返回列表
        # 注：在某些 Python 版本中需包装为 list(set(...)) 确保返回可变列表
        return list(set(valid_elements))

    def _get_mpid_for_metal(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Get MP-ID for metal material.
        # 为金属材料获取 Materials Project ID

        Args:
            query (str): Query string

        Returns:
            Optional[Dict[str, Any]]: Materials Project data or None
            # 材料数据字典或 None（表示未找到）
        """
        # 如果 Materials Project 工具不可用，直接返回 None
        if not self.materials_project_tool:
            return None

        try:
            # ==================== 策略一：按化学式搜索 ====================
            result = self.materials_project_tool.search_materials(
                formula=query,
                limit=5,
                fields=["material_id", "formula_pretty", "chemsys"]
                # 仅请求必要的字段以提高查询效率
            )
            if "error" not in result and "data" in result and result["data"]:
                # 遍历搜索结果，逐一验证
                for material in result["data"]:
                    material_formula = material.get("formula", "")
                    material_id = material.get("material_id", "")

                    # 验证 MP-ID 是否在 Materials Project 数据库中真实存在
                    if material_id and self.materials_project_tool.verify_material_id_exists(material_id):
                        # 检查化学式是否与查询严格相关（防止返回不相关的材料）
                        if self._is_formula_strictly_related(query, material_formula):
                            logger.info(f"Found related material: {material_formula} (ID: {material_id})")
                            return material
                            # 找到匹配材料，立即返回
                        else:
                            logger.warning(f"Found material but formula mismatch: query '{query}' vs '{material_formula}'")
                    else:
                        logger.warning(f"Found invalid material ID: {material_id}")

            # ==================== 策略二：按元素搜索（降级方案） ====================
            # 如果化学式搜索未找到结果，提取查询中的元素符号重新搜索
            elements = self._extract_elements(query)
            if elements:
                result = self.materials_project_tool.search_materials(
                    elements=elements[:3],
                    # 限制前 3 个元素以避免搜索范围过于宽泛
                    limit=5,
                    fields=["material_id", "formula_pretty", "chemsys"]
                )
                if "error" not in result and "data" in result and result["data"]:
                    for material in result["data"]:
                        # 从化学体系字段中提取材料包含的元素
                        material_elements = material.get("chemsys", "").split("-")
                        material_id = material.get("material_id", "")

                        # 验证 MP-ID 是否真实存在
                        if material_id and self.materials_project_tool.verify_material_id_exists(material_id):
                            # 检查材料元素是否与查询元素严格匹配
                            if self._are_elements_strictly_related(elements, material_elements):
                                logger.info(f"Found material with related elements: {material.get('formula', '')} (ID: {material_id})")
                                return material
                            else:
                                logger.warning(f"Found material but elements mismatch: query '{elements}' vs '{material_elements}'")
                        else:
                            logger.warning(f"Found invalid material ID: {material_id}")

            # 两种策略都失败时，返回 None（不生成假数据，确保数据可靠性）
            logger.info(f"No matching material found in Materials Project for {query}")
            return None
        except Exception as e:
            logger.warning(f"Error getting MP-ID for metal material: {e}")
            # 即使发生异常也返回 None，而不是虚构数据
            return None

    def _is_formula_strictly_related(self, query: str, formula: str) -> bool:
        """
        Strictly check if query and formula are related.
        # 严格检查查询字符串和化学式是否相关

        Args:
            query (str): Query string
            formula (str): Chemical formula

        Returns:
            bool: Whether related
            # True 表示相关，False 表示不相关
        """
        # 提取查询和化学式中的元素集合
        query_elements = set(self._extract_elements(query))
        formula_elements = set(self._extract_elements(formula))

        # 定义主要金属元素列表（用于复合物中有机配体场景的特殊处理）
        # 例如 (FeTCPP)Co(Melm) 这类复合物需要匹配核心金属元素
        main_metal_elements = ['Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Mn', 'Cr', 'V', 'Ti']
        query_metals = [e for e in query_elements if e in main_metal_elements]
        formula_metals = [e for e in formula_elements if e in main_metal_elements]

        # 如果查询和化学式包含相同的主要金属元素，判定为相关
        # 这是为了处理含复杂有机配体的金属配合物
        if query_metals and formula_metals and set(query_metals) == set(formula_metals):
            return True

        # 一般情况：检查共有元素的比例
        # 如果至少有 50% 的查询元素出现在化学式中，判定为相关
        if len(query_elements) > 0:
            common_elements = query_elements.intersection(formula_elements)
            return len(common_elements) / len(query_elements) >= 0.5

        return False

    def _are_elements_strictly_related(self, query_elements: list, material_elements: list) -> bool:
        """
        Strictly check if query elements and material elements are related.
        # 严格检查查询元素和材料元素是否相关

        Args:
            query_elements (list): Query element list
            material_elements (list): Material element list

        Returns:
            bool: Whether related
            # True 表示相关，False 表示不相关
        """
        query_set = set(query_elements)
        material_set = set(material_elements)

        # 检查共有元素的比例是否达到 50% 阈值
        if len(query_set) > 0:
            common_elements = query_set.intersection(material_set)
            return len(common_elements) / len(query_set) >= 0.5

        return False

    def _is_formula_related(self, query: str, formula: str) -> bool:
        """
        Check if query and formula are related.
        # （宽松版）检查查询和化学式是否相关——只要存在共同元素即判定相关

        Args:
            query (str): Query string
            formula (str): Chemical formula

        Returns:
            bool: Whether related
        """
        # 提取查询和化学式中的元素集合
        query_elements = set(self._extract_elements(query))
        formula_elements = set(self._extract_elements(formula))

        # 只要存在至少一个共同元素，即判定为相关（比严格版本更宽松）
        return len(query_elements.intersection(formula_elements)) > 0

    def _are_elements_related(self, query_elements: list, material_elements: list) -> bool:
        """
        Check if query elements and material elements are related.
        # （宽松版）检查查询元素和材料元素是否相关——只要存在共同元素即判定相关

        Args:
            query_elements (list): Query element list
            material_elements (list): Material element list

        Returns:
            bool: Whether related
        """
        query_set = set(query_elements)
        material_set = set(material_elements)

        # 只要存在至少一个共同元素，即判定为相关（比严格版本更宽松）
        return len(query_set.intersection(material_set)) > 0

    def _get_cas_for_organic(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Get CAS number for organic material.
        # 为有机材料获取 CAS 注册号

        Args:
            query (str): Query string

        Returns:
            Optional[Dict[str, Any]]: PubChem data (containing CAS number) or None
            # PubChem 数据字典（包含 CAS 号）或 None
        """
        try:
            # 通过 PubChem 工具查询化合物信息（包含 CAS 注册号）
            result = self.pubchem_tool.get_compound_info_with_cas(query)
            # 检查查询是否成功且返回了化合物数据
            if "error" not in result and "Compound" in result:
                return result["Compound"]
                # 返回化合物信息字典，调用方从中提取 CASNumbers 字段
            return None
        except Exception as e:
            logger.warning(f"Error getting CAS number for organic material: {e}")
            return None
            # 发生异常时返回 None，不伪造数据

# ==================== 全局单例实例管理 ====================
# 使用模块级变量实现懒加载单例模式
_material_identifier_tool = None
# 初始化为 None，第一次调用 get_material_identifier_tool() 时创建实例

def get_material_identifier_tool() -> MaterialIdentifierTool:
    """
    Get material identifier processing tool instance.
    # 获取材料标识符处理工具的单例实例

    Returns:
        MaterialIdentifierTool: Material identifier processing tool instance
    """
    global _material_identifier_tool
    # 声明使用模块级全局变量

    if _material_identifier_tool is None:
        # 懒加载：仅在首次调用时创建实例
        _material_identifier_tool = MaterialIdentifierTool()
    return _material_identifier_tool
    # 返回单例实例，确保全局只有一个工具实例，节省资源
