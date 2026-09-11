#!/usr/bin/env python3
"""
PNEC Tool.
PNEC (Predicted No Effect Concentration) database query tool.
Used to query predicted no effect concentration data of chemical substances.

本模块提供 PNEC（预测无效应浓度）数据的查询功能。PNEC 是环境风险评估中的关键指标，
表示化学物质在环境中不会对生态系统产生不利影响的最大浓度。
"""

import logging
import re
import requests
from typing import Dict, Any, List

# 配置日志：设置默认日志级别为 WARNING，避免过多的调试信息干扰
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class PNECTool:
    """PNEC Tool Class - Query predicted no effect concentration data of chemical substances.

    本工具类提供两种查询方式：
    1. 通过 CAS 号查询 PNEC 数据
    2. 通过化合物名称查询 PNEC 数据
    内部使用 PubChem API 获取化合物基本信息；PNEC 数值仅来自内置的金属毒性
    参考数据（公开文献值）。对无参考数据的化合物，诚实返回"无数据"，不提供估算值。
    """

    def __init__(self):
        """Initialize PNEC tool.

        初始化时完成以下工作：
        - 设置 PubChem REST API 的基础 URL
        - 创建可复用的 HTTP 会话（复用 TCP 连接，提升请求效率）
        - 设置 User-Agent 以标识请求来源
        - 加载内置的金属毒性参考数据（来源于公开文献）
        """
        # PubChem 是 NIH 维护的开放化学数据库，提供化合物的结构、性质等公开信息
        self.base_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
        # 使用 Session 对象保持 HTTP 连接，避免每次请求都重新建立 TCP 连接
        self.session = requests.Session()
        # 设置自定义 User-Agent 头部，便于 API 服务端识别和追踪请求来源
        self.session.headers.update({
            "User-Agent": "ECOMATS-PNEC-Tool/1.0"
        })

        # 常见金属元素及其对应价态的毒性数据
        # 键为元素符号，值为该元素在不同价态下的淡水 PNEC 数据
        # 这些数据来源于公开的环境风险研究文献，仅作为参考
        self.metal_toxicity_data = {
            "Ni": {
                "valences": ["Ni²⁺"],  # 镍在水环境中的常见价态
                "cas_numbers": ["7440-02-0"],
                "freshwater_pnec": {
                    "Ni²⁺": {"value": 0.02, "unit": "mg/L", "description": "Ni²⁺离子在淡水中的预测无效应浓度"}
                }
            },
            "W": {
                "valences": ["W⁶⁺"],  # 钨在水环境中的常见价态
                "cas_numbers": ["7440-07-5"],
                "freshwater_pnec": {
                    "W⁶⁺": {"value": 0.1, "unit": "mg/L", "description": "W⁶⁺离子在淡水中的预测无效应浓度"}
                }
            },
            "Co": {
                "valences": ["Co²⁺"],  # 钴在水环境中的常见价态
                "cas_numbers": ["7440-48-4"],
                "freshwater_pnec": {
                    "Co²⁺": {"value": 0.01, "unit": "mg/L", "description": "Co²⁺离子在淡水中的预测无效应浓度"}
                }
            },
            "Mo": {
                "valences": ["Mo⁶⁺"],  # 钼在水环境中的常见价态
                "cas_numbers": ["7439-98-7"],
                "freshwater_pnec": {
                    "Mo⁶⁺": {"value": 0.05, "unit": "mg/L", "description": "Mo⁶⁺离子在淡水中的预测无效应浓度"}
                }
            },
            "Fe": {
                "valences": ["Fe²⁺", "Fe³⁺"],  # 铁有两种常见价态，分别给出对应的 PNEC
                "cas_numbers": ["7439-89-6"],
                "freshwater_pnec": {
                    "Fe²⁺": {"value": 0.5, "unit": "mg/L", "description": "Fe²⁺离子在淡水中的预测无效应浓度"},
                    "Fe³⁺": {"value": 0.3, "unit": "mg/L", "description": "Fe³⁺离子在淡水中的预测无效应浓度"}
                }
            }
        }

    def get_pnec_by_cas(self, cas_number: str) -> Dict[str, Any]:
        """
        Query PNEC data by CAS number.
        通过 CAS 号查询 PNEC 数据。这是最精确的查询方式，因为每个化合物都有唯一的 CAS 号。

        Args:
            cas_number (str): CAS number of the chemical substance
                              CAS 号（Chemical Abstracts Service Registry Number），
                              是化学物质的唯一标识符，格式通常为 XXX-XX-X

        Returns:
            Dict[str, Any]: Dictionary containing PNEC data
                            返回包含化合物名称、分子式、分子量、价态分析和 PNEC 数据的字典
        """
        try:
            # 第一步：通过 CAS 号从 PubChem 获取化合物的基本信息
            compound_info = self._get_compound_info_by_cas(cas_number)

            # 如果 PubChem 查询失败，直接返回错误信息
            if "error" in compound_info:
                return {
                    "success": False,
                    "cas_number": cas_number,
                    "error": compound_info["error"]
                }

            # 第二步：分析化合物中金属元素的价态
            # 价态分析对于 PNEC 计算很重要，因为同一元素不同价态的毒性可能差异很大
            valence_analysis = self._analyze_element_valences(compound_info)

            # 第三步：汇总 PNEC 数据可用性
            # 注意：本工具未接入专业 PNEC 数据库，无真实数据时诚实返回"无数据"
            pnec_data = self._calculate_pnec(compound_info)

            return {
                "success": True,
                "cas_number": cas_number,
                "compound_name": compound_info.get("name", ""),
                "molecular_formula": compound_info.get("molecular_formula", ""),
                "molecular_weight": compound_info.get("molecular_weight", ""),
                "valence_analysis": valence_analysis,
                "pnec_data": pnec_data
            }

        except Exception as e:
            # 捕获所有异常，确保工具不会因为意外错误而崩溃
            logger.error(f"Error querying PNEC by CAS number: {e}")
            return {
                "success": False,
                "cas_number": cas_number,
                "error": f"Query failed: {str(e)}"
            }

    def get_pnec_by_name(self, compound_name: str) -> Dict[str, Any]:
        """
        Query PNEC data by compound name.
        通过化合物名称查询 PNEC 数据。这是一个两步查询：
        1. 先将名称转换为 CAS 号
        2. 再通过 CAS 号查询 PNEC

        Args:
            compound_name (str): Chemical substance name
                                 化合物名称，可以是 IUPAC 名称、通用名或商品名

        Returns:
            Dict[str, Any]: Dictionary containing PNEC data
        """
        try:
            # 第一步：通过化合物名称获取其 CAS 号
            # PubChem 支持通过名称搜索化合物
            cas_result = self._get_cas_by_name(compound_name)

            # 如果名称到 CAS 的转换失败，返回错误
            if "error" in cas_result:
                return {
                    "success": False,
                    "compound_name": compound_name,
                    "error": cas_result["error"]
                }

            # 提取 CAS 号，如果为空则报错
            cas_number = cas_result.get("cas_number")
            if not cas_number:
                return {
                    "success": False,
                    "compound_name": compound_name,
                    "error": "Could not get CAS number for the compound"
                }

            # 第二步：复用已有方法通过 CAS 号查询 PNEC 数据
            # 这种设计避免了代码重复，遵循 DRY（Don't Repeat Yourself）原则
            return self.get_pnec_by_cas(cas_number)

        except Exception as e:
            logger.error(f"Error querying PNEC by compound name: {e}")
            return {
                "success": False,
                "compound_name": compound_name,
                "error": f"Query failed: {str(e)}"
            }

    def _get_compound_info_by_cas(self, cas_number: str) -> Dict[str, Any]:
        """
        Get compound basic info by CAS number.
        通过 CAS 号从 PubChem 获取化合物基本信息。
        这是内部方法（以 _ 开头），不对外暴露。

        Args:
            cas_number (str): CAS number

        Returns:
            Dict[str, Any]: Compound basic info
                           包含 CID、分子式、分子量、IUPAC 名称、SMILES 等信息
        """
        try:
            # 构造 PubChem PUG REST API 的请求 URL
            # PUG (Power User Gateway) 是 PubChem 的 REST 风格 API
            # 注意：CAS 号不是 PubChem CID，不能直接请求 compound/cid/{cas}。
            # 正确做法：CAS 号作为同义词收录在 PubChem 中，
            # 因此使用 name 端点先将 CAS 号解析为 CID 列表
            url = f"{self.base_url}/compound/name/{cas_number}/cids/JSON"
            # 设置 30 秒超时，防止因网络问题导致请求无限等待
            response = self.session.get(url, timeout=30)
            # 如果服务器返回错误状态码（4xx/5xx），自动抛出异常
            response.raise_for_status()
            data = response.json()

            # IdentifierList.CID 包含该 CAS 号（同义词）匹配到的化合物 CID
            cids = data.get("IdentifierList", {}).get("CID", [])
            if cids:
                # 取第一个匹配的 CID（PubChem 内部唯一标识）
                cid = cids[0]

                # 通过 CID 获取更详细的化合物属性信息
                details = self._get_compound_details(cid)
                if "error" in details:
                    return details
                # 将原始查询的 CAS 号也加入详情中，方便追溯
                details["cas_number"] = cas_number
                return details
            else:
                return {"error": "Compound not found for this CAS number"}

        except requests.exceptions.RequestException as e:
            # 网络请求异常（连接超时、DNS 失败、服务器错误等）
            logger.error(f"PubChem API request failed: {e}")
            return {"error": f"API request failed: {str(e)}"}
        except Exception as e:
            # 数据解析等其他异常
            logger.error(f"Error processing response: {e}")
            return {"error": f"Error processing response: {str(e)}"}

    def _get_cas_by_name(self, compound_name: str) -> Dict[str, Any]:
        """
        Get CAS number by compound name.
        通过化合物名称从 PubChem 获取 CAS 号。
        名称搜索可能返回多个候选，这里取第一个匹配结果。

        Args:
            compound_name (str): Compound name

        Returns:
            Dict[str, Any]: Info containing CAS number
        """
        try:
            # 使用 PubChem 的名称搜索接口
            url = f"{self.base_url}/compound/name/{compound_name}/json"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "PC_Compounds" in data and len(data["PC_Compounds"]) > 0:
                compound = data["PC_Compounds"][0]
                # PUG JSON 中 id.id 的结构是 {"cid": 2244}，需要取出其中的整数值
                cid_obj = compound["id"]["id"]
                cid = cid_obj.get("cid") if isinstance(cid_obj, dict) else cid_obj

                # 获取化合物详情以提取 CAS 号
                # PubChem 的 name 搜索返回摘要，详细信息需要单独查询
                details = self._get_compound_details(cid)
                return {
                    "cas_number": details.get("cas_number", ""),
                    "name": details.get("name", compound_name)
                }
            else:
                return {"error": "Info not found for this compound name"}

        except requests.exceptions.RequestException as e:
            logger.error(f"PubChem API request failed: {e}")
            return {"error": f"API request failed: {str(e)}"}
        except Exception as e:
            logger.error(f"Error processing response: {e}")
            return {"error": f"Error processing response: {str(e)}"}

    def _get_compound_details(self, cid: str) -> Dict[str, Any]:
        """
        Get compound detailed info.
        通过 PubChem CID 获取化合物详细属性信息。

        Args:
            cid (str): PubChem compound ID
                       PubChem 内部为每个化合物分配的唯一数字标识符

        Returns:
            Dict[str, Any]: Compound detailed info
                           包括分子式、分子量、IUPAC名称、SMILES 等
        """
        try:
            # 使用 PubChem 的 property 接口批量获取所需属性
            # 一次请求获取多个属性，比逐个查询更高效
            # 需要的属性：标题（常用名）、分子式、分子量、IUPAC名称、标准SMILES、异构SMILES
            url = f"{self.base_url}/compound/cid/{cid}/property/Title,MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES/JSON"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # PropertyTable.Properties 包含了请求的所有属性值
            if "PropertyTable" in data and "Properties" in data["PropertyTable"] and len(data["PropertyTable"]["Properties"]) > 0:
                properties = data["PropertyTable"]["Properties"][0]
                # CAS 号不是 PubChem 的独立属性字段，需要从同义词（Synonyms）列表中
                # 按 CAS 格式（2-7位数字-2位数字-1位数字）正则提取
                cas_number = self._get_cas_from_synonyms(cid)
                return {
                    "cid": cid,
                    "name": properties.get("Title", ""),
                    "cas_number": cas_number,
                    "molecular_formula": properties.get("MolecularFormula", ""),
                    "molecular_weight": properties.get("MolecularWeight", ""),
                    "iupac_name": properties.get("IUPACName", ""),
                    "canonical_smiles": properties.get("CanonicalSMILES", ""),
                    "isomeric_smiles": properties.get("IsomericSMILES", "")
                }
            else:
                return {"error": "Could not get compound detailed info"}

        except requests.exceptions.RequestException as e:
            logger.error(f"PubChem API request failed: {e}")
            return {"error": f"API request failed: {str(e)}"}
        except Exception as e:
            logger.error(f"Error processing response: {e}")
            return {"error": f"Error processing response: {str(e)}"}

    def _get_cas_from_synonyms(self, cid) -> str:
        """
        Extract CAS number from compound synonyms.
        从化合物的同义词列表中提取 CAS 号。
        PubChem 没有独立的 CAS 属性字段，CAS 号作为同义词存储，
        需要通过 /synonyms 端点获取并按格式过滤。

        Args:
            cid: PubChem compound ID

        Returns:
            str: 第一个匹配 CAS 格式的同义词；未找到时返回空字符串
        """
        try:
            # 同义词端点：返回该化合物的全部同义词列表
            url = f"{self.base_url}/compound/cid/{cid}/synonyms/JSON"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            info_list = data.get("InformationList", {}).get("Information", [])
            if info_list:
                synonyms = info_list[0].get("Synonym", [])
                # CAS 号格式：^\d{2,7}-\d{2}-\d$，如 50-78-2（阿司匹林）、7440-02-0（镍）
                cas_pattern = r'^\d{2,7}-\d{2}-\d$'
                for syn in synonyms:
                    if re.match(cas_pattern, syn):
                        return syn
            return ""
        except Exception as e:
            # 同义词查询失败不阻断主流程，仅记录日志并返回空
            logger.warning(f"Failed to extract CAS number from synonyms (CID={cid}): {e}")
            return ""

    def _analyze_element_valences(self, compound_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze valence states of metal elements in compound.
        分析化合物中金属元素的价态。这对于 PNEC 计算很重要，因为：
        - 同一金属元素的不同价态可能具有显著不同的毒性
        - 例如 Fe²⁺ 和 Fe³⁺ 的 PNEC 值不同

        Args:
            compound_info (Dict[str, Any]): Compound info

        Returns:
            Dict[str, Any]: Element valence analysis result
        """
        try:
            # 获取化合物名称和分子式
            compound_name = compound_info.get("name", "")
            molecular_formula = compound_info.get("molecular_formula", "")

            # 从分子式中提取元素符号列表
            # 例如 "H2O" 提取为 ["H", "O"]，"NiSO4" 提取为 ["Ni", "S", "O"]
            elements = self._extract_elements_from_formula(molecular_formula)

            # 遍历提取出的元素，匹配内置的金属毒性数据
            # 只保留在我们的金属毒性数据字典中有记录的元素
            metal_valences = {}
            for element in elements:
                if element in self.metal_toxicity_data:
                    metal_info = self.metal_toxicity_data[element]
                    # 记录该元素在淡水中的不同价态及对应的 PNEC 数据
                    metal_valences[element] = {
                        "valences": metal_info["valences"],
                        "cas_numbers": metal_info["cas_numbers"],
                        "toxicity_data": metal_info["freshwater_pnec"]
                    }

            return {
                "success": True,
                "compound_name": compound_name,
                "molecular_formula": molecular_formula,
                "metal_elements": metal_valences
            }

        except Exception as e:
            logger.error(f"Error analyzing element valences: {e}")
            return {
                "success": False,
                "error": f"Error analyzing element valences: {str(e)}"
            }

    def _extract_elements_from_formula(self, formula: str) -> List[str]:
        """
        Extract element symbols from chemical formula.
        从化学式中提取元素符号列表。
        化学式中的元素符号规则：一个大写字母可选跟一个小写字母（如 Na、Fe、Cl）。

        Args:
            formula (str): Chemical formula
                           化学式字符串，例如 "NiSO4·6H2O"、"Fe2O3"

        Returns:
            List[str]: List of element symbols (deduplicated)
                       去重后的元素符号列表
        """
        import re
        # 正则匹配元素符号：一个大写字母后跟0-1个小写字母
        # 这是元素符号的标准模式（如 H, He, Li, Na 等）
        elements = re.findall(r'[A-Z][a-z]?', formula)
        # 过滤掉可能不是元素的短字符串（通过常见元素列表验证）
        valid_elements = []
        # 常见元素列表（简化版，涵盖周期表中大多数常见元素）
        # 用于验证提取出的符号是否为有效的化学元素
        common_elements = ['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar',
                          'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr',
                          'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
                          'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
                          'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn']

        for element in elements:
            # 只保留确认在元素周期表中的符号
            if element in common_elements:
                valid_elements.append(element)

        # 使用 set 去重后转回列表（一个元素可能在化学式中出现多次）
        return list(set(valid_elements))

    def _calculate_pnec(self, compound_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Report PNEC data availability for the compound.
        报告该化合物的 PNEC 数据可用性。

        说明：本工具未接入专业的 PNEC/生态毒性数据库，无法给出真实的
        PNEC 数值。按照项目规则，禁止使用编造公式或硬编码数据冒充真实
        查询结果，因此此处诚实地返回"无数据"，绝不返回估算值。
        可用的真实数据仅来自内置金属毒性参考表（见 valence_analysis）。

        Args:
            compound_info (Dict[str, Any]): Compound info

        Returns:
            Dict[str, Any]: 标明数据不可用的结果（不含任何编造的 PNEC 数值）
        """
        return {
            "acute_pnec": None,
            "chronic_pnec": None,
            "data_available": False,
            "note": "无真实 PNEC 数据：本工具未接入专业 PNEC/生态毒性数据库，不提供估算值"
        }

# 全局实例变量（用于实现单例模式）
# 使用模块级别的 _pnec_tool 变量保存 PNECTool 的唯一实例
_pnec_tool = None

def get_pnec_tool() -> PNECTool:
    """
    Get PNEC tool instance.
    获取 PNEC 工具实例。实现单例模式，确保全局只有一个 PNECTool 实例。
    这样可以：
    - 复用 HTTP Session，减少连接开销
    - 避免重复初始化内置数据
    - 保证多线程/多 Agent 环境下的数据一致性

    Returns:
        PNECTool: PNEC tool instance
    """
    global _pnec_tool
    # 仅在首次调用时创建实例（惰性初始化）
    if _pnec_tool is None:
        _pnec_tool = PNECTool()
    return _pnec_tool
