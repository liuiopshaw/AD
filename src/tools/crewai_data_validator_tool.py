import json
# 导入 json 模块，用于将验证结果序列化为 JSON 格式字符串返回

from typing import Dict, Any
# 从 typing 模块导入 Dict 和 Any 类型注解

from crewai.tools import BaseTool
# 从 crewai.tools 导入 BaseTool 基类，所有 CrewAI 工具必须继承此类

from pydantic import BaseModel, Field
# 从 pydantic 导入 BaseModel 和 Field，用于定义工具的输入参数模型和字段约束

from src.tools.data_validator_tool import get_data_validator_tool
# 导入底层数据验证工具的单例获取函数

class DataValidatorToolInput(BaseModel):
    """Data Validator Tool Input Model"""
    # Pydantic 输入模型：定义 CrewAI 封装层接受的参数

    data: Dict[str, Any] = Field(description="Data dictionary to validate")
    # 待验证的数据字典，必填参数；键值对包含各化学数据字段

    validation_type: str = Field(default="full", description="Validation type ('full', 'cid', 'cas', 'formula', 'h_statements', 'molecular_weight', 'material_id')")
    # 验证类型，默认为 "full"（全面验证）；
    # 可选值包括单项验证：cid、cas、formula、h_statements、molecular_weight、material_id

class CrewAIDataValidatorTool(BaseTool):
    """CrewAI tool wrapper for validating chemical and material data"""
    # CrewAI 数据验证工具的封装类，继承 BaseTool
    # 作用：将底层的数据验证功能包装为 CrewAI 代理可直接调用的工具

    name: str = "Data Validator"
    # 工具名称，CrewAI 代理通过此名称引用该工具

    description: str = (
        "Validate authenticity and validity of chemical and material data. "
        "Can validate CID, CAS number, formula, molecular weight, hazard statements etc. "
        "Use when you need to verify if generated chemical data is authentic and valid."
    )
    # 工具描述，CrewAI 代理据此判断何时调用；
    # 说明可验证 CID、CAS 号、分子式、分子量、危险声明等数据类型

    args_schema: type[BaseModel] = DataValidatorToolInput
    # 指定工具的输入参数模型，CrewAI 框架自动进行参数校验

    def _run(
        self,
        data: Dict[str, Any],
        validation_type: str = "full"
    ) -> str:
        """
        Execute data validation.
        # 执行数据验证的核心方法

        Args:
            data: Data dictionary to validate
            # 待验证的数据字典
            validation_type: Validation type ("full", "cid", "cas", "formula", "h_statements", "molecular_weight", "material_id")
            # 验证类型字符串

        Returns:
            JSON formatted validation result
            # JSON 格式的验证结果字符串
        """
        try:
            # 获取底层数据验证工具的单例实例
            tool = get_data_validator_tool()

            # ==================== 根据验证类型分发 ====================
            # 路由逻辑：根据用户指定的 validation_type 调用对应的单项验证方法
            # 如果数据中缺少对应的字段，返回错误提示

            if validation_type == "cid":
                # 单项验证：PubChem CID
                if "pubchem_cid" in data:
                    result = tool.validate_cid(data["pubchem_cid"])
                else:
                    result = {"error": "pubchem_cid field not found in data"}

            elif validation_type == "cas":
                # 单项验证：CAS 注册号
                if "cas_number" in data:
                    result = tool.validate_cas_number(data["cas_number"])
                else:
                    result = {"error": "cas_number field not found in data"}

            elif validation_type == "formula":
                # 单项验证：分子式
                if "molecular_formula" in data:
                    result = tool.validate_molecular_formula(data["molecular_formula"])
                else:
                    result = {"error": "molecular_formula field not found in data"}

            elif validation_type == "h_statements":
                # 单项验证：GHS 危险声明代码
                if "hazard_statements" in data:
                    result = tool.validate_h_statements(data["hazard_statements"])
                else:
                    result = {"error": "hazard_statements field not found in data"}

            elif validation_type == "molecular_weight":
                # 单项验证：分子量
                if "molecular_weight" in data:
                    result = tool.validate_molecular_weight(data["molecular_weight"])
                else:
                    result = {"error": "molecular_weight field not found in data"}

            elif validation_type == "material_id":
                # 单项验证：Materials Project 材料 ID
                if "material_id" in data:
                    result = tool.validate_material_id(data["material_id"])
                else:
                    result = {"error": "material_id field not found in data"}

            else:
                # 默认：执行全面验证（validation_type == "full" 或其他未识别值）
                # 这会对数据中存在的所有字段逐一验证并返回综合结果
                result = tool.validate_chemical_data(data)

            # 将验证结果（dict）序列化为 JSON 字符串返回
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            # 捕获所有异常，返回错误信息的 JSON
            # 保证 CrewAI 代理始终收到格式统一的响应，不会因未捕获异常而中断工作流
            return json.dumps({"error": f"Validation error: {str(e)}"}, ensure_ascii=False)

# ==================== 全局工具实例 ====================
# 创建 CrewAI 数据验证工具的实例，供 Agent 配置时直接引用
# 此处在模块加载时实例化，因为工具本身无状态，实例化开销极小
data_validator_tool = CrewAIDataValidatorTool()
