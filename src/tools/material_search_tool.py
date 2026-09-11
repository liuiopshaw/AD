#!/usr/bin/env python3
# 指定 Python 解释器，确保脚本在 Unix 环境下直接执行时使用 python3

"""
Material Search Tool.
Search for materials with specific properties.
"""
# 模块文档字符串：描述本工具的功能——根据特定属性搜索材料

import json
# 导入 json 模块，用于将搜索结果序列化为 JSON 格式字符串返回

import logging
# 导入 logging 模块，用于记录运行时的警告和错误日志

from typing import Optional, List
# 从 typing 模块导入 Optional 和 List 类型注解，增强代码可读性和类型检查

from crewai.tools import BaseTool
# 从 crewai.tools 导入 BaseTool 基类，所有自定义 CrewAI 工具必须继承此类

from pydantic import BaseModel, Field
# 从 pydantic 导入 BaseModel 和 Field，用于定义工具的输入参数模型和字段描述

from src.tools.materials_project_tool import get_materials_project_tool
# 导入 Materials Project 工具的单例获取函数，用于查询材料数据库

logging.basicConfig(level=logging.WARNING)
# 配置日志基本设置：仅输出 WARNING 级别及以上的日志，减少不必要的信息干扰

logger = logging.getLogger(__name__)
# 创建以当前模块名命名的日志记录器，便于定位日志来源

class MaterialSearchInput(BaseModel):
    """Material Search Tool Input Model"""
    # Pydantic 输入模型：定义搜索工具接受的参数及其约束

    query: str = Field(..., description="Search query: material type, formula or elements")
    # 搜索查询字符串，... 表示必填；支持材料类型、化学式或元素组合

    limit: int = Field(default=10, description="Result limit")
    # 返回结果的最大数量限制，默认值为 10

