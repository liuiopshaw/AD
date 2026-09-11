# ---- 标准库导入 ----
import json                                            # JSON 序列化，将查询结果转为 Agent 可读的字符串

# ---- CrewAI 框架相关导入 ----
from crewai.tools import BaseTool                      # CrewAI 工具基类
from pydantic import BaseModel, Field                  # Pydantic 数据校验模型，定义工具的输入参数结构

# ---- 内部模块导入 ----
from src.tools.pubchem_tool import get_pubchem_tool   # 获取底层 PubChemTool 单例
from src.utils.context_store import ContextStore       # 跨 Agent 共享的上下文缓存存储

# ============================================================================
#  Pydantic 输入模型 —— 定义 CrewAI 工具的参数结构
# ============================================================================

class PubChemToolInput(BaseModel):
    """
    PubChem 工具的输入模型。
    CrewAI 框架会根据 Field 的 description 自动生成 Agent 能理解的参数说明，
    然后自动将 Agent 的调用请求映射为 _run 方法的参数。
    """

    query: str = Field(
        description="Query content (chemical name, formula or InChIKey)"
    )
    # query 是必填字段——要查询的化学物质标识符。
    # 支持三种格式：化合物名称（如 "caffeine"）、分子式（如 "C8H10N4O2"）、InChIKey

    search_type: str = Field(
        default="auto",
        description="Query type ('auto', 'name', 'formula', 'inchikey')"
    )
    # search_type 控制查询路由方式：
    # - "auto": 自动检测 query 格式并选择合适的端点（推荐）
    # - "name": 强制按化合物名称查询
    # - "formula": 强制按分子式查询（使用 fastformula 端点）
    # - "inchikey": 强制按 InChIKey 查询

    get_cas: bool = Field(
        default=True,
        description="Whether to get CAS number"
    )
    # get_cas=True 时调用 get_compound_info_with_cas，从同义词中提取 CAS 号
    # 注意：get_full_info 优先级高于 get_cas

    get_full_info: bool = Field(
        default=False,
        description="Whether to get full compound info"
    )
    # get_full_info=True 时调用 get_compound_info，返回最完整的属性集合
    # 包含 SMILES、InChI、XLogP、TPSA 等全部计算属性

# ============================================================================
#  CrewAI 工具类 —— 将 PubChem API 封装为 Agent 可调用的工具
# ============================================================================

