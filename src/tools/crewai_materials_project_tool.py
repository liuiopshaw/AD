# ---- 标准库导入 ----
import json                                            # JSON 序列化，用于返回结果给 CrewAI Agent

# ---- CrewAI 框架相关导入 ----
from typing import Optional, List                      # Python 类型注解
from crewai.tools import BaseTool                      # CrewAI 工具基类，所有 Agent 工具都继承它
from pydantic import BaseModel, Field                  # Pydantic 数据校验模型，定义工具输入参数的结构

# ---- 内部模块导入 ----
from src.tools.materials_project_tool import get_materials_project_tool  # 获取底层 MP API 工具单例
from src.utils.context_store import ContextStore       # 跨 Agent 共享的上下文缓存

# ============================================================================
#  Pydantic 输入模型 —— 定义 CrewAI 工具的参数结构
# ============================================================================

class MaterialsProjectToolInput(BaseModel):
    """
    Materials Project 工具的输入模型。
    Pydantic 的 Field 描述会被 CrewAI 框架用来自动生成工具的参数说明，
    Agent 调用工具时，框架会校验输入是否符合此模型。
    """
    action: str = Field(
        default="search",
        description="Action to perform ('search', 'get_material', 'get_summary')"
    )
    # Action 指定要执行的操作类型：
    # - "search": 按化学式/元素搜索材料
    # - "get_material": 按 material_id 获取详细材料信息
    # - "get_summary": 获取元素条件下的材料摘要

    material_id: Optional[str] = Field(
        default=None,
        description="Material ID (for get_material action)"
    )
    # Material ID 仅在 action="get_material" 时使用，格式为 "mp-XXXX"

    formula: Optional[str] = Field(
        default=None,
        description="Chemical formula (for search)"
    )
    # 化学式，如 "C3N4"、"Fe2O3"，仅在 action="search" 时使用

    elements: Optional[List[str]] = Field(
        default=None,
        description="Elements that must be included (for search/get_summary)"
    )
    # 必须包含的元素列表，如 ["Li", "Co", "O"]

    exclude_elements: Optional[List[str]] = Field(
        default=None,
        description="Elements to exclude (for search)"
    )
    # 需要排除的元素列表，用于过滤不需要的材料

    crystal_system: Optional[str] = Field(
        default=None,
        description="Crystal system (for search)"
    )
    # 晶体系统过滤条件，如 "cubic"、"hexagonal"

    limit: int = Field(
        default=100,
        description="Result limit (for search/get_summary)"
    )
    # 返回结果的最大条数，控制 API 调用数据量

    skip: int = Field(
        default=0,
        description="Results to skip (for search)"
    )
    # 跳过的结果数，用于分页查询

    fields: Optional[List[str]] = Field(
        default=None,
        description="Data fields to include"
    )
    # 指定返回的数据字段，如 ["material_id", "density", "volume"]

# ============================================================================
#  CrewAI 工具类 —— 将底层 API 封装为 Agent 可调用的工具
# ============================================================================

