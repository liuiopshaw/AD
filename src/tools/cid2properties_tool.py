#!/usr/bin/env python3
# 指定使用 Python 3 解释器运行此脚本

"""
CID2Properties Tool.
Query compound properties by PubChem CID.

通过 PubChem 化合物 CID 查询化合物属性的工具。
CID（Compound ID）是 PubChem 数据库中每个化合物的唯一数字标识符。
该工具使用 PubChem REST API 获取化合物的分子式、分子量、SMILES 等信息。
"""

import logging
# 导入 logging 模块，用于记录查询过程中的错误和异常信息

from typing import Dict, Any
# 从 typing 导入类型提示，Dict 和 Any 用于标注返回值的类型结构

from src.tools.pubchem_tool import get_pubchem_tool
# 导入 PubChem 工具的单例获取函数，该工具封装了对 PubChem REST API 的调用

# 配置全局日志级别和格式，仅输出 WARNING 及以上级别的日志
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
# 获取当前模块的 logger 实例，日志输出时会带上模块名，便于定位问题来源

class CID2PropertiesTool:
    """CID2Properties Tool Class - Query compound properties by PubChem CID.
    CID 到属性查询工具类。不继承 BaseTool（非直接 CrewAI 工具），
    而是作为纯业务逻辑类，供 CrewAI 包装器调用。"""

    def __init__(self):
        """Initialize CID2Properties tool.
        初始化工具实例时获取 PubChem 工具的单例引用。"""
        self.pubchem_tool = get_pubchem_tool()
        # 将 PubChem 工具实例存储为实例属性，供后续方法调用时使用

    def get_properties_by_cid(self, cid: str) -> Dict[str, Any]:
        """
        Query compound properties by PubChem CID.
        根据 PubChem CID 查询化合物的详细属性信息。

        Args:
            cid (str): PubChem compound ID PubChem 化合物 ID（字符串格式，内部会转为整数）

        Returns:
            Dict[str, Any]: Dictionary containing compound properties
            返回包含化合物属性的字典，结构为 {"success": bool, "cid": str, ...属性字段}
        """
        try:
            # 调用 PubChem 工具通过 CID 查询化合物信息，cid 从字符串转为整数
            result = self.pubchem_tool.get_properties_by_cid(int(cid))
            # int(cid) 确保 CID 以整数格式传递给 PubChem API

            # 检查查询是否成功（结果中不含 "error" 键则表示成功）
            if "error" not in result:
                # 解析 PubChem API 返回的嵌套数据结构
                # PubChem 的 PropertyTable.Properties 数组中包含第一个匹配结果的属性
                if "PropertyTable" in result and "Properties" in result["PropertyTable"]:
                    properties = result["PropertyTable"]["Properties"][0]
                    # 取 Properties 数组的第一个元素（根据 CID 查询通常只有一个结果）

                    return {
                        "success": True,
                        # 标记查询成功

                        "cid": cid,
                        # 保留原始查询的 CID，方便调用方对照

                        "molecular_formula": properties.get("MolecularFormula", "N/A"),
                        # 分子式，如 H2O、C6H12O6 等，不存在则返回 "N/A"

                        "molecular_weight": properties.get("MolecularWeight", "N/A"),
                        # 分子量（相对分子质量），单位为 g/mol

                        "iupac_name": properties.get("IUPACName", "N/A"),
                        # IUPAC 系统命名法的化合物名称，是最权威的化学命名

                        "canonical_smiles": properties.get("CanonicalSMILES", "N/A"),
                        # 规范 SMILES 字符串，用于唯一表示分子结构的线性符号

                        "isomeric_smiles": properties.get("IsomericSMILES", "N/A"),
                        # 异构 SMILES 字符串，包含立体化学信息（如手性中心的标记）

                        "inchi": properties.get("InChI", "N/A"),
                        # IUPAC 国际化学标识符 (InChI)，标准的分子结构文本表示

                        "inchi_key": properties.get("InChIKey", "N/A")
                        # InChI Key，是 InChI 的哈希版本，用于数据库索引和搜索
                    }
                else:
                    return {
                        "success": False,
                        # 标记查询失败

                        "cid": cid,
                        # 保留 CID 供调用方参考

                        "error": "Unable to parse return data"
                        # 无法解析 PubChem API 返回的数据结构，可能是 API 格式变更
                    }
            else:
                return {
                    "success": False,
                    # 标记查询失败

                    "cid": cid,
                    # 保留 CID 供调用方参考

                    "error": result.get("error", "Query failed")
                    # 返回 PubChem API 返回的具体错误信息，若为空则给出默认提示
                }

        except Exception as e:
            logger.error(f"Error querying compound properties by CID: {e}")
            # 记录异常信息到日志，包含具体的错误描述

            return {
                "success": False,
                # 标记查询失败

                "cid": cid,
                # 保留 CID 供调用方参考

                "error": f"Query failed: {str(e)}"
                # 将异常信息包装为错误消息返回
            }

# 模块级别的全局变量，用于存储 CID2PropertiesTool 的单例实例
# 初始化为 None，首次调用时懒加载创建
_cid2properties_tool = None

def get_cid2properties_tool() -> CID2PropertiesTool:
    """
    Get CID2Properties tool instance.
    获取 CID2Properties 工具的单例实例。

    使用懒加载模式（Lazy Singleton），只在首次调用时创建实例，
    后续调用返回同一实例，避免重复创建和网络连接开销。

    Returns:
        CID2PropertiesTool: CID2Properties tool instance
        返回 CID2Properties 工具的全局唯一实例
    """
    global _cid2properties_tool
    # 声明使用模块级别的全局变量，以便在函数内修改

    if _cid2properties_tool is None:
        _cid2properties_tool = CID2PropertiesTool()
        # 首次调用时创建新实例，后续调用直接返回已有实例

    return _cid2properties_tool
    # 返回单例实例
