#!/usr/bin/env python3
"""
Tool Factory.
Create and manage various database query tools.
工具工厂模块 —— 创建并管理各种数据库查询工具。
根据不同的业务场景（如操作指导、文献提取、材料设计、材料评估等），
提供对应的一组工具，供各 Agent 使用。
"""

# ---- CrewAI 工具封装层导入 ----
# 将 Materials Project 和 PubChem 等底层 API 封装为 CrewAI 工具对象，
# 方便 CrewAI 框架中的 Agent 直接调用。

# Materials Project 数据库的 CrewAI 封装工具
from src.tools.crewai_materials_project_tool import materials_project_tool
# PubChem 数据库的 CrewAI 封装工具
from src.tools.crewai_pubchem_tool import pubchem_tool
# PNEC（预测无效应浓度）环境风险评估的 CrewAI 工具
from src.tools.crewai_pnec_tool import CrewAIPNECTool
# 数据格式验证的 CrewAI 工具（纯本地验证，不调用外部 API）
from src.tools.crewai_data_validator_tool import CrewAIDataValidatorTool
# MolPort 化学品供应商数据库的三个 CrewAI 工具
from src.tools.crewai_molport_tool import (
    molport_availability_tool,   # 化学品商业可用性查询
    molport_search_tool,         # 化学品搜索
    molport_molecule_info_tool   # 分子信息查询
)


class ToolFactory:
    """
    工具工厂类 —— 根据不同的工作流阶段（Agent 的任务需求），
    提供预设的工具集合。每个静态方法返回一组工具实例，
    体现了 "Less is More" 的设计策略：只保留核心数据源和独立功能工具，
    移除内部间接调用 MP/PubChem 的冗余工具。
    """

    @staticmethod
    def create_operation_guidance_tools():
        """
        创建操作指导工具集 —— 供 Operation_Suggesting_agent 使用。

        根据任务需求匹配：
        - pubchem: 化学安全数据
        - materials_project: 材料成本数据
        - PNEC: 环境影响数据

        Returns:
            list: 操作指导工具实例列表
        """
        tools = [
            pubchem_tool,                  # 化学安全数据（满足任务需求）
            materials_project_tool,        # 材料成本数据（满足任务需求）
            CrewAIPNECTool(),              # 环境影响评估（满足任务需求）
        ]
        return tools

    @staticmethod
    def create_literature_extraction_tools():
        """
        创建文献提取工具集 —— 供 Extracting_agent 用于从文献中提取化学信息。

        策略 (Less is More):
        - 移除 Name2Properties/MaterialSearch（内部调用 MP，冗余）
        - 保留核心查询工具 + 本地验证工具

        Returns:
            list: 文献提取工具实例列表
        """
        tools = [
            materials_project_tool,         # 材料结构查询（无机材料核心搜索）
            pubchem_tool,                   # 化合物信息查询（有机化合物核心搜索）
            CrewAIDataValidatorTool()       # 本地数据格式验证（不调用外部 API，快速）
        ]
        return tools

    @staticmethod
    def create_material_design_tools():
        """
        创建材料设计工具集。

        策略 (Less is More):
        - 只保留 MP 和 PubChem 两个核心查询工具
        - 移除 MaterialIdentifier/StructureValidator/MaterialSearch
          （均内部调用 MP+PubChem，高度冗余）

        Returns:
            list: 材料设计工具实例列表
        """
        tools = [
            materials_project_tool,   # 材料结构和性质查询（无机材料设计依据）
            pubchem_tool,             # 有机化合物信息（有机组分设计依据）
        ]
        return tools

    @staticmethod
    def create_material_search_tools():
        """
        创建材料搜索工具集 —— 供 SynthesisGuidingAgent 合成指导 Agent 使用。

        策略 (Less is More):
        - 移除 MaterialSearch/StructureValidator（内部调用 MP，冗余）
        - 直接使用核心工具

        Returns:
            list: 材料搜索工具实例列表
        """
        tools = [
            materials_project_tool,             # 材料结构和合成信息
            pubchem_tool,                       # 试剂安全数据（合成安全性参考）
        ]
        return tools

    @staticmethod
    def create_mechanism_analysis_tools():
        """
        创建机理分析工具集 —— 供 MechanismMiningAgent 机理挖掘 Agent 使用。

        注意: 优先复用上游 Agent 的分析结果，减少重复查询。

        Returns:
            list: 机理分析工具实例列表
        """
        tools = [
            materials_project_tool,          # 材料结构和电子结构（用于机理解释）
            pubchem_tool,                    # 化学反应性数据（反应用）
        ]
        return tools

    @staticmethod
    def create_unified_assessment_tools():
        """
        创建统一 ASA 评估工具集 —— 供 Expert A/B/C 三个专家 Agent 共用。

        策略 (Less is More):
        - 移除 MaterialIdentifier/StructureValidator（调用 MP+PubChem，高度冗余）
        - 保留核心数据源 + 独立功能工具

        评估维度与工具的映射关系：
        - 催化性能 (50%)      → materials_project（材料结构、电子结构、稳定性）
        - 经济可行性 (10%)    → molport（商业可用性）
        - 环境友好性 (10%)    → PNEC（环境风险评估）
        - 技术可行性 (10%)    → materials_project（材料结构与合成可行性）
        - 结构合理性 (20%)    → pubchem（化学性质、毒性、结构验证）

        Returns:
            list: 统一评估工具实例列表
        """
        tools = [
            materials_project_tool,          # 材料结构、电子结构、稳定性（催化性能+技术可行性）
            pubchem_tool,                    # 化学性质、毒性、结构验证（结构合理性）
            CrewAIPNECTool(),                # 环境风险评估（独立 API，环境友好性）
            molport_availability_tool,       # 商业可用性（独立 API，经济可行性）
        ]
        return tools
