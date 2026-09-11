#!/usr/bin/env python3
"""
工具调用规格模块 (Tool Call Specification Module)
为每个 Agent 定义其所需的工具清单和工具调用验证逻辑。

设计目的：
- 集中管理每个 Agent 需要调用哪些工具
- 提供统一的结果验证接口，确保工具返回的数据符合预期格式
- 支持上下文缓存复用，避免重复调用外部 API
"""

# 日志记录模块，用于在验证失败时输出警告信息
import logging
# typing 模块用于类型注解，提高代码可读性和 IDE 支持
from typing import Dict, Any, List


# =============================================================================
# 延迟导入的工具获取函数
# 使用延迟导入（lazy import）模式避免循环导入问题。
# 各模块之间的依赖关系复杂，在函数内部导入可以打破循环依赖链。
# =============================================================================

def get_material_identifier_tool():
    """
    获取材料标识工具实例（延迟导入）。

    在函数内部导入以避免模块级循环依赖：
    tool_call_spec -> material_identifier_tool -> 其他模块 -> tool_call_spec
    """
    from src.tools.material_identifier_tool import get_material_identifier_tool as _get_material_identifier_tool
    return _get_material_identifier_tool()

def get_structure_validator_tool():
    """
    获取结构验证工具实例（延迟导入）。
    延迟导入避免与 structure_validator_tool 模块之间的循环依赖。
    """
    from src.tools.structure_validator_tool import get_structure_validator_tool as _get_structure_validator_tool
    return _get_structure_validator_tool()

def get_materials_project_tool():
    """
    获取 Materials Project 数据库查询工具实例（延迟导入）。
    Materials Project 是一个材料科学数据库，用于查询无机晶体结构数据。
    """
    from src.tools.materials_project_tool import get_materials_project_tool as _get_materials_project_tool
    return _get_materials_project_tool()

def get_pubchem_tool():
    """
    获取 PubChem 数据库查询工具实例（延迟导入）。
    PubChem 是美国国立卫生研究院 (NIH) 的化学分子数据库，用于查询有机化合物信息。
    """
    from src.tools.pubchem_tool import get_pubchem_tool as _get_pubchem_tool
    return _get_pubchem_tool()

