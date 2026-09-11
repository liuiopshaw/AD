#!/usr/bin/env python3
# 指定解释器为 python3，确保在 Unix-like 系统上直接执行时使用正确的 Python 版本

"""
Assessment Tool Executor.
Provides unified tool invocation logic to ensure all assessment agents use the same tool invocation process.

评估工具执行器模块。
提供统一的工具调用逻辑，确保所有评估 Agent 使用相同的工具调用流程，
避免不同 Agent 重复调用相同的工具、浪费 API 配额，并将结果写入全局上下文供复用。
"""

import logging
# 导入 Python 内置日志模块，用于记录工具调用过程中的错误和警告
import json
# 导入 json 模块，用于解析 BaseTool._run 返回的 JSON 字符串结果
from typing import Dict, Any
# 从 typing 模块导入类型提示，用于函数签名中的字典类型标注
from src.utils.tool_call_spec import ToolCallSpec
# 导入工具调用规范类，用于验证各工具返回结果的格式和内容是否合法
from src.utils.context_store import ContextStore
# 导入上下文存储类，用于将工具调用结果写入全局上下文，供后续 Agent 和 Task 复用

# Delayed import to avoid circular import
# 以下函数采用延迟导入策略：每个工具的真实导入只在函数被首次调用时执行
# 目的是避免在模块加载阶段产生循环导入问题（因为工具模块也可能引用此模块）

def get_material_identifier_tool():
    """
    获取材料标识符工具实例（延迟导入）。
    为了避免循环导入，不在此模块顶部直接 import，而是在函数体内动态导入。
    """
    from src.tools.material_identifier_tool import get_material_identifier_tool as _get_material_identifier_tool
    return _get_material_identifier_tool()

def get_structure_validator_tool():
    """
    获取结构验证器工具实例（延迟导入）。
    用于验证材料结构是否在已知晶体学数据库中真实存在。
    """
    from src.tools.structure_validator_tool import get_structure_validator_tool as _get_structure_validator_tool
    return _get_structure_validator_tool()

def get_materials_project_tool():
    """
    获取 Materials Project 数据库查询工具实例（延迟导入）。
    用于查询金属和无机材料的晶体结构、热力学稳定性和物理性质。
    """
    from src.tools.materials_project_tool import get_materials_project_tool as _get_materials_project_tool
    return _get_materials_project_tool()

def get_pubchem_tool():
    """
    获取 PubChem 数据库查询工具实例（延迟导入）。
    用于查询有机化合物和污染物的化学信息、毒性和环境数据。
    """
    from src.tools.pubchem_tool import get_pubchem_tool as _get_pubchem_tool
    return _get_pubchem_tool()

def get_pnec_tool():
    """
    获取 PNEC（预测无效应浓度）工具实例（延迟导入）。
    用于查询化学品的环境风险评估数据和生态毒性阈值。
    """
    from src.tools.pnec_tool import get_pnec_tool as _get_pnec_tool
    return _get_pnec_tool()

def get_data_validator_tool():
    """
    获取数据验证器工具实例（延迟导入）。
    用于验证化学数据的完整性和一致性，如分子式格式、化学价的合理性。
    """
    from src.tools.data_validator_tool import get_data_validator_tool as _get_data_validator_tool
    return _get_data_validator_tool()

def get_material_search_tool():
    """
    获取材料搜索工具实例（延迟导入）。
    用于在多个材料数据库中执行综合搜索，汇总候选材料信息。
    """
    from src.tools.material_search_tool import get_material_search_tool as _get_material_search_tool
    return _get_material_search_tool()


# Configure logging
logging.basicConfig(level=logging.WARNING)
# 配置日志级别为 WARNING，仅输出警告及以上级别的信息，避免 INFO/DEBUG 日志干扰
logger = logging.getLogger(__name__)
# 获取当前模块命名的日志记录器

