import json
# 导入 CrewAI 框架的 BaseTool 基类，所有 CrewAI 工具都需要继承此类
from crewai.tools import BaseTool
# 导入 Pydantic 的数据模型类，用于定义工具的输入参数结构
# BaseModel 提供自动验证和类型检查，Field 用于添加参数描述和默认值
from pydantic import BaseModel, Field
# 导入底层 PNEC 查询工具的单例获取函数
from src.tools.pnec_tool import get_pnec_tool
# 导入上下文存储，用于在 Agent 之间共享查询结果（跨 Agent 缓存）
from src.utils.context_store import ContextStore

class PNECToolInput(BaseModel):
    """PNEC Tool Input Model

    定义 CrewAI PNEC 工具的输入参数模型。
    使用 Pydantic BaseModel 可以自动获得参数验证、类型检查和默认值功能。
    CrewAI 框架会根据此模型自动生成工具调用的参数 schema。
    """
    # query: 查询内容，可以是 CAS 号（如 "7440-02-0"）或化合物名称（如 "Nickel"）
    query: str = Field(description="查询内容（CAS号或化合物名称）")
    # query_type: 查询类型，默认为 "name"；设为 "cas" 时按 CAS 号查询
    query_type: str = Field(default="name", description="查询类型（'name' 或 'cas'）")

class CrewAIPNECTool(BaseTool):
    """CrewAI tool wrapper for PNEC data query

    将底层 PNECTool 封装为 CrewAI 框架可用的工具。
    继承 BaseTool 使其能被 CrewAI Agent 自动发现和调用。
    内置两层缓存机制：跨 Agent 上下文缓存和本地 TTL 缓存。
    """

    # 工具名称：在 CrewAI Agent 的任务描述中引用此工具时使用
    name: str = "PNEC Database Query"
    # 工具描述：帮助 LLM 理解何时以及如何使用此工具
    # 这是一个关键的提示信息，LLM 根据描述决定是否调用此工具
    description: str = (
        "查询预测无效应浓度（PNEC）数据，用于环境风险评估。"
        "通过 CAS 号或化合物名称查询 PNEC 值。"
        "当需要评估化学品环境安全性时使用此工具。"
        "注意：仅提供真实的参考数据（如内置金属毒性文献值）；"
        "对无真实数据的化合物会明确返回 data_available=false，不会给出估算值。"
    )
    # args_schema: 指定工具的输入参数结构
    # CrewAI 使用此 schema 来验证输入并在调用 _run 前进行类型转换
    args_schema: type[BaseModel] = PNECToolInput

    def __init__(self):
        """初始化 CrewAI PNEC 工具。

        调用父类 BaseTool 的初始化方法，
        同时设置本地内存缓存和 TTL（生存时间）配置。
        """
        super().__init__()
        # _cache: 本地内存缓存字典
        # 键为 (查询类型, 查询内容) 元组，值为 (时间戳, 结果) 元组
        self._cache = {}
        # _ttl_seconds: 缓存的生存时间（秒）
        # 600 秒（10分钟）后缓存数据自动失效，确保数据不会过时
        self._ttl_seconds = 600

    def _run(self, query: str, query_type: str = "name") -> str:
        """
        Execute PNEC data query.
        执行 PNEC 数据查询。CrewAI 框架会自动调用此方法。

        缓存策略（从快到慢）：
        1. 先查跨 Agent 上下文缓存（ContextStore）：跨多个 Agent 共享数据
        2. 再查本地 TTL 缓存（_cache）：避免重复请求 PubChem API
        3. 最后才真正执行查询

        Args:
            query: 查询内容（CAS 号或化合物名称）
            query_type: 查询类型（"name" 或 "cas"）

        Returns:
            JSON 格式的查询结果字符串
            CrewAI 工具必须返回字符串，所以这里将字典序列化为 JSON
        """
        try:
            # 构造缓存键：使用查询类型和查询内容的组合
            # 例如 ("cas", "7440-02-0") 或 ("name", "Nickel")
            key = (query_type.lower(), query)
            # 获取当前时间戳，用于判断本地缓存是否过期
            import time as _t
            now = _t.time()

            # 第一层缓存：尝试从跨 Agent 上下文存储获取
            # ContextStore 可以在不同 Agent 之间共享数据，避免重复查询
            if query_type.lower() == "cas":
                cached_ctx = ContextStore.get(f"pnec:cas:{query}")
                if cached_ctx is not None:
                    # 缓存命中，直接返回（不重新请求 PubChem API）
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)
            else:
                cached_ctx = ContextStore.get(f"pnec:name:{query}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # 第二层缓存：尝试从本地 TTL 缓存获取
            # 这里使用 time-based TTL 策略，超过 _ttl_seconds 的缓存被认为失效
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # 缓存未命中：获取底层工具实例并执行实际查询
            tool = get_pnec_tool()

            # 根据查询类型调用对应的底层方法
            # 仅将成功结果写入跨 Agent 上下文缓存（无 TTL），错误结果不缓存，
            # 避免一次失败的查询被后续所有 Agent 永久复用
            if query_type.lower() == "cas":
                result = tool.get_pnec_by_cas(query)
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pnec:cas:{query}", result)
            else:
                result = tool.get_pnec_by_name(query)
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pnec:name:{query}", result)

            # 同时写入本地 TTL 缓存（时间戳 + 结果元组）
            self._cache[key] = (now, result)
            # 将结果序列化为 JSON 字符串返回
            # ensure_ascii=False 保留中文字符，indent=2 使输出可读
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            # 异常处理：返回包含错误信息的 JSON，避免工具崩溃导致 Agent 失败
            return json.dumps({"error": f"查询错误: {str(e)}"}, ensure_ascii=False)