class MaterialSearchTool(BaseTool):
    """Material Search Tool"""
    # 材料搜索工具类，继承 BaseTool，供 CrewAI 代理调用

    name: str = "Material Search Tool"
    # 工具名称，CrewAI 框架通过名称识别和引用工具

    description: str = (
        "Search for materials with specific properties. "
        "Search by material type, formula or element combination."
    )
    # 工具描述，CrewAI 代理根据描述判断何时应使用此工具；
    # 注：外部使用时会自动转为英文小写，中文部分仅用于内部可读性

    args_schema: type[BaseModel] = MaterialSearchInput
    # 指定工具的输入参数模型，CrewAI 框架会基于此模型解析和验证传入参数

    def _run(self, query: str, limit: int = 10) -> str:
        """
        Search materials.
        # 执行材料搜索的核心方法（_run 是 CrewAI BaseTool 要求的接口方法）

        Args:
            query: Search query
            limit: Result limit

        Returns:
            JSON formatted search results
        """
        try:
            # 获取 Materials Project 工具的单例实例
            mp_tool = get_materials_project_tool()
            materials = []
            # 初始化空列表，用于累积从不同搜索策略中获取的材料数据

            # ==================== 策略一：按化学式搜索 ====================
            # 首先尝试将用户查询直接作为化学式进行搜索
            formula_result = mp_tool.search_materials(
                formula=query,
                limit=limit,
                fields=["material_id", "formula_pretty", "chemsys", "volume", "density", "nsites"]
                # 指定需要返回的字段：材料ID、美化化学式、化学体系、体积、密度、原子位点数
            )

            # 如果搜索成功且返回了数据，则将结果加入 materials 列表
            if "error" not in formula_result and formula_result.get("data"):
                materials.extend(formula_result["data"])

            # ==================== 策略二：按元素搜索 ====================
            # 如果化学式搜索没有结果，尝试解析查询中的元素符号并按元素搜索
            if not materials:
                elements = self._parse_elements(query)
                # 从查询字符串中提取有效的化学元素符号列表
                if elements:
                    element_result = mp_tool.search_materials(
                        elements=elements,
                        limit=limit,
                        fields=["material_id", "formula_pretty", "chemsys", "volume", "density", "nsites"]
                    )
                    if "error" not in element_result and element_result.get("data"):
                        materials.extend(element_result["data"])

            # ==================== 策略三：按连字符分隔元素组合搜索 ====================
            # 如果前两种策略均无结果，尝试按 "-" 分隔符拆分查询为元素列表
            if not materials:
                if "-" in query:
                    element_list = [elem.strip() for elem in query.split("-") if elem.strip()]
                    # 按 "-" 拆分并去除空白和空字符串
                    if element_list:
                        combo_result = mp_tool.search_materials(
                            elements=element_list,
                            limit=limit,
                            fields=["material_id", "formula_pretty", "chemsys", "volume", "density", "nsites"]
                        )
                        if "error" not in combo_result and combo_result.get("data"):
                            materials.extend(combo_result["data"])

            # ==================== 无结果处理 ====================
            # 如果所有搜索策略都未找到匹配材料，返回提示信息
            if not materials:
                return json.dumps({
                    "query": query,
                    "results": [],
                    "message": f"No materials found matching '{query}'"
                }, ensure_ascii=False, indent=2)
                # ensure_ascii=False 确保非 ASCII 字符（如化学符号中的特殊字符）正常显示

            # ==================== 结果截取与格式化 ====================
            materials = materials[:limit]
            # 截断结果到用户指定的数量限制

            formatted_results = []
            # 遍历每条材料记录，提取关键字段并格式化
            for material in materials:
                formatted_material = {
                    "material_id": material.get("material_id", "N/A"),
                    # 材料 ID，若缺失则用 "N/A" 填充
                    "formula": material.get("formula", "N/A"),
                    # 化学式
                    "chemsys": material.get("chemsys", "N/A"),
                    # 化学体系（元素组合）
                    "volume": material.get("volume", "N/A"),
                    # 晶胞体积
                    "density": material.get("density", "N/A"),
                    # 密度
                    "nsites": material.get("nsites", "N/A")
                    # 原子位点数
                }
                formatted_results.append(formatted_material)

            # 返回 JSON 格式的最终搜索结果
            return json.dumps({
                "query": query,
                "results": formatted_results
            }, ensure_ascii=False, indent=2)

        except Exception as e:
            # 捕获所有异常，记录错误日志并返回错误信息的 JSON
            logger.error(f"Error searching material '{query}': {e}")
            return json.dumps({"error": f"Search error for '{query}': {str(e)}"}, ensure_ascii=False)

    def _parse_elements(self, query: str) -> Optional[List[str]]:
        """
        Parse elements from query.
        # 从查询字符串中解析并提取有效的化学元素符号

        Args:
            query: Query string

        Returns:
            Element list or None
            # 返回元素列表，如果未提取到有效元素则返回 None
        """
        elements = []
        import re
        # 在方法内导入 re，仅在需要时加载，避免不必要的模块加载

        # 使用正则表达式匹配大写字母后跟可选小写字母的模式（典型化学元素符号格式）
        element_chars = re.findall(r'[A-Z][a-z]?', query)

        # 定义已知的有效化学元素符号列表（前 54 号元素，常用范围）
        valid_elements = ["H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
                         "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
                         "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe"]

        # 过滤：仅保留在已知有效元素列表中的符号
        for element in element_chars:
            if element in valid_elements:
                elements.append(element)

        # 如果提取到元素则返回列表，否则返回 None（区分"无元素"和"空列表"）
        return elements if elements else None

# ==================== 全局单例实例 ====================
# 创建工具的单例实例，避免每次调用都重新实例化（节省内存和初始化开销）
material_search_tool = MaterialSearchTool()

def get_material_search_tool():
    """Get material search tool instance"""
    # 返回材料搜索工具的单例实例，供其他模块（如 CrewAI 封装层）调用
    return material_search_tool