class CrewAIMaterialsProjectTool(BaseTool):
    """
    CrewAI 工具封装器 —— 将 Materials Project API 暴露给 CrewAI Agent。
    Agent 通过自然语言描述的工具定义来调用，框架自动将参数映射到 _run 方法。

    关键设计：
    - name 和 description 供 Agent 理解和决策时参考
    - args_schema 指定输入参数的结构，框架自动进行 JSON Schema 校验
    - _cache 是实例级缓存，与底层 MaterialsProjectTool 的缓存互补
    - ContextStore 提供跨 Agent 共享的数据缓存
    """

    # CrewAI 框架要求：name 是工具的展示名称，Agent 据此识别工具
    name: str = "Materials Project Database Access"

    # CrewAI 框架要求：description 是工具的功能描述，
    # Agent 会阅读此描述来决定何时调用该工具
    description: str = (
        "Access Materials Project database. "
        "Actions: 'search' (by formula/elements), 'get_material' (by ID), 'get_summary' (element-based summary). "
        "Usage: action='search', formula='C3N4'"
    )

    # Pydantic 模型，定义工具的输入参数 schema
    args_schema: type[BaseModel] = MaterialsProjectToolInput

    def __init__(self):
        """
        初始化 CrewAI Materials Project 工具。
        设置实例级缓存（字典 + TTL），与底层工具的单例缓存互相补充。
        """
        super().__init__()
        # 实例级缓存：存储 (timestamp, result) 元组
        self._cache: dict = {}
        # 缓存有效期：600 秒（10 分钟）
        self._ttl_seconds = 600

    def _sanitize_fields(self, fields: Optional[List[str]], action: str) -> Optional[List[str]]:
        """
        字段白名单过滤 —— 防止 Agent 请求不支持的字段导致 API 错误。

        根据 action 类型限制允许的字段：
        - search: 允许基本字段（无 symmetry 嵌套对象）
        - 其他 (get_material 等): 允许包含 symmetry

        Args:
            fields: 用户请求的字段列表
            action: 当前操作类型

        Returns:
            过滤后的安全字段列表，或 None
        """
        if not fields:
            return None
        # 搜索时可用的字段（不含嵌套的 symmetry 对象）
        allowed_search = {"material_id", "formula_pretty", "chemsys", "volume", "density", "nsites"}
        # 详细信息时可用的字段（增加了 symmetry）
        allowed_detail = allowed_search | {"symmetry"}
        if action == "search":
            # 搜索时只保留白名单内的字段
            return [f for f in fields if f in allowed_search]
        # 非搜索操作使用更宽的白名单
        return [f for f in fields if f in allowed_detail]

    def _run(
        self,
        action: str = "search",
        material_id: Optional[str] = None,
        formula: Optional[str] = None,
        elements: Optional[List[str]] = None,
        exclude_elements: Optional[List[str]] = None,
        crystal_system: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
        fields: Optional[List[str]] = None
    ) -> str:
        """
        执行 Materials Project API 操作 —— CrewAI 框架的核心调用入口。

        CrewAI 框架会将 Agent 的请求自动映射为 _run 方法的参数，
        该方法处理后返回 JSON 字符串给 Agent。

        缓存策略（多层）：
        1. ContextStore（跨 Agent 共享）：先检查全局缓存
        2. 实例级 _cache：再检查实例缓存
        3. 底层 API 调用：最后才调用底层工具的缓存/API

        Args:
            action: 操作类型 ("search", "get_material", "get_summary")
            material_id: 材料 ID（get_material 操作使用）
            formula: 化学式（search 操作使用）
            elements: 必需元素列表（search/get_summary 操作使用）
            exclude_elements: 排除元素列表（search 操作使用）
            crystal_system: 晶体系统（search 操作使用）
            limit: 结果数量限制
            skip: 跳过的结果数
            fields: 需要返回的数据字段

        Returns:
            JSON 格式的 API 响应字符串（Agent 直接读取此字符串）
        """
        try:
            # ---- 获取底层 MaterialsProjectTool 单例 ----
            tool = get_materials_project_tool()

            # ---- 构建缓存键 ----
            # 缓存键包含全部查询参数，确保不同查询的缓存互不干扰
            key = (
                action,
                material_id or "",
                formula or "",
                tuple(elements) if elements else (),
                tuple(exclude_elements) if exclude_elements else (),
                crystal_system or "",
                int(limit or 0),
                int(skip or 0),
                tuple(fields) if fields else ()
            )

            import time as _t
            now = _t.time()

            # ---- 第一层缓存：ContextStore（跨 Agent 共享缓存） ----
            # 缓存键携带查询条件（formula / material_id），保证：
            # - 同一材料的多个评估 Agent 之间可以复用结果（键相同）
            # - 不同材料的查询不会命中彼此缓存，避免跨材料串数据
            if action == "search":
                # 按具体化学式检查缓存（不使用泛化键，避免命中其他材料的查询结果）
                if formula:
                    cached_ctx = ContextStore.get(f"materials_project_search:{formula}")
                    if cached_ctx is not None:
                        return json.dumps(cached_ctx, ensure_ascii=False, indent=2)
            elif action == "get_material" and material_id:
                # 检查按 material_id 的缓存
                cached_ctx = ContextStore.get(f"materials_project_get:{material_id}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # ---- 第二层缓存：实例级缓存 ----
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # ---- 根据 action 类型执行对应的底层操作 ----
            if action == "search":
                # 对字段做安全过滤
                fields = self._sanitize_fields(fields, action)
                # 如果按元素查询，限制 limit 为 10 以避免拉取过多数据
                if elements and (limit is None or limit > 10):
                    limit = 10
                result = tool.search_materials(
                    formula=formula,
                    elements=elements,
                    exclude_elements=exclude_elements,
                    crystal_system=crystal_system,
                    limit=min(limit or 100, 10),  # 上限 10，控制数据量
                    skip=skip,
                    fields=fields
                )
            elif action == "get_material":
                # 通过 material_id 获取详情时必须提供 ID
                if not material_id:
                    return json.dumps({"error": "material_id required for get_material action"})
                fields = self._sanitize_fields(fields, action)
                result = tool.get_material_by_id(material_id)
                # 存入 ContextStore，供其他 Agent 复用（仅缓存成功结果，错误结果不入永久缓存）
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"materials_project_get:{material_id}", result)
            elif action == "get_summary":
                # 获取材料摘要信息
                result = tool.get_materials_summary(
                    elements=elements,
                    limit=min(limit or 100, 100)  # 确保 limit 不超过 100
                )
            else:
                # 不支持的操作类型，返回错误信息
                return json.dumps({"error": f"Unsupported action: {action}"})

            # ---- 更新缓存并返回结果 ----
            # 更新实例级缓存
            self._cache[key] = (now, result)
            # 更新 ContextStore（跨 Agent 共享）
            # 仅按化学式键缓存成功结果：错误结果（含 "error"）不写入永久缓存，
            # 且不使用泛化键，避免不同材料的查询结果互相污染
            if action == "search" and isinstance(result, dict) and "error" not in result:
                if formula:
                    ContextStore.set(f"materials_project_search:{formula}", result)
            # 返回 JSON 字符串（CrewAI 框架要求 _run 返回 str）
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            # 异常兜底：返回格式化的错误信息 JSON
            return json.dumps({"error": f"Operation error: {str(e)}"}, ensure_ascii=False)

# ============================================================================
#  模块级工具实例 —— 供工具工厂直接导入使用
# ============================================================================

# 创建全局唯一的 CrewAIMaterialsProjectTool 实例
# 该实例被 factory.py 中的 ToolFactory 直接引用
materials_project_tool = CrewAIMaterialsProjectTool()
