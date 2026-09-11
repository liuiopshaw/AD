import json
# 导入 CrewAI 框架的 BaseTool 基类
from crewai.tools import BaseTool
# 导入 Pydantic 的数据模型类，用于定义工具的输入参数 schema
from pydantic import BaseModel, Field
# 导入底层 MolPort 工具的单例获取函数
from src.tools.molport_tool import get_molport_tool
# 导入跨 Agent 上下文存储，用于在 Agent 之间共享查询结果
from src.utils.context_store import ContextStore

# ============================================================================
# 输入参数模型定义
# 每个 CrewAI 工具对应一个 Pydantic BaseModel，定义其接收的参数
# ============================================================================

class MolPortAvailabilityInput(BaseModel):
    """MolPort 可获得性查询输入参数

    用于检查化合物是否可从 MolPort 供应商处购买。
    """
    # smiles: 化合物的 SMILES 表示，如 "CCO"（乙醇）、"c1ccccc1"（苯）
    smiles: str = Field(description="化合物的 SMILES 字符串")
    # similarity_threshold: 判断"可获得"的相似度标准
    # 默认 0.95，即结构相似度 >= 95% 认为可获得
    similarity_threshold: float = Field(default=0.95, description="相似度阈值（0-1），默认0.95")

class MolPortSearchInput(BaseModel):
    """MolPort 结构搜索输入参数

    支持精确匹配、相似性搜索、子/超结构搜索等多种模式。
    """
    smiles: str = Field(description="化合物的 SMILES 字符串")
    # search_type: 1=子结构, 2=超结构, 3=精确, 4=相似性(默认), 5=完美, 6=精确片段
    search_type: int = Field(default=4, description="搜索类型：1=子结构，2=超结构，3=精确，4=相似性(默认)，5=完美，6=精确片段")
    # similarity_index: 仅对相似性搜索（类型 4）有效
    similarity_index: float = Field(default=0.9, description="相似度阈值（0-1），默认0.9")
    # max_results: 控制返回结果数量，避免数据过载
    max_results: int = Field(default=100, description="最大结果数，默认100（上限10000）")

class MolPortMoleculeInfoInput(BaseModel):
    """MolPort 分子信息查询输入参数

    通过 MolPort 内部 ID 查询分子的详细信息。
    """
    # molecule_id: MolPort 的唯一分子标识符
    molecule_id: str = Field(description="MolPort 分子ID（如 '2325020' 或 'Molport-002-325-020'）")


# ============================================================================
# CrewAI 工具类定义
# 每个工具封装 MolPortTool 的一个特定功能，使其可被 CrewAI Agent 调用
# ============================================================================

class CrewAIMolPortAvailabilityTool(BaseTool):
    """CrewAI 工具：检查化合物商业可获得性

    该工具帮助 Agent 判断一个化合物是否可以从商业供应商处购买，
    以及购买的条件（供应商数量、价格范围等）。
    这对于评估材料经济可行性和前体可获得性至关重要。
    """

    # 工具名称：CrewAI Agent 使用此名称来调用工具
    name: str = "MolPort 化合物可获得性检查器"
    # 工具描述：LLM 根据此描述判断何时使用此工具
    # 描述需要清晰说明工具的用途、输入输出和行为
    description: str = (
        "检查化合物的商业可获得性。"
        "通过 SMILES 字符串查询化合物是否可从供应商处购买。"
        "返回可获得性状态、匹配的化合物ID、库存水平等信息。"
        "用于评估材料经济可行性和前体可获得性。"
    )
    # 指定输入参数的数据模型（BaseModel 子类）
    args_schema: type[BaseModel] = MolPortAvailabilityInput

    def __init__(self):
        """初始化工具实例。

        设置本地内存缓存和相关配置。
        """
        super().__init__()
        # _cache: 本地内存缓存字典
        # 键为缓存键字符串，值为 (时间戳, 结果数据) 元组
        self._cache = {}
        # _ttl_seconds: 缓存有效期，3600 秒（1小时）
        # 可获得性数据相对稳定，所以 TTL 设置较长
        self._ttl_seconds = 3600

    def _run(self, smiles: str, similarity_threshold: float = 0.95) -> str:
        """
        检查化合物商业可获得性。

        缓冲策略：
        1. 先查跨 Agent 上下文缓存（ContextStore）
        2. 再查本地 TTL 缓存
        3. 最后执行实际查询

        Args:
            smiles: 化合物 SMILES 字符串
            similarity_threshold: 相似度阈值（0-1）

        Returns:
            JSON 格式的可获得性评估结果字符串
        """
        try:
            # 构造缓存键：包含 smiles 和相似度阈值
            # 不同相似度阈值会产生不同的结果，所以必须包含在键中
            cache_key = f"molport_availability:{smiles}:{similarity_threshold}"
            # 第一层缓存：跨 Agent 上下文存储
            # ContextStore 允许不同 Agent 之间共享同一查询的结果
            cached_ctx = ContextStore.get(cache_key)
            if cached_ctx is not None:
                return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # 第二层缓存：本地 TTL 内存缓存
            import time as _t
            now = _t.time()
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self._ttl_seconds:
                # 缓存未过期，直接返回缓存数据
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # 缓存未命中：获取底层工具并执行查询
            tool = get_molport_tool()
            result = tool.check_compound_availability(smiles, similarity_threshold)

            # 将结果同时写入两层缓存（ContextStore 仅缓存成功结果，错误结果不写入）
            if isinstance(result, dict) and "error" not in result:
                ContextStore.set(cache_key, result)      # 跨 Agent 缓存
            self._cache[cache_key] = (now, result)   # 本地 TTL 缓存

            # 返回 JSON 序列化结果
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            # 异常处理：返回包含错误信息的 JSON
            return json.dumps({"error": f"查询错误: {str(e)}"}, ensure_ascii=False)


