#!/usr/bin/env python3
# 指定 Python 解释器，确保脚本在 Unix 环境下直接执行时使用 python3

"""
Data Validator Tool.
Used to validate the authenticity and validity of chemical and material data.
"""
# 模块文档字符串：描述本工具的功能——验证化学和材料数据的真实性和有效性

import logging
# 导入 logging 模块，用于记录验证过程中的警告信息

import re
# 导入 re 模块（正则表达式），用于 CAS 号和分子式的格式校验

import time
# 导入 time 模块，用于在验证结果中添加时间戳

from typing import Dict, Any, List, Union
# 导入类型注解：Dict（字典）、Any（任意类型）、List（列表）、Union（联合类型）

# Configure logging
logging.basicConfig(level=logging.WARNING)
# 配置日志基本设置：仅输出 WARNING 级别及以上的日志

logger = logging.getLogger(__name__)
# 创建以当前模块名命名的日志记录器，便于在日志中定位验证失败的原因

class DataValidatorTool:
    """Data Validator Tool Class."""
    # 数据验证工具类，提供多种化学和材料数据的格式与有效性验证方法

    def __init__(self):
        """Initialize data validator tool."""
        # 初始化验证工具，预加载验证所需的有效值列表

        # ==================== 有效化学元素符号列表 ====================
        # 包含周期表中所有已知元素（118个元素中常用的大部分）
        # 用于验证分子式中提取的元素符号是否为真实元素
        self.valid_elements = [
            'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar',
            'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr',
            'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
            'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
            'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn'
        ]

        # ==================== 有效 GHS 危险声明代码列表 ====================
        # GHS（全球化学品统一分类和标签制度）H 代码涵盖了物理危险、健康危险和环境危险
        # 用于验证危险声明代码是否符合 GHS 标准
        self.valid_h_statements = [
            "H200", "H201", "H202", "H203", "H204", "H205",
            # 物理危险 - 爆炸物（H200系列）
            "H220", "H221", "H222", "H223", "H224", "H225", "H226",
            # 物理危险 - 易燃气体/液体（H220系列）
            "H228",
            # 物理危险 - 易燃固体（H228）
            "H240", "H241", "H242",
            # 物理危险 - 自反应物质（H240系列）
            "H250", "H251", "H252",
            # 物理危险 - 自燃物质（H250系列）
            "H260", "H261",
            # 物理危险 - 遇水放出易燃气体的物质（H260系列）
            "H270", "H271", "H272",
            # 物理危险 - 氧化性物质（H270系列）
            "H280", "H281",
            # 物理危险 - 高压气体（H280系列）
            "H290",
            # 物理危险 - 金属腐蚀物（H290）
            "H300", "H301", "H302", "H303", "H304", "H305",
            # 健康危险 - 急性毒性（H300系列）
            "H310", "H311", "H312", "H313",
            # 健康危险 - 皮肤接触毒性（H310系列）
            "H314", "H315", "H316",
            # 健康危险 - 皮肤腐蚀/刺激（H314系列）
            "H317",
            # 健康危险 - 皮肤致敏（H317）
            "H318", "H319", "H320",
            # 健康危险 - 眼损伤/刺激（H318系列）
            "H330", "H331", "H332", "H333",
            # 健康危险 - 吸入毒性（H330系列）
            "H334", "H335", "H336",
            # 健康危险 - 呼吸道致敏/麻醉（H334系列）
            "H340", "H341",
            # 健康危险 - 生殖细胞致突变性（H340系列）
            "H350", "H351",
            # 健康危险 - 致癌性（H350系列）
            "H360", "H361", "H362",
            # 健康危险 - 生殖毒性（H360系列）
            "H370", "H371",
            # 健康危险 - 特异性靶器官毒性-单次暴露（H370系列）
            "H372", "H373",
            # 健康危险 - 特异性靶器官毒性-重复暴露（H373系列）
            "H400", "H401", "H402",
            # 环境危险 - 水生毒性（H400系列）
            "H410", "H411", "H412", "H413",
            # 环境危险 - 慢性水生毒性（H410系列）
            "H420"
            # 环境危险 - 臭氧层危害（H420）
        ]

    def validate_cid(self, cid: Any) -> Dict[str, Any]:
        """
        Validate if PubChem CID is valid.
        # 验证 PubChem 化合物 ID (CID) 是否有效

        Args:
            cid: Compound ID
            # 化合物 ID，可能为字符串、整数或空值

        Returns:
            Validation result dictionary
            # 包含 valid（是否有效）、reason（原因说明）、value（验证后的值）的字典
        """
        try:
            # 检查 CID 是否为空值或占位符
            # 这些值在数据采集过程中常见，表示信息缺失而非有效的 CID
            if cid is None or cid == "" or cid == "N/A" or cid == "null":
                return {
                    "valid": False,
                    "reason": "CID is empty or invalid",
                    "value": cid
                }
            # 尝试将 CID 转换为整数
            cid_int = int(cid)
            # CID 必须是正整数（PubChem 中 CID 从 1 开始递增）
            if cid_int <= 0:
                return {
                    "valid": False,
                    "reason": "CID must be a positive integer",
                    "value": cid
                }
            return {
                "valid": True,
                "reason": "CID is valid",
                "value": cid_int
                # 返回转换后的整数值，避免后续类型不一致问题
            }
        except (ValueError, TypeError):
            # 捕获转换异常：当 cid 不是合法数字字符串时
            return {
                "valid": False,
                "reason": "CID is not a valid number",
                "value": cid
            }

    def validate_material_id(self, material_id: Any) -> Dict[str, Any]:
        """
        Validate if Materials Project material ID is valid.
        # 验证 Materials Project 材料 ID (MP-ID) 是否有效

        Args:
            material_id: Material ID
            # 材料 ID，可能为字符串或空值

        Returns:
            Validation result dictionary
        """
        try:
            # 检查材料 ID 是否为空值或占位符
            if material_id is None or material_id == "" or material_id == "N/A" or material_id == "null":
                return {
                    "valid": False,
                    "reason": "Material ID is empty or invalid",
                    "value": material_id
                }
            # 确保是字符串类型
            material_id_str = str(material_id)
            # MP-ID 必须以 "mp-" 开头，且后缀长度大于 0（即总长 > 3）
            # 例如 "mp-1234" 是有效的，"mp-" 则无效
            if not material_id_str.startswith("mp-") or len(material_id_str) <= 3:
                return {
                    "valid": False,
                    "reason": "Material ID format is incorrect, should start with 'mp-'",
                    "value": material_id
                }
            return {
                "valid": True,
                "reason": "Material ID is valid",
                "value": material_id_str
                # 返回标准化为字符串的值
            }
        except (ValueError, TypeError):
            return {
                "valid": False,
                "reason": "Material ID is not a valid string",
                "value": material_id
            }

    def validate_cas_number(self, cas_number: str) -> Dict[str, Any]:
        """
        Validate if CAS number format is correct.
        # 验证 CAS 注册号格式是否正确

        Args:
            cas_number: CAS number
            # CAS 注册号字符串

        Returns:
            Validation result dictionary
        """
        # 检查 CAS 号是否为空值或占位符
        if not cas_number or cas_number == "N/A" or cas_number == "null":
            return {
                "valid": False,
                "reason": "CAS number is empty or invalid",
                "value": cas_number
            }

        # ==================== CAS 号格式验证 ====================
        # CAS 号标准格式：XXXXXXX-XX-X
        # - 第一部分：2 到 7 位数字
        # - 第二部分：2 位数字
        # - 第三部分：1 位校验数字
        # 示例：7732-18-5（水）、67-64-1（丙酮）
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'
        if re.match(cas_pattern, cas_number):
            return {
                "valid": True,
                "reason": "CAS number format is correct",
                "value": cas_number
            }
        else:
            return {
                "valid": False,
                "reason": "CAS number format is incorrect, should be XXXXX-XX-X format",
                "value": cas_number
            }

    def validate_molecular_formula(self, formula: str) -> Dict[str, Any]:
        """
        Validate if molecular formula is valid.
        # 验证分子式是否有效

        Args:
            formula: Molecular formula
            # 分子式字符串

        Returns:
            Validation result dictionary
        """
        # 检查分子式是否为空值或占位符
        if not formula or formula == "N/A" or formula == "null":
            return {
                "valid": False,
                "reason": "Molecular formula is empty or invalid",
                "value": formula
            }

        # ==================== 分子式格式验证 ====================
        # 支持两种模式：
        # 模式1：简单分子式，如 H2O、NaCl、C6H12O6
        # 模式2：含括号的分子式，如 Ca(OH)2、Fe(CN)3
        formula_pattern = r'^([A-Z][a-z]?[0-9]*)+([A-Z][a-z]?[0-9]*)*$|^([A-Z][a-z]?[0-9]*)*\([A-Z][a-z]?[0-9]*\)[0-9]*([A-Z][a-z]?[0-9]*)*$'
        if re.match(formula_pattern, formula):
            # 提取分子式中所有的元素符号
            elements = re.findall(r'[A-Z][a-z]?', formula)
            # 检查是否存在无效元素（不在已知元素列表中的符号）
            invalid_elements = [e for e in elements if e not in self.valid_elements]
            if not invalid_elements:
                return {
                    "valid": True,
                    "reason": "Molecular formula format is correct and elements are valid",
                    "value": formula
                }
            else:
                return {
                    "valid": False,
                    "reason": f"Molecular formula contains invalid elements: {', '.join(invalid_elements)}",
                    "value": formula
                }
        else:
            return {
                "valid": False,
                "reason": "Molecular formula format is incorrect",
                "value": formula
            }

    def validate_h_statements(self, h_statements: List[str]) -> Dict[str, Any]:
        """
        Validate if GHS hazard statement codes are valid.
        # 验证 GHS 危险声明代码 (H-statements) 是否有效

        Args:
            h_statements: List of hazard statement codes
            # 危险声明代码列表

        Returns:
            Validation result dictionary
        """
        # 空列表视为有效（某些化学品可能没有危险声明）
        if not h_statements:
            return {
                "valid": True,
                "reason": "Hazard statement list is empty",
                "value": h_statements
            }

        # 筛选出不在已知有效 H 代码列表中的声明
        invalid_statements = [h for h in h_statements if h not in self.valid_h_statements]
        if not invalid_statements:
            return {
                "valid": True,
                "reason": "All hazard statement codes are valid",
                "value": h_statements
            }
        else:
            return {
                "valid": False,
                "reason": f"Contains invalid hazard statement codes: {', '.join(invalid_statements)}",
                "value": h_statements,
                "invalid_statements": invalid_statements
                # 额外返回无效声明列表，方便调用方定位具体问题
            }

    def validate_molecular_weight(self, molecular_weight: Union[str, float]) -> Dict[str, Any]:
        """
        Validate if molecular weight is valid.
        # 验证分子量是否有效

        Args:
            molecular_weight: Molecular weight
            # 分子量，可能是字符串或浮点数

        Returns:
            Validation result dictionary
        """
        # 空值或占位符视为可接受状态（分子量信息可能尚未获取）
        if molecular_weight == "N/A" or molecular_weight == "null" or molecular_weight is None:
            return {
                "valid": True,
                # 注意：空值被视为 valid=True，因为"无数据"不等同于"数据错误"
                "reason": "Molecular weight is empty (acceptable)",
                "value": molecular_weight
            }

        try:
            # 转换为浮点数进行数值范围验证
            mw = float(molecular_weight)
            # 分子量必须为正数
            if mw <= 0:
                return {
                    "valid": False,
                    "reason": "Molecular weight must be positive",
                    "value": molecular_weight
                }
            # 分子量上限设为 100,000 Da（道尔顿），超过此值可能是数据错误
            # 绝大多数小分子和材料在此范围内，高分子聚合物可能接近但一般不超
            elif mw > 100000:
                return {
                    "valid": False,
                    "reason": "Molecular weight is too large, may be incorrect",
                    "value": molecular_weight
                }
            else:
                return {
                    "valid": True,
                    "reason": "Molecular weight is valid",
                    "value": mw
                    # 返回转换后的浮点数值
                }
        except (ValueError, TypeError):
            # 捕获无法转换为数字的异常
            return {
                "valid": False,
                "reason": "Molecular weight is not a valid number",
                "value": molecular_weight
            }

    def validate_chemical_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate the completeness and validity of chemical data.
        # 对化学数据进行全面验证（组合验证）

        Args:
            data: Chemical data dictionary
            # 包含各化学数据字段的字典

        Returns:
            Validation result dictionary
            # 包含 overall_valid（整体是否有效）、各字段验证结果、时间戳和原始数据的字典
        """
        validation_results = {}
        # 存储各字段的独立验证结果

        overall_valid = True
        # 整体有效性标志：任一字段验证失败即变为 False

        # ==================== 逐字段验证 ====================
        # 仅验证数据中实际存在的字段，避免对缺失字段产生误报

        # 验证 CID（如果数据中存在该字段）
        if "pubchem_cid" in data:
            cid_result = self.validate_cid(data["pubchem_cid"])
            validation_results["cid"] = cid_result
            if not cid_result["valid"]:
                overall_valid = False
                # 任一字段无效，整体标记为无效

        # 验证 CAS 号（如果数据中存在该字段）
        if "cas_number" in data:
            cas_result = self.validate_cas_number(data["cas_number"])
            validation_results["cas_number"] = cas_result
            if not cas_result["valid"]:
                overall_valid = False

        # 验证分子式（如果数据中存在该字段）
        if "molecular_formula" in data:
            formula_result = self.validate_molecular_formula(data["molecular_formula"])
            validation_results["molecular_formula"] = formula_result
            if not formula_result["valid"]:
                overall_valid = False

        # 验证分子量（如果数据中存在该字段）
        if "molecular_weight" in data:
            mw_result = self.validate_molecular_weight(data["molecular_weight"])
            validation_results["molecular_weight"] = mw_result
            if not mw_result["valid"]:
                overall_valid = False

        # 验证危险声明（如果数据中存在且为列表类型）
        if "hazard_statements" in data and isinstance(data["hazard_statements"], list):
            h_result = self.validate_h_statements(data["hazard_statements"])
            validation_results["hazard_statements"] = h_result
            if not h_result["valid"]:
                overall_valid = False

        # 验证材料 ID（如果数据中存在该字段）
        if "material_id" in data:
            material_id_result = self.validate_material_id(data["material_id"])
            validation_results["material_id"] = material_id_result
            if not material_id_result["valid"]:
                overall_valid = False

        # 返回综合验证结果
        return {
            "valid": overall_valid,
            # 整体有效性：所有存在字段均通过验证才为 True
            "validation_results": validation_results,
            # 各字段的详细验证结果字典
            "timestamp": time.time(),
            # Unix 时间戳，用于记录验证发生的时间
            "data": data
            # 原始数据回传，便于结果追溯
        }

# ==================== 全局单例实例管理 ====================
# 使用模块级变量实现懒加载单例模式
_data_validator_tool = None
# 初始化为 None，第一次调用 get_data_validator_tool() 时创建实例

def get_data_validator_tool() -> DataValidatorTool:
    """
    Get data validator tool instance.
    # 获取数据验证工具的单例实例

    Returns:
        DataValidatorTool: Data validator tool instance
    """
    global _data_validator_tool
    # 声明使用模块级全局变量

    if _data_validator_tool is None:
        # 懒加载：仅在首次调用时创建实例，保持和 material_identifier_tool 一致的模式
        _data_validator_tool = DataValidatorTool()
    return _data_validator_tool
    # 返回单例实例