class AssessmentToolExecutor:
    """Assessment Tool Executor Class - Provides unified tool invocation logic.
    评估工具执行器类 - 封装了所有评估相关工具的统一调用逻辑。
    每个评估 Agent 应该使用此执行器，而非直接调用工具，以保证调用的一致性和结果的可复用性。"""

    def __init__(self):
        """Initialize assessment tool executor.
        初始化评估工具执行器：在构造函数中预先获取所有可用工具的实例。
        这样在后续方法中可以直接使用，避免重复导入。"""
        # 材料标识符工具：用于识别材料类型（金属/有机/未知）
        self.material_identifier_tool = get_material_identifier_tool()
        # 结构验证器工具：验证材料结构是否在真实数据库中存在
        self.structure_validator_tool = get_structure_validator_tool()
        # Materials Project 工具：查询无机材料数据库（含能带、热力学数据）
        self.materials_project_tool = get_materials_project_tool()
        # PubChem 工具：查询有机化合物和污染物的化学数据库
        self.pubchem_tool = get_pubchem_tool()
        # PNEC 工具：查询环境风险评估数据
        self.pnec_tool = get_pnec_tool()
        # 数据验证器工具：验证化学数据的完整性和正确性
        self.data_validator_tool = get_data_validator_tool()
        # 材料搜索工具：综合搜索多种材料数据库
        self.material_search_tool = get_material_search_tool()

    def execute_mandatory_tool_calls(self, material_formula: str) -> Dict[str, Any]:
        """
        Execute mandatory tool invocation sequence for assessment agents.
        执行评估 Agent 的强制工具调用序列。
        按固定顺序调用 7 个工具，将结果收集到统一字典中，
        并将关键结果写入全局上下文供后续复用。

        Args:
            material_formula (str): Material chemical formula
            material_formula (str): 待评估材料的化学式，如 "TiO2"、"Fe2O3"

        Returns:
            Dict[str, Any]: Results of all tool invocations
            Dict[str, Any]: 所有工具调用的结果字典，包含每个工具的返回值和错误列表
        """
        # 初始化结果字典：每个工具对应的 key 初始为 None
        # errors 列表用于收集所有工具调用过程中的异常信息
        results = {
            "material_identifier": None,   # 材料标识符结果
            "structure_validator": None,   # 结构验证结果
            "materials_project": None,     # Materials Project 查询结果
            "pubchem": None,               # PubChem 查询结果
            "pnec": None,                  # PNEC 环境风险查询结果
            "data_validator": None,        # 数据验证结果
            "material_search": None,       # 材料搜索综合结果
            "errors": []                   # 错误信息收集列表
        }

        try:
            # 1. Material identifier tool invocation
            # 步骤1：调用材料标识符工具，识别物质类型（金属/有机/未知）和验证信息
            results["material_identifier"] = self.material_identifier_tool.identify_material(material_formula)

            # 2. Structure validator tool invocation
            # 步骤2：调用结构验证器工具，验证该化学式对应的材料结构是否在真实数据库中存在
            results["structure_validator"] = self.structure_validator_tool.validate_structure_exists(material_formula)

            # 3. Invoke appropriate database tool based on material type (only when validation passes)
            # 步骤3：根据材料类型选择性调用数据库工具——仅在材料标识验证通过时才查询
            # 材料标识结果中包含 material_type（材料类型）和 is_verified（是否验证通过）
            material_type = results["material_identifier"].get("material_type", "unknown")
            if results["material_identifier"].get("is_verified"):
                # 如果材料被验证为金属类型，调用 Materials Project 搜索
                if material_type == "metal":
                    results["materials_project"] = self.materials_project_tool.search_materials(
                        formula=material_formula,
                        limit=5,  # 限制返回 5 条结果，避免过度消耗 API 配额
                        fields=["material_id", "formula_pretty"]  # 仅请求必要字段，减少数据传输量
                    )
                # 如果材料被验证为有机物类型，调用 PubChem 搜索
                elif material_type == "organic":
                    results["pubchem"] = self.pubchem_tool.search_compound(material_formula)

            # 4. Invoke PNEC tool (environmental risk assessment): only attempt when validated or valid name parsed
            # 步骤4：调用 PNEC 工具获取环境风险评估数据（预测无效应浓度）
            # 仅在材料已通过验证时查询，否则返回警告信息
            try:
                if results["material_identifier"].get("is_verified"):
                    results["pnec"] = self.pnec_tool.get_pnec_by_name(material_formula)
                else:
                    # 材料未验证，跳过 PNEC 查询并记录原因
                    results["pnec"] = {"warning": "Material not validated, skipping PNEC query"}
            except Exception:
                # PNEC 查询失败不影响整体流程，记录错误信息继续执行
                results["pnec"] = {"error": "PNEC query failed"}

            # 5. Invoke data validator tool
            # 步骤5：调用数据验证器工具，验证化学数据的完整性和一致性
            # 构建包含分子式和材料名称的数据字典作为验证输入
            material_data = {
                "molecular_formula": material_formula,  # 分子式
                "material_name": material_formula       # 材料名称（此处与分子式相同）
            }
            results["data_validator"] = self.data_validator_tool.validate_chemical_data(material_data)

            # 6. Invoke material search tool: this tool is BaseTool, use its _run interface
            # 步骤6：调用材料搜索工具的综合搜索接口
            # 注意：此工具继承自 BaseTool，使用 _run 方法而非自定义接口
            # _run 返回的是 JSON 字符串，需要解析为 dict 以保持与其他工具结果类型一致
            try:
                raw_search_result = self.material_search_tool._run(material_formula, limit=10)
                if isinstance(raw_search_result, str):
                    try:
                        results["material_search"] = json.loads(raw_search_result)
                    except (json.JSONDecodeError, ValueError):
                        # 返回内容不是合法 JSON，包装为错误字典，避免污染下游处理
                        results["material_search"] = {"error": "Material search tool returned a non-JSON result"}
                else:
                    # 已实现返回 dict 的情况，直接使用
                    results["material_search"] = raw_search_result
            except Exception:
                # 材料搜索失败不阻塞流程，记录错误后继续
                results["material_search"] = {"error": "Material search tool invocation failed"}

            # Write to global context for reuse to avoid duplicate queries
            # 步骤7：将关键工具结果写入全局上下文存储，供后续 Agent 和 Task 复用
            # 这避免了不同 Agent 重复发起相同的数据库查询，有效节省 API 配额
            # 缓存键携带材料化学式（material_formula），保证：
            # - 同一材料的 A/B/C 专家之间可以复用结果（键相同）
            # - 不同材料之间不会互相串数据（键不同）
            # 仅缓存成功结果：含 "error" 的结果不写入，避免错误结果被永久缓存
            try:
                # 材料标识结果写入上下文，供后续 Agent 判断材料类型
                material_identifier_result = results.get("material_identifier")
                if isinstance(material_identifier_result, dict) and "error" not in material_identifier_result:
                    ContextStore.set(f"material_identifier:{material_formula}", material_identifier_result)
                # Materials Project 搜索结果写入上下文（如果有）
                materials_project_result = results.get("materials_project")
                if isinstance(materials_project_result, dict) and "error" not in materials_project_result:
                    ContextStore.set(f"materials_project_search:{material_formula}", materials_project_result)
                # 结构验证结果写入上下文，避免重复验证
                structure_validator_result = results.get("structure_validator")
                if isinstance(structure_validator_result, dict) and "error" not in structure_validator_result:
                    ContextStore.set(f"structure_validator:{material_formula}", structure_validator_result)
                # 材料搜索综合结果写入上下文
                material_search_result = results.get("material_search")
                if isinstance(material_search_result, dict) and "error" not in material_search_result:
                    ContextStore.set(f"material_search:{material_formula}", material_search_result)
            except Exception:
                # 上下文写入失败不影响主流程，静默跳过
                pass

        except Exception as e:
            # 捕获所有异常，收集错误信息而非崩溃
            results["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            # 记录详细错误日志供调试
            logger.error(f"Assessment tool invocation failed: {e}")

        # 返回包含所有工具调用结果（或错误信息）的完整字典
        return results

    def validate_tool_results(self, tool_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate all tool invocation results.
        验证所有工具调用结果的完整性和合法性。
        使用 ToolCallSpec 中定义的验证标准逐一检查各工具返回的数据格式。

        Args:
            tool_results (Dict[str, Any]): Tool invocation results
            tool_results (Dict[str, Any]): 工具调用结果字典（由 execute_mandatory_tool_calls 返回）

        Returns:
            Dict[str, Any]: Validation results
            Dict[str, Any]: 验证结果字典，包含总体通过标志和各项验证详情
        """
        # 初始化验证结果字典：默认 all_valid 为 True，遇到任一项失败则置为 False
        validation_result = {
            "all_valid": True,                # 总体验证标志：True 表示所有工具结果通过验证
            "validation_details": {},         # 各工具逐项验证详情
            "errors": []                      # 验证失败的错误信息列表
        }

        # Validate material identifier results
        # 验证材料标识符结果：检查返回的字典是否包含必要字段且数据合法
        if tool_results.get("material_identifier"):
            is_valid = ToolCallSpec.validate_material_identifier_result(tool_results["material_identifier"])
            validation_result["validation_details"]["material_identifier"] = is_valid
            if not is_valid:
                # 材料标识验证失败，标记总体验证为失败并记录
                validation_result["all_valid"] = False
                validation_result["errors"].append("Material identifier validation failed")

        # Validate structure validator results
        # 验证结构验证器结果：检查结构信息是否完整且数据库来源可靠
        if tool_results.get("structure_validator"):
            is_valid = ToolCallSpec.validate_structure_validator_result(tool_results["structure_validator"])
            validation_result["validation_details"]["structure_validator"] = is_valid
            if not is_valid:
                validation_result["all_valid"] = False
                validation_result["errors"].append("Structure validation failed")

        # Validate Materials Project results
        # 验证 Materials Project 查询结果：确保返回数据符合 API 规范
        if tool_results.get("materials_project"):
            is_valid = ToolCallSpec.validate_materials_project_result(tool_results["materials_project"])
            validation_result["validation_details"]["materials_project"] = is_valid
            if not is_valid:
                validation_result["all_valid"] = False
                validation_result["errors"].append("Materials Project data validation failed")

        # Validate PubChem results
        # 验证 PubChem 查询结果：确保化合物数据格式正确、字段完整
        if tool_results.get("pubchem"):
            is_valid = ToolCallSpec.validate_pubchem_result(tool_results["pubchem"])
            validation_result["validation_details"]["pubchem"] = is_valid
            if not is_valid:
                validation_result["all_valid"] = False
                validation_result["errors"].append("PubChem data validation failed")

        # 返回验证结果字典，调用方可根据 all_valid 判断是否需要调整评分
        return validation_result