# 配置本模块的日志记录器
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class ToolCallSpec:
    """
    工具调用规格基类。

    提供所有 Agent 共享的工具结果验证方法。
    每个验证方法检查工具返回结果是否符合预期的格式和内容要求。
    子类可以继承这些验证方法并添加 Agent 特定的验证逻辑。
    """

    @staticmethod
    def validate_material_identifier_result(result: Dict[str, Any]) -> bool:
        """
        验证材料标识工具返回结果的完整性和有效性。

        验证步骤：
        1. 确认结果是字典类型
        2. 检查所有必需字段是否存在
        3. 确认验证状态通过（is_verified 为 True）

        Args:
            result: 材料标识工具返回的结果字典

        Returns:
            bool: 验证是否通过。True 表示结果格式正确且内容有效
        """
        # 第一步：基本类型检查——结果必须是字典类型
        if not isinstance(result, dict):
            return False

        # 第二步：检查所有必需的字段是否都存在
        # query: 原始查询字符串, material_type: 材料类型(metal/organic)
        # identifier: 材料标识符(如化学式), identifier_type: 标识符类型
        # validation_status: 验证状态, is_verified: 是否已验证通过
        required_fields = ["query", "material_type", "identifier", "identifier_type", "validation_status", "is_verified"]
        for field in required_fields:
            if field not in result:
                # 缺少必需字段时记录警告日志，帮助开发者定位数据问题
                logger.warning(f"Material identifier result missing required field: {field}")
                return False

        # 第三步：确认材料标识验证已通过
        # is_verified 为 True 表示工具已确认该材料标识符是有效的
        # 使用 .get() 安全获取值，默认 False 避免 KeyError
        if result.get("is_verified", False) is not True:
            logger.warning(f"Material identifier validation failed: {result.get('query', 'Unknown')}")
            return False

        return True

    @staticmethod
    def validate_structure_validator_result(result: Dict[str, Any]) -> bool:
        """
        验证结构验证工具返回结果的完整性和有效性。

        验证步骤：
        1. 确认结果是字典类型
        2. 检查所有必需字段是否存在
        3. 确认结构有效 (valid 为 True)
        4. 确认验证置信度为 high（高置信度）

        Args:
            result: 结构验证工具返回的结果字典

        Returns:
            bool: 验证是否通过
        """
        # 基本类型检查
        if not isinstance(result, dict):
            return False

        # 检查必需字段：
        # query: 查询的材料化学式, valid: 结构是否有效
        # type: 材料类型, source: 数据来源, reason: 验证结论原因
        # validation_confidence: 验证置信度 (high/medium/low)
        required_fields = ["query", "valid", "type", "source", "reason", "validation_confidence"]
        for field in required_fields:
            if field not in result:
                logger.warning(f"Structure validation result missing required field: {field}")
                return False

        # 确认结构被判定为有效
        if result.get("valid", False) is not True:
            logger.warning(f"Material structure validation failed: {result.get('query', 'Unknown')}")
            return False

        # 确认验证置信度为 "high"（高置信度才认为可靠）
        # 如果置信度是 "low" 或 "medium"，说明数据来源不够权威或存在不确定性
        if result.get("validation_confidence", "low") != "high":
            logger.warning(f"Material structure validation confidence insufficient: {result.get('query', 'Unknown')}")
            return False

        return True

    @staticmethod
    def validate_materials_project_result(result: Dict[str, Any]) -> bool:
        """
        验证 Materials Project 工具返回结果的完整性和有效性。

        Materials Project 专门用于查询无机晶体材料（如金属合金、陶瓷等）的电子结构、
        热力学性质等数据。

        验证步骤：
        1. 确认结果是字典类型
        2. 检查是否有 error 字段（即 API 返回了错误）
        3. 确认 data 字段存在且非空

        Args:
            result: Materials Project 工具返回的结果字典

        Returns:
            bool: 验证是否通过
        """
        # 基本类型检查
        if not isinstance(result, dict):
            return False

        # 检查 API 是否返回了错误
        # 如果 result 中包含 "error" 键，说明外部 API 调用失败
        if "error" in result:
            logger.warning(f"Materials Project tool returned error: {result['error']}")
            return False

        # 确认返回结果中包含 data 字段
        # data 字段通常是一个字典列表，每个元素代表一个查询到的材料条目
        if "data" not in result:
            logger.warning("Materials Project result missing data field")
            return False

        # 确认 data 字段不为空（即确实查到了数据）
        # 空的 data 表示没有匹配的材料，这也是验证失败的情况
        if not result["data"]:
            logger.warning("Materials Project returned empty data")
            return False

        return True

    @staticmethod
    def validate_pubchem_result(result: Dict[str, Any]) -> bool:
        """
        验证 PubChem 工具返回结果的完整性和有效性。

        PubChem 用于查询有机化合物信息，返回的结构包含 PropertyTable.Properties。

        验证步骤：
        1. 确认结果是字典类型
        2. 检查是否有 error 字段
        3. 逐级检查 PropertyTable -> Properties 的结构完整性
        4. 确认 Properties 数据非空

        Args:
            result: PubChem 工具返回的结果字典

        Returns:
            bool: 验证是否通过
        """
        # 基本类型检查
        if not isinstance(result, dict):
            return False

        # 检查 API 是否返回了错误
        if "error" in result:
            logger.warning(f"PubChem tool returned error: {result['error']}")
            return False

        # 检查 PubChem 返回结果的顶层结构：必须包含 PropertyTable
        # PropertyTable 是 PubChem API 的标准返回结构
        if "PropertyTable" not in result:
            logger.warning("PubChem result missing PropertyTable field")
            return False

        # 检查 PropertyTable 中是否包含 Properties 字段
        # Properties 是一个列表，每个元素是一个包含化合物属性的字典
        if "Properties" not in result["PropertyTable"]:
            logger.warning("PubChem result missing Properties field")
            return False

        # 确认 Properties 列表不为空
        # 空的 Properties 表示没有查询到化合物数据
        if not result["PropertyTable"]["Properties"]:
            logger.warning("PubChem returned empty Properties data")
            return False

        return True