class CrewAIPubChemTool(BaseTool):
    """
    CrewAI 工具封装器 —— 将 PubChem REST API 暴露给 CrewAI Agent。

    设计要点：
    - name 和 description 是 Agent 用来理解工具功能的描述性文本
    - args_schema 定义了工具接受的参数结构，框架自动校验
    - _run 方法是核心执行入口，返回 JSON 字符串
    - 缓存策略：ContextStore（跨 Agent） > 实例级 _cache > 底层 API

    使用场景：
    - 验证化学信息：查询化合物的分子量、分子式等属性
    - 获取安全数据：查询化合物的毒性和物化性质
    - 提取 CAS 号：从同义词列表中提取标准的 CAS 标识符
    """

    # CrewAI 框架要求：name 供 Agent 识别工具
    name: str = "PubChem Database Query"

    # CrewAI 框架要求：description 描述工具功能和使用方式
    # Agent 会根据此描述决定是否调用该工具
    description: str = (
        "Query PubChem chemical database to get compound information. "
        "Search compounds by name, formula or InChIKey. "
        "Get CAS number, molecular weight, SMILES, InChI and other properties. "
        "Use when you need to verify chemical info or get compound details."
    )

    # Pydantic 输入参数模型，CrewAI 框架根据它生成 JSON Schema 并校验输入
    args_schema: type[BaseModel] = PubChemToolInput

    def __init__(self):
        """
        初始化 CrewAI PubChem 工具。
        创建实例级缓存，与底层 PubChemTool 的缓存和 ContextStore 形成三级缓存体系。
        """
        super().__init__()
        # 实例级缓存字典：key -> (timestamp, result) 元组
        self._cache = {}
        # 缓存有效期：600 秒（10 分钟），过期后重新查询
        self._ttl_seconds = 600

    def _run(
        self,
        query: str,
        search_type: str = "auto",
        get_cas: bool = True,
        get_full_info: bool = False
    ) -> str:
        """
        执行 PubChem 数据库查询 —— CrewAI 框架的核心调用入口。

        CrewAI 框架会将 Agent 的请求自动映射为 _run 方法的参数。

        缓存策略（三层，从快到慢）：
        1. ContextStore（全局跨 Agent 缓存）：按查询类型+内容查找
        2. 实例级 _cache：按完整参数组合查找
        3. 底层 PubChemTool API 调用：通过 HTTP 请求获取真实数据

        查询优先级逻辑：
        - 如果 get_full_info=True：调用 get_compound_info（最完整属性）
        - 否则如果 get_cas=True（默认）：调用 get_compound_info_with_cas（含 CAS 号）
        - 否则：调用 search_compound（基础查询）

        Args:
            query: 查询内容（化合物名称、分子式或 InChIKey）
            search_type: 查询类型（"auto", "name", "formula", "inchikey"）
            get_cas: 是否获取 CAS 号（默认 True）
            get_full_info: 是否获取完整化合物信息（默认 False）

        Returns:
            JSON 格式的查询结果字符串（Agent 直接解析和阅读）
        """
        try:
            # ---- 构建缓存键 ----
            # 缓存键包含所有影响查询结果的参数
            key = (query, search_type, bool(get_cas), bool(get_full_info))

            import time as _t
            now = _t.time()

            # ---- 第一层缓存：ContextStore（跨 Agent 共享的全局缓存） ----
            # 根据查询类型使用不同的缓存命名空间，避免不同类型缓存互相污染
            if get_full_info:
                # 完整信息查询缓存，键格式: pubchem_full:<query>
                cached_ctx = ContextStore.get(f"pubchem_full:{query}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)
            elif get_cas:
                # 含 CAS 号查询缓存，键格式: pubchem_cas:<query>
                cached_ctx = ContextStore.get(f"pubchem_cas:{query}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)
            else:
                # 基础搜索缓存，键格式: pubchem_search:<type>:<query>
                # 这里的 type 是 search_type（"auto"/"name"/"formula"/"inchikey"）
                cached_ctx = ContextStore.get(f"pubchem_search:{search_type}:{query}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # ---- 第二层缓存：实例级缓存 ----
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # ---- 第三层：调用底层 PubChemTool API ----
            # 获取 PubChemTool 单例实例
            tool = get_pubchem_tool()

            # 仅将成功结果写入 ContextStore（无 TTL 的永久缓存）：
            # 含 "error" 的失败结果不缓存，避免错误结果被后续查询永久复用
            if get_full_info:
                # 获取最完整的化合物信息（含所有计算属性）
                result = tool.get_compound_info(query)
                # 更新全局缓存
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pubchem_full:{query}", result)
            elif get_cas:
                # 获取含 CAS 号的化合物信息
                result = tool.get_compound_info_with_cas(query)
                # 更新全局缓存
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pubchem_cas:{query}", result)
            else:
                # 基础搜索（使用智能路由自动判断查询类型）
                result = tool.search_compound(query, search_type)
                # 更新全局缓存
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pubchem_search:{search_type}:{query}", result)

            # ---- 更新实例级缓存 ----
            self._cache[key] = (now, result)

            # ---- 返回 JSON 字符串 ----
            # CrewAI 框架要求 _run 方法返回字符串类型
            # ensure_ascii=False 允许直接输出中文等 Unicode 字符
            # indent=2 使输出更易读
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            # 异常兜底：返回格式化的错误 JSON 字符串
            # ensure_ascii=False: 允许非 ASCII 字符原生输出
            return json.dumps({"error": f"Query error: {str(e)}"}, ensure_ascii=False)

# ============================================================================
#  模块级工具实例 —— 供工具工厂直接导入使用
# ============================================================================

# 创建全局唯一的 CrewAIPubChemTool 实例
# 该实例被 factory.py 中的 ToolFactory 直接引用
pubchem_tool = CrewAIPubChemTool()
