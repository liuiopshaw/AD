#!/usr/bin/env python3
"""
Structure Validator Tool - 材料结构验证工具
验证材料结构是否真实存在于已知数据库中。
Validate if material structure actually exists.
"""

import logging
from typing import Dict, Any
# 导入 Materials Project 工具，用于查询金属/无机材料数据库
from src.tools.materials_project_tool import get_materials_project_tool
# 导入 PubChem 工具，用于查询有机化合物数据库
from src.tools.pubchem_tool import get_pubchem_tool
# 导入材料类型识别工具，用于自动判断材料属于金属还是有机物
from src.tools.material_identifier_tool import get_material_identifier_tool

# 配置日志记录：设置默认日志级别为 WARNING，避免过多调试信息输出
logging.basicConfig(level=logging.WARNING)
# 创建当前模块的日志记录器实例
logger = logging.getLogger(__name__)

class StructureValidatorTool:
    """结构验证工具类 - 验证材料结构是否真实存在。

    支持多种材料类型的结构验证：
    1. 金属材料（使用 Materials Project 数据库进行验证）
    2. 有机材料（使用 PubChem 数据库进行验证）
    3. 复合材料（通过元素组成进行验证）
    """

    def __init__(self):
        """初始化结构验证工具。
        在初始化时加载所有需要的子工具（Materials Project、PubChem、材料识别工具）。
        Materials Project 工具可能因为 API Key 未配置而初始化失败，此时记为不可用但不阻塞。
        """
        try:
            # 尝试获取 Materials Project 工具实例（需要 API Key）
            self.materials_project_tool = get_materials_project_tool()
        except Exception as e:
            # 如果 Materials Project 不可用（如缺少 API Key），记录警告并设为 None
            logger.warning(f"Materials Project tool not available: {e}")
            self.materials_project_tool = None
        # PubChem 工具无需 API Key，直接获取
        self.pubchem_tool = get_pubchem_tool()
        # 材料类型识别工具，用于自动判断查询是金属还是有机物
        self.identifier_tool = get_material_identifier_tool()

    def validate_structure_exists(self, material_formula: str) -> Dict[str, Any]:
        """
        验证材料结构是否真实存在（核心方法）。

        验证流程：
        1. 先通过识别工具判断材料类型（金属/有机/未知）
        2. 根据材料类型选择对应的数据库进行查询
        3. 对未知类型，依次尝试两种数据库
        4. 返回包含验证置信度和强制操作标识的完整结果

        Args:
            material_formula (str): 材料的化学式或名称

        Returns:
            Dict[str, Any]: 验证结果字典，包含以下字段：
                - query: 原始查询字符串
                - valid: 验证是否通过
                - type: 材料类型
                - data: 查询到的数据
                - source: 数据来源
                - reason: 结果说明
                - validation_confidence: 验证置信度 (low/high)
                - mandatory_action_required: 是否需要强制操作
        """
        try:
            # 构建初始结果字典，设置默认值为"未通过验证"
            result = {
                "query": material_formula,
                "valid": False,              # 默认未通过验证
                "type": "unknown",           # 默认未知类型
                "data": None,                # 默认无数据
                "source": None,              # 默认无来源
                "reason": None,              # 默认无原因说明
                "validation_confidence": "low"  # 默认低置信度
            }

            # 第一步：通过识别工具确定材料类型（金属/有机）
            if self.identifier_tool:
                # 调用材料识别工具进行类型判断
                identification = self.identifier_tool.identify_material(material_formula)
                material_type = identification.get("material_type", "unknown")
                result["type"] = material_type

                # 检查识别工具是否已经验证过该材料
                validation_status = identification.get("validation_status", "not_found")
                is_verified = identification.get("is_verified", False)
                if validation_status == "validated" and is_verified:
                    # 如果识别工具已验证通过，即可设为高置信度
                    result["validation_confidence"] = "high"
                    result["reason"] = f"Material type verified as {material_type} by identifier tool"
                    # 记录识别工具提供的标识符信息（如 CAS 号）
                    result["identifier"] = identification.get("identifier")
                    result["identifier_type"] = identification.get("identifier_type")
                elif validation_status == "not_found":
                    # 识别工具未找到匹配材料
                    result["reason"] = f"Identifier tool could not find matching {material_type} material"
                else:
                    # 识别工具验证过程出错
                    result["reason"] = f"Identifier tool verification failed: {identification.get('error', 'unknown error')}"
            else:
                # 如果识别工具不可用，使用简单的元素分析方法判断类型
                material_type = self._simple_determine_material_type(material_formula)
                result["type"] = material_type
                result["reason"] = "Identifier tool not available, using simple judgment"

            # 第二步：根据材料类型选择对应的验证数据库
            if material_type == "metal":
                # 金属材料：使用 Materials Project 数据库验证
                validation_result = self._validate_metal_structure(material_formula)
                result.update(validation_result)
                # 更新验证置信度
                if validation_result["valid"]:
                    result["validation_confidence"] = "high"
                else:
                    result["validation_confidence"] = "low"
            elif material_type == "organic":
                # 有机材料：使用 PubChem 数据库验证
                validation_result = self._validate_organic_structure(material_formula)
                result.update(validation_result)
                # 更新验证置信度
                if validation_result["valid"]:
                    result["validation_confidence"] = "high"
                else:
                    result["validation_confidence"] = "low"
            else:
                # 未知类型：依次尝试两种数据库，任一通过即可
                metal_result = self._validate_metal_structure(material_formula)
                if metal_result["valid"]:
                    result.update(metal_result)
                    result["validation_confidence"] = "high"
                else:
                    organic_result = self._validate_organic_structure(material_formula)
                    result.update(organic_result)
                    if organic_result["valid"]:
                        result["validation_confidence"] = "high"
                    else:
                        result["validation_confidence"] = "low"

            # 第三步：设置强制操作标记
            # 如果验证未通过，标记为需要强制操作（如重新设计或补充实验数据）
            if not result["valid"]:
                result["mandatory_action_required"] = True
                result["action_description"] = "Material structure failed validation, needs redesign or more experimental data support"
            else:
                result["mandatory_action_required"] = False

            return result

        except Exception as e:
            # 捕获所有异常，返回错误结果而不是抛出异常
            logger.error(f"Error validating material structure: {e}")
            return {
                "query": material_formula,
                "valid": False,
                "type": "unknown",
                "data": None,
                "source": None,
                "reason": f"Error during validation: {str(e)}",
                "validation_confidence": "low",
                "mandatory_action_required": True,
                "action_description": f"Error occurred during validation: {str(e)}, manual check required"
            }

    def _validate_metal_structure(self, formula: str) -> Dict[str, Any]:
        """
        通过 Materials Project 数据库验证金属材料结构。

        验证策略：
        1. 先按化学式精确搜索
        2. 如果精确搜索失败，则按组成元素搜索相似材料
        3. 两种方式均失败则判定为不存在

        Args:
            formula (str): 化学式

        Returns:
            Dict[str, Any]: 验证结果
        """
        # 如果 Materials Project 工具不可用，直接返回失败
        if not self.materials_project_tool:
            return {
                "valid": False,
                "type": "metal",
                "data": None,
                "source": None,
                "reason": "Materials Project tool not available"
            }

        try:
            # 策略1：按化学式精确搜索，limit=1 只取最匹配的一条
            search_result = self.materials_project_tool.search_materials(formula=formula, limit=1)
            if "error" not in search_result and "data" in search_result and search_result["data"]:
                # 找到匹配材料，返回成功
                material = search_result["data"][0]
                return {
                    "valid": True,
                    "type": "metal",
                    "data": material,
                    "source": "Materials Project",
                    "reason": "Found matching material structure in Materials Project"
                }

            # 策略2：化学式搜索失败，尝试按组成元素搜索
            # 从化学式中提取元素符号（如 Fe2O3 -> [Fe, O]）
            elements = self._extract_elements(formula)
            if elements:
                # 取前两个元素进行搜索（大多数材料由2-3种元素组成，取前两个覆盖范围最广）
                element_result = self.materials_project_tool.search_materials(elements=elements[:2], limit=1)
                if "error" not in element_result and "data" in element_result and element_result["data"]:
                    material = element_result["data"][0]
                    return {
                        "valid": True,
                        "type": "metal",
                        "data": material,
                        "source": "Materials Project",
                        "reason": "Found material structure with same elements in Materials Project"
                    }

            # 两种策略均未找到匹配，返回验证失败
            return {
                "valid": False,
                "type": "metal",
                "data": None,
                "source": None,
                "reason": f"No material with formula {formula} found in Materials Project or found material ID is invalid"
            }
        except Exception as e:
            # 捕获查询过程中的异常，返回失败结果
            logger.warning(f"Error validating metal material structure: {e}")
            return {
                "valid": False,
                "type": "metal",
                "data": None,
                "source": None,
                "reason": f"Error validating metal material: {str(e)}"
            }

    def _validate_organic_structure(self, formula: str) -> Dict[str, Any]:
        """
        通过 PubChem 数据库验证有机材料结构。

        对于有机化合物，PubChem 是最权威的公开数据库。
        该方法通过调用 PubChem 工具的搜索功能来验证。

        Args:
            formula (str): 化学式或化合物名称

        Returns:
            Dict[str, Any]: 验证结果
        """
        try:
            # 使用 PubChem 工具搜索化合物
            compound_info = self.pubchem_tool.search_compound(formula)
            if "error" not in compound_info:
                # 返回结果中不含 error 字段，说明查询成功
                return {
                    "valid": True,
                    "type": "organic",
                    "data": compound_info,
                    "source": "PubChem",
                    "reason": "Found matching compound structure in PubChem"
                }
            else:
                # PubChem 返回了错误，说明未找到匹配化合物
                return {
                    "valid": False,
                    "type": "organic",
                    "data": None,
                    "source": None,
                    "reason": f"No compound with formula {formula} found in PubChem"
                }
        except Exception as e:
            # 捕获查询异常
            logger.warning(f"Error validating organic compound structure: {e}")
            return {
                "valid": False,
                "type": "organic",
                "data": None,
                "source": None,
                "reason": f"Error validating organic compound: {str(e)}"
            }

    def _simple_determine_material_type(self, query: str) -> str:
        """
        简单的材料类型判定方法（当识别工具不可用时的备选方案）。

        判定逻辑：
        1. 提取化学式中的所有元素符号
        2. 如果包含金属元素 -> 金属材料
        3. 如果主要由非金属元素组成 -> 有机材料
        4. 其他情况 -> 未知类型

        Args:
            query (str): 查询字符串（通常是化学式）

        Returns:
            str: 材料类型 ("metal", "organic", "unknown")
        """
        # 从查询字符串中提取所有元素符号
        elements = self._extract_elements(query)

        # 常见金属元素列表（共74种金属元素）
        metal_elements = ['Li', 'Be', 'Na', 'Mg', 'Al', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn',
                         'Ga', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Cs', 'Ba',
                         'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf', 'Ta',
                         'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U',
                         'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr']

        # 常见非金属元素列表（通常构成有机化合物的元素）
        non_metal_elements = ['H', 'C', 'N', 'O', 'F', 'P', 'S', 'Cl', 'Br', 'I']

        # 检查是否包含任意金属元素
        has_metal = any(element in metal_elements for element in elements)

        # 统计非金属元素的数量
        non_metal_count = sum(1 for element in elements if element in non_metal_elements)
        total_elements = len(elements)

        # 判定规则1：如果含有金属元素，视为金属材料
        if has_metal:
            return "metal"

        # 判定规则2：如果非金属元素占比 >= 50%，视为有机材料
        if total_elements > 0 and non_metal_count / total_elements >= 0.5:
            return "organic"

        # 判定规则3：其他情况返回未知类型
        return "unknown"

    def _extract_elements(self, query: str) -> list:
        """
        从查询字符串中提取元素符号。

        使用正则表达式匹配化学式中的元素符号。
        元素符号规则：首字母大写，可选一个小写字母（如 Fe, Na, Cl）。
        提取后对照已知元素列表进行过滤，去除误识别的字符串。

        Args:
            query (str): 查询字符串（如 "Fe2O3", "TiO2", "NaCl"）

        Returns:
            list: 去重后的有效元素符号列表
        """
        import re
        # 正则匹配：大写字母开头，可选一个小写字母（匹配所有可能的元素符号格式）
        elements = re.findall(r'[A-Z][a-z]?', query)
        # 过滤掉不在已知元素列表中的字符串
        valid_elements = []
        # 已知元素符号列表（前103号元素，简化版）
        common_elements = ['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar',
                          'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr',
                          'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
                          'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
                          'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn']

        # 遍历所有匹配结果，仅保留在已知元素列表中的
        for element in elements:
            if element in common_elements:
                valid_elements.append(element)

        # 使用 set 去重后返回列表（同一元素可能多次出现，如 CaCO3 中的 C）
        return list(set(valid_elements))  # 去重

# 全局单例变量：确保结构验证工具在应用中只创建一次
_structure_validator_tool = None

def get_structure_validator_tool() -> StructureValidatorTool:
    """
    获取结构验证工具的单例实例。

    使用懒加载模式：第一次调用时创建实例，后续调用返回同一个实例。
    这样既节省资源（避免重复初始化连接），又保证状态一致性。

    Returns:
        StructureValidatorTool: 结构验证工具实例
    """
    global _structure_validator_tool
    if _structure_validator_tool is None:
        _structure_validator_tool = StructureValidatorTool()
    return _structure_validator_tool
