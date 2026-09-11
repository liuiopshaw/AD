# =============================================================================
# 日志模块：记录程序运行信息，便于调试和追踪问题
# =============================================================================
import logging
from src.agents.base_agent import BaseAgent
from src.tools import ToolFactory

# 配置日志格式和级别：WARNING 及以上的日志才会输出，避免过多的 INFO/DEBUG 信息干扰
# 注意：basicConfig 只在首次调用时生效，多次调用不影响已有配置
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)  # 获取当前模块的日志记录器，便于定位日志来源


class SynthesisGuidingAgent(BaseAgent):
    """合成引导智能体

    该智能体专门负责设计材料的合成方法和工艺流程。
    继承自 BaseAgent，通过化学数据库工具扩展了功能，
    能够查询物质特性、合成路线等专业数据。

    在多智能体协作流程中，该智能体接收上游的材料设计结果，
    输出可行的合成方案供下游操作建议智能体使用。
    """

    def __init__(self, llm):
        """初始化合成引导智能体。

        设置智能体的角色定位、目标任务、提示词模板和行为参数。
        使用 Config 中预定义的温度参数来控制输出的创造性和一致性。

        Args:
            llm: 语言模型实例，作为智能体的推理引擎
        """
        # 延迟导入 Config，避免循环依赖问题
        # Config 中包含了各个智能体专用的温度等参数配置
        from src.config.config import Config
        super().__init__(
            llm,
            "Synthesis_Guiding_agent",  # 角色名：合成方法专家，用于日志和标识
            "Design material synthesis methods and process flows",  # 目标描述：指导 LLM 的任务方向
            "synthesis_guiding_agent_prompt.md",  # 提示词模板文件：包含该角色的详细系统提示
            temperature=Config.SYNTHESIS_EXPERT_TEMPERATURE,  # 温度参数：从配置文件读取，控制 LLM 输出的随机性
            max_iter=2  # 最大迭代次数：设置为 2（原始值为 8），遵循 "少即是多" 原则
                        # 减少迭代次数意味着：复用上游设计结果，专注于合成路线规划，避免过度重复推理
        )

    def create_agent(self):
        """创建并配置智能体实例。

        该方法的执行流程：
        1. 优先尝试创建 EAS（弹性算法服务）LLM 实例，因为 EAS 提供更高的性能和稳定性
        2. 如果 EAS 不可用，则使用初始化时传入的默认 LLM，保证系统在降级情况下仍可运行
        3. 根据端点是否支持工具调用来决定是否加载化学数据库查询工具

        Returns:
            配置完成的智能体实例，已挂载所需工具
        """
        # ---- 第一阶段：LLM 选择已统一收敛到 BaseAgent._resolve_llm() ----
        # EAS / 带温度标准 LLM / 默认 LLM 的决策在父类中完成，此处不再重复创建

        # ---- 第二阶段：调用父类创建基础智能体 ----
        # 父类的 create_agent 方法负责加载提示词、设置 LangChain agent 框架
        agent = super().create_agent()

        # ---- 第三阶段：挂载化学数据库查询工具 ----
        # 工具集提供材料搜索功能（如物质性质查询、合成路线检索等）
        # 注意：DashScope 兼容端点可能不支持原生工具调用（function calling）
        # 因此需要先检查 tools_enabled 的开关状态
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # 端点支持工具调用：加载材料搜索工具集
                agent.tools = ToolFactory.create_material_search_tools()
            else:
                # 端点不支持工具调用：清空工具列表，避免运行时错误
                agent.tools = []
        except Exception:
            # 如果 tools_enabled 导入或调用失败（例如配置缺失），默认启用工具
            # 这是一个保守的容错策略：宁可多加载工具，也不让智能体缺少功能
            agent.tools = ToolFactory.create_material_search_tools()
        return agent
