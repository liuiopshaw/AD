#!/usr/bin/env python3
# 指定使用 Python 3 解释器运行此脚本

"""
Name to Properties Query Tool.
Query key physicochemical properties by material name.

通过材料名称查询关键物化属性的工具。
用户输入材料名称，工具返回该材料的关键物化属性信息（如密度、体积、晶系等）。
"""

import json
# 导入 json 模块，用于将查询结果序列化为 JSON 格式的字符串返回

import logging
# 导入 logging 模块，用于记录错误日志，便于调试和追踪运行时异常

from crewai.tools import BaseTool
# 从 crewai.tools 导入 BaseTool 基类，所有 CrewAI 工具都需要继承此类

from pydantic import BaseModel, Field
# 从 pydantic 导入 BaseModel 和 Field，用于定义工具的输入参数模型和字段约束

from src.tools.materials_project_tool import get_materials_project_tool
# 导入 Materials Project 工具的单例获取函数，该工具封装了对 Materials Project API 的调用

logging.basicConfig(level=logging.WARNING)
# 配置全局日志级别为 WARNING，减少低级别日志输出，避免干扰正常业务日志

logger = logging.getLogger(__name__)
# 获取当前模块的 logger 实例，用于记录该模块内的错误信息，日志中会带上模块名

class Name2PropertiesInput(BaseModel):
    """Name to Properties Query Tool Input Model
    名称到属性查询工具的输入参数模型。定义工具接收的输入字段及其验证规则。"""

    name: str = Field(..., description="Material name")
    # 材料名称字段，类型为字符串，"..." 表示该字段为必填项（无默认值）

class Name2PropertiesTool(BaseTool):
    """Name to Properties Query Tool
    名称到属性查询工具类。继承自 CrewAI 的 BaseTool，实现通过材料名称查询物化属性的功能。"""

    name: str = "Name to Properties Query Tool"
    # 工具的名称标识，CrewAI 框架使用此名称来引用和执行工具

    description: str = (
        "Query key physicochemical properties by material name. "
        "Input material name, returns property information."
    )
    # 工具的功能描述，帮助 LLM 理解何时应该调用此工具以及它的作用

    args_schema: type[BaseModel] = Name2PropertiesInput
    # 指定该工具的输入参数模型为 Name2PropertiesInput，CrewAI 会据此验证和解析输入

    def _run(self, name: str) -> str:
        """
        Query material properties by name.
        根据材料名称查询物化属性，核心执行逻辑。

        Args:
            name: Material name 材料名称

        Returns:
            JSON formatted material property info 返回 JSON 格式的材料属性信息
        """
        try:
            mp_tool = get_materials_project_tool()
            # 获取 Materials Project 工具的单例实例，避免重复初始化 API 连接

            search_result = mp_tool.search_materials(formula=name, limit=5, fields=["material_id", "formula_pretty"])
            # 使用材料名称作为搜索词在 Materials Project 数据库中搜索
            # limit=5 限制返回最多 5 条结果，fields 指定只返回 material_id 和 formula_pretty 以节省带宽

            if "error" in search_result:
                return json.dumps({"error": search_result["error"]}, ensure_ascii=False)
                # 如果搜索返回中包含 "error" 键，说明 API 调用出错，将错误信息包装为 JSON 返回
                # ensure_ascii=False 确保中文/特殊字符在 JSON 中不被转义为 \uXXXX 格式

            if not search_result.get("data"):
                return json.dumps({"error": f"No material found with name {name}"}, ensure_ascii=False)
                # 如果搜索结果的 "data" 字段为空或不存在，说明没有找到匹配的材料，返回错误信息

            first_material = search_result["data"][0]
            # 取搜索结果中的第一条记录作为最匹配的材料

            material_id = first_material.get("material_id")
            # 从第一条匹配结果中提取 Materials Project 内部的材料 ID

            if not material_id or material_id == "N/A":
                return json.dumps({"error": f"No valid material ID found for name {name}"}, ensure_ascii=False)
                # 如果材料 ID 不存在或为 "N/A"，说明结果无效，返回错误信息

            detail_result = mp_tool.get_material_by_id(material_id)
            # 使用获取到的材料 ID 查询该材料的详细属性信息

            if "error" in detail_result:
                return json.dumps({"error": detail_result["error"]}, ensure_ascii=False)
                # 如果详细查询返回错误，同样包装为 JSON 格式返回

            properties = {
                "name": name,
                # 原始查询的材料名称，保留用户输入以便对照

                "formula": detail_result.get("formula", "N/A"),
                # 材料的化学式，如不存在则返回 "N/A"

                "material_id": detail_result.get("material_id", "N/A"),
                # Materials Project 中的材料 ID，全局唯一标识

                "chemsys": detail_result.get("chemsys", "N/A"),
                # 化学体系（Chemical System），表示材料包含的元素种类组合

                "volume": detail_result.get("volume", "N/A"),
                # 材料的晶胞体积，单位为 Angstrom^3

                "density": detail_result.get("density", "N/A"),
                # 材料的理论密度，单位为 g/cm^3

                "nsites": detail_result.get("nsites", "N/A"),
                # 晶胞中的原子位点数量

                "crystal_system": detail_result.get("crystal_system", "N/A")
                # 材料的晶系（如 cubic、hexagonal、monoclinic 等）
            }

            return json.dumps(properties, ensure_ascii=False, indent=2)
            # 将属性字典序列化为格式化的 JSON 字符串返回，indent=2 使输出更易读

        except Exception as e:
            logger.error(f"Error querying properties for name {name}: {e}")
            # 捕获所有异常并记录到日志中，包含异常的具体信息以便排查

            return json.dumps({"error": f"Query error for name {name}: {str(e)}"}, ensure_ascii=False)
            # 将异常信息包装为 JSON 格式的错误响应返回给调用方

# 在模块级别创建工具的单例实例，确保整个应用中共享同一个工具对象
name2properties_tool = Name2PropertiesTool()

def get_name2properties_tool():
    """Get name to properties query tool instance
    获取名称到属性查询工具的单例实例。
    提供统一的访问入口，其他模块通过调用此函数获取同一个工具实例。"""
    return name2properties_tool
