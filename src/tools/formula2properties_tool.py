#!/usr/bin/env python3
# 指定使用 Python 3 解释器运行此脚本

"""
Formula to Properties Query Tool.
Query key physicochemical properties by material formula.

通过化学式查询材料物化属性的工具。
用户输入化学分子式（如 "TiO2"、"LiFePO4" 等），
工具通过 Materials Project 数据库搜索并返回对应的物理化学属性。
"""

import json
# 导入 json 模块，用于将查询结果序列化为 JSON 格式字符串返回

import logging
# 导入 logging 模块，用于记录运行时的错误信息

from crewai.tools import BaseTool
# 从 crewai.tools 导入 BaseTool 基类，用于构建符合 CrewAI 框架标准的工具

from pydantic import BaseModel, Field
# 从 pydantic 导入 BaseModel 和 Field，用于定义工具的输入参数模型

from src.tools.materials_project_tool import get_materials_project_tool
# 导入 Materials Project 工具的单例获取函数，用于访问 Materials Project API

logging.basicConfig(level=logging.WARNING)
# 配置日志级别为 WARNING，仅输出警告及以上级别的信息，避免日志冗余

logger = logging.getLogger(__name__)
# 获取当前模块的 logger 实例，日志中带模块名前缀，便于追踪问题来源

class Formula2PropertiesInput(BaseModel):
    """Formula to Properties Query Tool Input Model
    化学式到属性查询工具的输入参数模型。定义工具接收的必填参数。"""

    formula: str = Field(..., description="Chemical formula")
    # 化学式字段，类型为字符串
    # "..."（Ellipsis）表示该字段为必填项，调用时必须提供
    # description 为 LLM 提供参数说明

class Formula2PropertiesTool(BaseTool):
    """Formula to Properties Query Tool
    化学式到属性查询工具类。继承自 CrewAI 的 BaseTool，
    实现通过化学式在 Materials Project 中搜索材料并返回详细属性。"""

    name: str = "Formula to Properties Query Tool"
    # 工具的标识名称，CrewAI 框架通过此名称引用工具

    description: str = (
        "Query key physicochemical properties by material formula. "
        "Input formula, returns material property information."
    )
    # 工具功能描述，告知 LLM 工具的作用和使用场景

    args_schema: type[BaseModel] = Formula2PropertiesInput
    # 指定输入模型为 Formula2PropertiesInput，CrewAI 据此验证输入参数

    def _run(self, formula: str) -> str:
        """
        Query material properties by formula.
        通过化学式查询材料的物化属性。这是工具的执行入口方法。

        流程：
        1. 搜索 Materials Project 数据库
        2. 取最佳匹配的材料 ID
        3. 用材料 ID 获取详细属性
        4. 返回格式化的 JSON 结果

        Args:
            formula: Chemical formula 化学分子式（如 H2O、NaCl、TiO2）

        Returns:
            JSON formatted material property info  JSON 格式的材料属性信息
        """
        try:
            mp_tool = get_materials_project_tool()
            # 获取 Materials Project 工具的单例实例，复用已有的 API 连接

            search_result = mp_tool.search_materials(formula=formula, limit=5, fields=["material_id", "formula_pretty"])
            # 用化学式在 Materials Project 数据库中搜索匹配材料
            # limit=5 限制返回最多 5 条结果，fields 指定只取必要字段以减少数据传输量
            # formula_pretty 是格式化后的化学式（含上下标），material_id 是唯一标识

            if "error" in search_result:
                return json.dumps({"error": search_result["error"]}, ensure_ascii=False)
                # 如果搜索 API 返回错误，直接将错误信息包装为 JSON 返回

            if not search_result.get("data"):
                return json.dumps({"error": f"No material found with formula {formula}"}, ensure_ascii=False)
                # 如果搜索结果为空（data 字段不存在或为空），说明数据库中无该化学式的记录

            first_material = search_result["data"][0]
            # 取搜索结果中第一条（最相关）的材料记录

            material_id = first_material.get("material_id")
            # 提取 Materials Project 中的材料唯一 ID

            if not material_id or material_id == "N/A":
                return json.dumps({"error": f"No valid material ID found for formula {formula}"}, ensure_ascii=False)
                # 如果材料 ID 无效或缺失，无法进行后续详细查询，返回错误

            detail_result = mp_tool.get_material_by_id(material_id)
            # 使用获取到的材料 ID 请求该材料的完整详细信息

            if "error" in detail_result:
                return json.dumps({"error": detail_result["error"]}, ensure_ascii=False)
                # 如果详细查询失败，返回错误信息

            properties = {
                "formula": detail_result.get("formula", formula),
                # 材料的化学式，优先使用 API 返回的格式化公式，若不存在则回退到用户输入的公式

                "material_id": detail_result.get("material_id", "N/A"),
                # Materials Project 中该材料的唯一标识 ID

                "chemsys": detail_result.get("chemsys", "N/A"),
                # 化学体系标识，表示材料由哪些元素组成（如 "Li-Fe-P-O"）

                "volume": detail_result.get("volume", "N/A"),
                # 晶胞体积，单位为 Angstrom^3（立方埃），反映晶体结构的基本尺寸

                "density": detail_result.get("density", "N/A"),
                # 理论密度，单位为 g/cm^3，由晶胞质量和体积计算得出

                "nsites": detail_result.get("nsites", "N/A"),
                # 晶胞中的原子位点数，即单胞内独立原子位置的总数

                "crystal_system": detail_result.get("crystal_system", "N/A")
                # 晶系类型，如 cubic（立方）、hexagonal（六方）、tetragonal（四方）等
            }

            return json.dumps(properties, ensure_ascii=False, indent=2)
            # 将属性字典序列化为格式化的 JSON 字符串
            # ensure_ascii=False 保证中文字符不转义
            # indent=2 使输出具有缩进层次，便于阅读

        except Exception as e:
            logger.error(f"Error querying properties for formula {formula}: {e}")
            # 记录异常详情到日志，包含触发异常的化学式和错误堆栈

            return json.dumps({"error": f"Query error for formula {formula}: {str(e)}"}, ensure_ascii=False)
            # 将异常信息包装为 JSON 格式的错误响应返回，确保接口始终返回合法的 JSON

# 在模块层面创建工具的单例实例
# 模块首次被导入时即创建，后续导入共享同一个实例
formula2properties_tool = Formula2PropertiesTool()

def get_formula2properties_tool():
    """Get formula to properties query tool instance
    获取化学式到属性查询工具的单例实例。
    提供统一的外部访问接口，返回模块级别的单例工具对象。"""
    return formula2properties_tool