class CrewAIMolPortSearchTool(BaseTool):
    """CrewAI 工具：MolPort 化学结构搜索

    支持多种搜索模式：
    - 精确搜索：查找结构完全相同的化合物
    - 相似性搜索：查找结构相似的化合物（最常用，用于找替代品）
    - 子结构搜索：查找包含指定子结构的化合物
    - 超结构搜索：查找被指定结构包含的化合物
    """

    name: str = "MolPort 化学结构搜索"
    description: str = (
        "在 MolPort 数据库中搜索化学结构。"
        "支持精确匹配、相似性搜索、子结构搜索等。"
        "通过 SMILES 字符串搜索相似化合物，获取 MolPort ID 和相似度指数。"
        "用于寻找相似的可购买化合物或验证材料设计可行性。"
    )
    args_schema: type[BaseModel] = MolPortSearchInput

    def __init__(self):
        super().__init__()
        self._cache = {}
        self._ttl_seconds = 3600  # 1 小时缓存

    def _run(
        self,
        smiles: str,
        search_type: int = 4,
        similarity_index: float = 0.9,
        max_results: int = 100
    ) -> str:
        """
        执行化学结构搜索。

        Args:
            smiles: 化合物 SMILES 字符串
            search_type: 搜索类型（1-6）
            similarity_index: 相似度阈值（0-1）
            max_results: 最大返回结果数

        Returns:
            JSON 格式的搜索结果字符串
        """
        try:
            # 构建缓存键：包含所有搜索参数，因为不同参数组合产生不同结果
            cache_key = f"molport_search:{search_type}:{smiles}:{similarity_index}:{max_results}"
            # 先查跨 Agent 上下文缓存
            cached_ctx = ContextStore.get(cache_key)
            if cached_ctx is not None:
                return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # 再查本地 TTL 缓存
            import time as _t
            now = _t.time()
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # 执行实际查询
            tool = get_molport_tool()
            result = tool.search_by_smiles(
                smiles,
                search_type=search_type,
                similarity_index=similarity_index,
                max_results=max_results
            )

            # 更新两层缓存（仅缓存成功结果，错误结果不写入无 TTL 的 ContextStore）
            if isinstance(result, dict) and "error" not in result:
                ContextStore.set(cache_key, result)
            self._cache[cache_key] = (now, result)

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps({"error": f"搜索错误: {str(e)}"}, ensure_ascii=False)


class CrewAIMolPortMoleculeInfoTool(BaseTool):
    """CrewAI 工具：获取 MolPort 分子详细信息

    通过 MolPort 的分子 ID 获取完整信息，包括：
    - 分子标识：SMILES、IUPAC 名称、分子式、分子量
    - 商业信息：供应商列表、价格、库存、交货时间
    - 用于评估特定化合物的商业可获得性和成本
    """

    name: str = "MolPort 分子信息加载器"
    description: str = (
        "通过 MolPort ID 获取化合物的详细信息，包括 SMILES、IUPAC 名称、分子式、"
        "分子量、供应商信息、库存、价格、交货时间等。"
        "用于评估特定化合物的商业可获得性和成本。"
    )
    args_schema: type[BaseModel] = MolPortMoleculeInfoInput

    def __init__(self):
        super().__init__()
        self._cache = {}
        self._ttl_seconds = 3600  # 1 小时缓存：分子信息相对稳定

    def _run(self, molecule_id: str) -> str:
        """
        获取分子详细信息。

        Args:
            molecule_id: MolPort 分子 ID（支持两种格式）

        Returns:
            JSON 格式的分子详细信息字符串
        """
        try:
            # 构建缓存键：仅使用 molecule_id 作为标识
            cache_key = f"molport_molecule:{molecule_id}"
            # 先查跨 Agent 上下文缓存
            cached_ctx = ContextStore.get(cache_key)
            if cached_ctx is not None:
                return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # 再查本地 TTL 缓存
            import time as _t
            now = _t.time()
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # 执行查询：使用 get_availability_info 获取完整的商业信息
            tool = get_molport_tool()
            result = tool.get_availability_info(molecule_id)

            # 更新两层缓存（仅缓存成功结果，错误结果不写入无 TTL 的 ContextStore）
            if isinstance(result, dict) and "error" not in result:
                ContextStore.set(cache_key, result)
            self._cache[cache_key] = (now, result)

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps({"error": f"信息获取错误: {str(e)}"}, ensure_ascii=False)


# ============================================================================
# 创建全局工具实例
# 这些实例在模块导入时创建，供 CrewAI Agent 配置使用
# ============================================================================

# 化合物可获得性检查工具实例
molport_availability_tool = CrewAIMolPortAvailabilityTool()
# 化学结构搜索工具实例
molport_search_tool = CrewAIMolPortSearchTool()
# 分子详细信息加载工具实例
molport_molecule_info_tool = CrewAIMolPortMoleculeInfoTool()
