"""
Tools module initialization file. - 工具模块初始化文件
集中导入和暴露所有工具类、工厂函数和实例，作为 tools 包的公共接口。

注意：本模块不再反向导入 src.utils.assessment_tool_executor /
assessment_scoring_logic（评估相关类请直接从 src.utils 导入），
以避免 tools <-> utils 之间的循环依赖。
"""

# ===== 导入功能性工具（获取器函数） =====
# 这些是底层工具类，通过 get_xxx 工厂函数获取实例
from .materials_project_tool import get_materials_project_tool    # Materials Project 无机材料数据库查询
from .pubchem_tool import get_pubchem_tool                        # PubChem 有机化合物数据库查询
# EvaluationTool removed - not used in ECOMATS, only in BioCrew    # 评估工具已移除（仅 BioCrew 使用）
from .name2cas_tool import get_name2cas_tool                      # 化合物名称转 CAS 号
from .name2properties_tool import get_name2properties_tool        # 按名称查询化合物属性
from .cid2properties_tool import get_cid2properties_tool          # 按 CID 查询化合物属性
from .formula2properties_tool import get_formula2properties_tool  # 按分子式查询化合物属性
from .material_search_tool import get_material_search_tool        # 材料综合搜索
from .pnec_tool import get_pnec_tool                              # PNEC（预测无效应浓度）查询
from .material_identifier_tool import get_material_identifier_tool # 材料类型识别
from .data_validator_tool import get_data_validator_tool          # 数据验证
from .structure_validator_tool import get_structure_validator_tool # 材料结构存在性验证
from .molport_tool import get_molport_tool                        # MolPort 化学品市场数据查询

# ===== 导入 CrewAI 工具包装器 =====
# 这些是将底层工具封装为 CrewAI BaseTool 的适配器类/实例
from .crewai_materials_project_tool import materials_project_tool      # CrewAI Materials Project 工具实例
from .crewai_pubchem_tool import pubchem_tool                          # CrewAI PubChem 工具实例
from .crewai_pnec_tool import CrewAIPNECTool                           # CrewAI PNEC 查询工具类
from .crewai_data_validator_tool import CrewAIDataValidatorTool        # CrewAI 数据验证工具类
from .crewai_molport_tool import (                                     # CrewAI MolPort 工具（多入口）
    molport_availability_tool,                                         # 化学试剂可获得性查询
    molport_search_tool,                                               # MolPort 化合物搜索
    molport_molecule_info_tool,                                        # MolPort 分子信息查询
    CrewAIMolPortAvailabilityTool,
    CrewAIMolPortSearchTool,
    CrewAIMolPortMoleculeInfoTool
)

# ===== 导入工具工厂 =====
# ToolFactory 用于统一创建和管理所有工具实例
from .factory import ToolFactory

# ===== Nano-Bio Evaluator: Domain Tools =====
from .drugbank_tool import DrugBankTool
from .enzyme_classifier import EnzymeClassifier
from .material_compare import MaterialCompare

# ===== 定义本模块的公共接口 =====
# __all__ 列表控制 from package import * 时的导出范围
# 只导出真正需要被外部使用的类和函数
__all__ = [
    # 功能性工具获取器
    'get_materials_project_tool',
    'get_pubchem_tool',
    'get_name2cas_tool',
    'get_name2properties_tool',
    'get_cid2properties_tool',
    'get_formula2properties_tool',
    'get_material_search_tool',
    'get_pnec_tool',
    'get_material_identifier_tool',
    'get_data_validator_tool',
    'get_structure_validator_tool',
    'get_molport_tool',

    # CrewAI 工具包装器（实例）
    'materials_project_tool',
    'pubchem_tool',

    # CrewAI 工具包装器（类）
    'CrewAIPNECTool',
    'CrewAIDataValidatorTool',
    'ToolFactory',

    # MolPort 工具
    'molport_availability_tool',
    'molport_search_tool',
    'molport_molecule_info_tool',
    'CrewAIMolPortAvailabilityTool',
    'CrewAIMolPortSearchTool',
    'CrewAIMolPortMoleculeInfoTool',

    # Nano-Bio Evaluator: Domain Tools
    'DrugBankTool',
    'EnzymeClassifier',
    'MaterialCompare',
]