class MaterialDesignerToolSpec(ToolCallSpec):
    """
    材料设计专家 (Material Designer Expert) 的工具调用规格。

    该 Agent 负责根据材料化学式进行材料特性检索和验证，
    并设计合成方案。
    需要调用材料标识、结构验证、Materials Project 和 PubChem 等工具。
    """

    @staticmethod
    def validate_tool_usage(material_formula: str) -> Dict[str, Any]:
        """
        验证材料设计专家的工具调用流程。

        执行完整的工作流：
        1. 调用材料标识工具，识别材料类型（金属/有机）
        2. 调用结构验证工具，确认材料结构有效
        3. 根据材料类型调用相应的数据库工具（金属->Materials Project, 有机->PubChem）

        优化策略：
        - 优先从全局上下文缓存 (ContextStore) 读取已有结果，避免重复 API 调用
        - 当结构验证工具通过 Materials Project 返回数据时，直接复用其结果

        Args:
            material_formula: 材料化学式，如 "SiO2", "TiO2"

        Returns:
            包含验证结果的字典，结构为：
            {
                "material_formula": str,      # 输入的材料化学式
                "validation_passed": bool,    # 整体验证是否通过
                "errors": List[str],          # 错误信息列表
                "tool_calls": Dict            # 各工具返回结果
            }
        """
        # 初始化返回结果字典，设置默认状态为通过
        result = {
            "material_formula": material_formula,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- 从全局上下文缓存加载已有结果 ----
            # 如果之前的 Agent 已经调用过相同工具并存储了结果，直接复用
            # 这避免了重复的外部 API 调用，提高了效率
            try:
                from src.utils.context_store import ContextStore
                cached_identifier = ContextStore.get(f"material_identifier:{material_formula}")
                cached_validator = ContextStore.get(f"structure_validator:{material_formula}")
                cached_mp = ContextStore.get(f"materials_project_search:{material_formula}")
            except Exception:
                # ContextStore 不可用时（如测试环境），所有缓存设为 None
                cached_identifier = None
                cached_validator = None
                cached_mp = None

            # ---- 步骤1：调用材料标识工具 ----
            identifier_tool = get_material_identifier_tool()
            # 优先使用缓存，缓存不可用时调用工具的 identify_material 方法
            identifier_result = cached_identifier or identifier_tool.identify_material(material_formula)
            # 记录工具调用结果
            result["tool_calls"]["material_identifier"] = identifier_result

            # 验证材料标识结果的完整性和有效性
            if not ToolCallSpec.validate_material_identifier_result(identifier_result):
                result["validation_passed"] = False
                result["errors"].append("Material identifier validation failed")

            # ---- 步骤2：调用结构验证工具 ----
            validator_tool = get_structure_validator_tool()
            # 优先使用缓存中的结构验证结果
            validator_result = cached_validator or validator_tool.validate_structure_exists(material_formula)
            result["tool_calls"]["structure_validator"] = validator_result

            # 验证结构验证结果
            if not ToolCallSpec.validate_structure_validator_result(validator_result):
                result["validation_passed"] = False
                result["errors"].append("Structure validation failed")

            # ---- 步骤3：根据材料类型调用相应的数据库工具 ----
            # 从材料标识工具的结果中获取材料类型，默认为 "unknown"
            material_type = identifier_result.get("material_type", "unknown")

            if material_type == "metal":
                # 金属材料 -> 使用 Materials Project 数据库
                mp_tool = get_materials_project_tool()

                # 优先使用缓存中已有的 Materials Project 查询结果
                if cached_mp and isinstance(cached_mp, dict) and cached_mp.get("data"):
                    mp_result = cached_mp
                else:
                    # 缓存不可用时的查询策略（按优先级递减）：

                    # 策略1：复用结构验证工具返回的 Materials Project 数据
                    # 如果结构验证工具已经从 Materials Project 获取了数据且验证通过，
                    # 直接将其作为 Materials Project 的查询结果，避免重复调用同一 API
                    validator_data = result["tool_calls"].get("structure_validator", {})
                    if isinstance(validator_data, dict) and validator_data.get("valid") and validator_data.get("source") == "Materials Project" and validator_data.get("data"):
                        mp_result = {
                            "data": [validator_data["data"]],
                            "meta": {"total_count": 1, "limit": 1}
                        }
                    else:
                        # 策略2：使用材料标识符中的 material_id 进行精确查询
                        # material_id 是 Materials Project 中的唯一标识符，通过它获取详细数据
                        add_info = identifier_result.get("additional_info") or {}
                        material_id = add_info.get("material_id")
                        if material_id and mp_tool.validate_material_id(material_id):
                            # 验证 material_id 有效后，调用 get_material_by_id 获取材料详情
                            detail = mp_tool.get_material_by_id(material_id)
                            mp_result = {"data": [detail] if "error" not in detail else [], "meta": {"total_count": 1, "limit": 1}}
                        else:
                            # 策略3：使用化学式进行关键词搜索（兜底策略）
                            # 设定查询上限为5条，只请求 material_id 和 formula_pretty 字段
                            mp_result = mp_tool.search_materials(formula=material_formula, limit=5, fields=["material_id", "formula_pretty"])

                # 记录工具调用结果并验证
                result["tool_calls"]["materials_project"] = mp_result
                if not ToolCallSpec.validate_materials_project_result(mp_result):
                    result["validation_passed"] = False
                    result["errors"].append("Materials Project data validation failed")

            elif material_type == "organic":
                # 有机材料 -> 使用 PubChem 数据库
                pubchem_tool = get_pubchem_tool()
                # 调用 PubChem 的 search_compound 方法查询化合物信息
                pubchem_result = pubchem_tool.search_compound(material_formula)
                result["tool_calls"]["pubchem"] = pubchem_result

                # 验证 PubChem 查询结果
                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append("PubChem data validation failed")

        except Exception as e:
            # 捕获工具调用过程中的所有异常
            # 记录错误并标记验证失败，但不会中断程序（优雅降级）
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Material designer expert tool call validation failed: {e}")

        return result


class AssessmentExpertToolSpec(ToolCallSpec):
    """
    评估专家 (Assessment Expert) 的工具调用规格。

    评估专家负责对材料设计结果进行评估和筛选，比材料设计专家多了
    PNEC Tool 和 Data Validator Tool。工作流与材料设计专家类似，
    但额外需要进行安全性评估和数据验证。
    """

    @staticmethod
    def validate_tool_usage(material_formula: str) -> Dict[str, Any]:
        """
        验证评估专家的工具调用流程。

        工作流与 MaterialDesignerToolSpec 基本一致：
        1. 材料标识 -> 2. 结构验证 -> 3. 数据库查询

        额外的工具（PNEC, Data Validator）的验证逻辑可以由子类或外部逻辑补充。

        Args:
            material_formula: 材料化学式

        Returns:
            包含验证结果的字典
        """
        # 初始化返回结果
        result = {
            "material_formula": material_formula,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- 从全局上下文缓存加载已有结果 ----
            # 复用之前 Agent 已查询的数据，减少 API 调用开销
            try:
                from src.utils.context_store import ContextStore
                cached_identifier = ContextStore.get(f"material_identifier:{material_formula}")
                cached_validator = ContextStore.get(f"structure_validator:{material_formula}")
                cached_mp = ContextStore.get(f"materials_project_search:{material_formula}")
            except Exception:
                cached_identifier = None
                cached_validator = None
                cached_mp = None

            # ---- 步骤1：材料标识 ----
            identifier_tool = get_material_identifier_tool()
            identifier_result = cached_identifier or identifier_tool.identify_material(material_formula)
            result["tool_calls"]["material_identifier"] = identifier_result

            if not ToolCallSpec.validate_material_identifier_result(identifier_result):
                result["validation_passed"] = False
                result["errors"].append("Material identifier validation failed")

            # ---- 步骤2：结构验证 ----
            validator_tool = get_structure_validator_tool()
            validator_result = cached_validator or validator_tool.validate_structure_exists(material_formula)
            result["tool_calls"]["structure_validator"] = validator_result

            if not ToolCallSpec.validate_structure_validator_result(validator_result):
                result["validation_passed"] = False
                result["errors"].append("Structure validation failed")

            # ---- 步骤3：数据库查询（按材料类型区分） ----
            material_type = identifier_result.get("material_type", "unknown")
            if material_type == "metal":
                mp_tool = get_materials_project_tool()

                # 查询策略：缓存 > 结构验证复用 > material_id 精确查询 > 化学式搜索
                if cached_mp and isinstance(cached_mp, dict) and cached_mp.get("data"):
                    mp_result = cached_mp
                else:
                    validator_data = result["tool_calls"].get("structure_validator", {})
                    if isinstance(validator_data, dict) and validator_data.get("valid") and validator_data.get("source") == "Materials Project" and validator_data.get("data"):
                        mp_result = {
                            "data": [validator_data["data"]],
                            "meta": {"total_count": 1, "limit": 1}
                        }
                    else:
                        add_info = identifier_result.get("additional_info") or {}
                        material_id = add_info.get("material_id")
                        if material_id and mp_tool.validate_material_id(material_id):
                            detail = mp_tool.get_material_by_id(material_id)
                            mp_result = {"data": [detail] if "error" not in detail else [], "meta": {"total_count": 1, "limit": 1}}
                        else:
                            mp_result = mp_tool.search_materials(formula=material_formula, limit=5, fields=["material_id", "formula_pretty"])

                result["tool_calls"]["materials_project"] = mp_result
                if not ToolCallSpec.validate_materials_project_result(mp_result):
                    result["validation_passed"] = False
                    result["errors"].append("Materials Project data validation failed")

            elif material_type == "organic":
                # 调用 PubChem 工具查询有机化合物数据
                pubchem_tool = get_pubchem_tool()
                pubchem_result = pubchem_tool.search_compound(material_formula)
                result["tool_calls"]["pubchem"] = pubchem_result

                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append("PubChem data validation failed")

        except Exception as e:
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Assessment expert tool call validation failed: {e}")

        return result


class FinalValidatorToolSpec(ToolCallSpec):
    """
    最终验证专家 (Final Validator Expert) 的工具调用规格。

    最终验证专家是流程的最后一道关卡，负责对所有前置步骤的结果进行综合验证。
    它拥有最完整的工具清单，包括额外的属性查询工具和材料搜索工具。

    与前面的 Agent 不同，FinalValidator 不使用上下文缓存，
    而是独立地重新调用所有工具以确保数据的最终一致性。
    """

    @staticmethod
    def validate_tool_usage(material_formula: str) -> Dict[str, Any]:
        """
        验证最终验证专家的工具调用流程。

        与 MaterialDesigner 和 Assessment 专家不同，
        最终验证专家不依赖缓存，每次都独立调用所有工具以确保数据准确性。
        这保证了最终输出结果的可信度，即使可能增加额外的 API 调用成本。

        Args:
            material_formula: 材料化学式

        Returns:
            包含验证结果的字典
        """
        # 初始化返回结果
        result = {
            "material_formula": material_formula,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- 步骤1：直接调用材料标识工具（不使用缓存） ----
            # 不使用缓存的原因：最终验证需要最权威和最新鲜的数据
            identifier_tool = get_material_identifier_tool()
            identifier_result = identifier_tool.identify_material(material_formula)
            result["tool_calls"]["material_identifier"] = identifier_result

            if not ToolCallSpec.validate_material_identifier_result(identifier_result):
                result["validation_passed"] = False
                result["errors"].append("Material identifier validation failed")

            # ---- 步骤2：直接调用结构验证工具（不使用缓存） ----
            validator_tool = get_structure_validator_tool()
            validator_result = validator_tool.validate_structure_exists(material_formula)
            result["tool_calls"]["structure_validator"] = validator_result

            if not ToolCallSpec.validate_structure_validator_result(validator_result):
                result["validation_passed"] = False
                result["errors"].append("Structure validation failed")

            # ---- 步骤3：数据库查询（按材料类型区分） ----
            # 注意：FinalValidator 也不使用 ContextStore 缓存
            material_type = identifier_result.get("material_type", "unknown")
            if material_type == "metal":
                mp_tool = get_materials_project_tool()

                # 查询策略（按优先级）：
                # 1. 复用结构验证工具中来自 Materials Project 的数据
                # 2. 使用 material_id 精确查询
                # 3. 化学式关键词搜索（兜底）
                validator_data = result["tool_calls"].get("structure_validator", {})
                if isinstance(validator_data, dict) and validator_data.get("valid") and validator_data.get("source") == "Materials Project" and validator_data.get("data"):
                    mp_result = {
                        "data": [validator_data["data"]],
                        "meta": {"total_count": 1, "limit": 1}
                    }
                else:
                    add_info = identifier_result.get("additional_info") or {}
                    material_id = add_info.get("material_id")
                    if material_id and mp_tool.validate_material_id(material_id):
                        detail = mp_tool.get_material_by_id(material_id)
                        mp_result = {"data": [detail] if "error" not in detail else [], "meta": {"total_count": 1, "limit": 1}}
                    else:
                        mp_result = mp_tool.search_materials(formula=material_formula, limit=5, fields=["material_id", "formula_pretty"])

                result["tool_calls"]["materials_project"] = mp_result
                if not ToolCallSpec.validate_materials_project_result(mp_result):
                    result["validation_passed"] = False
                    result["errors"].append("Materials Project data validation failed")

            elif material_type == "organic":
                pubchem_tool = get_pubchem_tool()
                pubchem_result = pubchem_tool.search_compound(material_formula)
                result["tool_calls"]["pubchem"] = pubchem_result

                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append("PubChem data validation failed")

        except Exception as e:
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Final validator expert tool call validation failed: {e}")

        return result


class MechanismExpertToolSpec(ToolCallSpec):
    """
    机制分析专家的工具调用规格。

    机制分析专家 (Mechanism Analysis Expert) 专注于分析材料的物理化学机制，
    所需工具较少，主要依赖 Materials Project 和 PubChem 进行数据查询。
    相比设计/评估专家，机制分析专家不需要结构验证工具。
    """

    @staticmethod
    def validate_tool_usage(material_formula: str) -> Dict[str, Any]:
        """
        验证机制分析专家的工具调用流程。

        工作流比设计/评估专家简洁：
        1. 通过材料标识确定材料类型
        2. 直接根据类型调用对应的数据库工具

        注意：机制分析专家不进行结构验证。

        Args:
            material_formula: 材料化学式

        Returns:
            包含验证结果的字典
        """
        # 初始化返回结果
        result = {
            "material_formula": material_formula,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- 从上下文缓存加载已有结果 ----
            try:
                from src.utils.context_store import ContextStore
                cached_identifier = ContextStore.get(f"material_identifier:{material_formula}")
                cached_mp = ContextStore.get(f"materials_project_search:{material_formula}")
            except Exception:
                cached_identifier = None
                cached_mp = None

            # ---- 步骤1：材料标识 ----
            identifier_tool = get_material_identifier_tool()
            identifier_result = cached_identifier or identifier_tool.identify_material(material_formula)
            result["tool_calls"]["material_identifier"] = identifier_result

            # ---- 步骤2：根据材料类型调用数据库（跳过结构验证） ----
            material_type = identifier_result.get("material_type", "unknown")
            if material_type == "metal":
                mp_tool = get_materials_project_tool()

                # 查询策略：缓存 > material_id 精确查询 > 化学式搜索
                if cached_mp and isinstance(cached_mp, dict) and cached_mp.get("data"):
                    mp_result = cached_mp
                else:
                    # 从材料标识结果中提取 material_id 用于精确查询
                    validator_data = result["tool_calls"].get("material_identifier", {})
                    add_info = validator_data.get("additional_info") if isinstance(validator_data, dict) else {}
                    material_id = (add_info or {}).get("material_id")
                    if material_id and mp_tool.validate_material_id(material_id):
                        detail = mp_tool.get_material_by_id(material_id)
                        mp_result = {"data": [detail] if "error" not in detail else [], "meta": {"total_count": 1, "limit": 1}}
                    else:
                        mp_result = mp_tool.search_materials(formula=material_formula, limit=5, fields=["material_id", "formula_pretty"])

                result["tool_calls"]["materials_project"] = mp_result
                if not ToolCallSpec.validate_materials_project_result(mp_result):
                    result["validation_passed"] = False
                    result["errors"].append("Materials Project data validation failed")

            elif material_type == "organic":
                pubchem_tool = get_pubchem_tool()
                pubchem_result = pubchem_tool.search_compound(material_formula)
                result["tool_calls"]["pubchem"] = pubchem_result

                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append("PubChem data validation failed")

        except Exception as e:
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Mechanism analysis expert tool call validation failed: {e}")

        return result


class SynthesisExpertToolSpec(ToolCallSpec):
    """
    合成指导专家 (Synthesis Guidance Expert) 的工具调用规格。

    合成指导专家专注于化学合成路径的设计和验证。
    与其他 Agent 不同，它不是根据单个材料化学式而是根据一组化学试剂
    (chemical reagents) 来查询 PubChem 数据。
    """

    @staticmethod
    def validate_tool_usage(chemical_reagents: List[str]) -> Dict[str, Any]:
        """
        验证合成指导专家的工具调用流程。

        与其他 Agent 的核心区别：
        - 输入不是单个材料化学式，而是一组化学试剂的列表
        - 对列表中的每个试剂独立调用 PubChem 进行查询
        - 逐个验证每个试剂的数据完整性

        Args:
            chemical_reagents: 化学试剂名称列表，如 ["H2O2", "NaOH", "HCl"]

        Returns:
            包含验证结果的字典
        """
        # 初始化返回结果，使用 chemical_reagents 而非 material_formula
        result = {
            "chemical_reagents": chemical_reagents,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- 对每个化学试剂调用 PubChem 工具 ----
            pubchem_results = []
            for reagent in chemical_reagents:
                # 为每个试剂创建独立的 PubChem 查询
                pubchem_tool = get_pubchem_tool()
                pubchem_result = pubchem_tool.search_compound(reagent)
                # 将试剂名称和查询结果一起存入列表，便于后续关联分析
                pubchem_results.append({
                    "reagent": reagent,
                    "result": pubchem_result
                })

                # 对每个试剂的 PubChem 结果进行验证
                # 如果任何一个试剂的验证失败，整体验证标记为失败
                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append(f"PubChem data validation failed for reagent {reagent}")

            # 将所有试剂的 PubChem 查询结果存入工具调用记录
            result["tool_calls"]["pubchem"] = pubchem_results

            # 如果存在材料信息，也可以调用 Materials Project 工具进行补充查询
            # 此处留空供未来扩展，实际应用中可能需要更复杂的逻辑
            # 例如：根据 PubChem 返回的分子量、密度等属性判断是否需要 Materials Project

        except Exception as e:
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Synthesis guidance expert tool call validation failed: {e}")

        return result
