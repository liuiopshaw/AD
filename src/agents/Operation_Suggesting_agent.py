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


# 操作建议专家智能体类
# 该智能体为材料的合成、生产和应用提供详细的操作指导
class OperationSuggestingAgent(BaseAgent):
    def __init__(self, llm):
        """初始化操作建议智能体。

        设置智能体的角色定位、目标任务、提示词模板和行为参数。
        该智能体专注于将上游的合成方案转化为具体可执行的操作步骤。

        Args:
            llm: 语言模型实例，作为智能体的推理引擎
        """
        # 延迟导入 Config，避免循环依赖问题
        # Config 中包含了各个智能体专用的温度等参数配置
        from src.config.config import Config
        super().__init__(
            llm,
            "Operation_Suggesting_agent",  # 角色名：操作建议专家，用于日志和标识
            "Provide detailed operational guidance for material synthesis, production and application",  # 目标描述：指导 LLM 生成详细的操作规程
            "operation_suggesting_agent_prompt.md",  # 提示词模板文件：包含该角色的详细系统提示，定义其专业领域和行为规范
            temperature=Config.OPERATION_SUGGESTING_TEMPERATURE,  # 温度参数：从配置文件读取，控制 LLM 输出的随机性
            max_iter=2  # 最大迭代次数：设置为 2（原始值为 8），遵循 "少即是多" 原则
                        # 减少迭代次数意味着：复用上游合成路线，专注于操作细节的细化，避免过度重复推理
        )

    def create_agent(self):
        """创建并配置操作建议智能体，挂载所需工具。

        该方法的执行流程：
        1. 优先尝试创建 EAS（弹性算法服务）LLM 实例，以获得更好的性能
        2. 如果 EAS 不可用，则使用初始化时传入的默认 LLM 作为降级方案
        3. 根据端点是否支持工具调用来决定是否加载操作指导工具集

        Returns:
            配置完成的智能体实例，已挂载化学数据库查询工具
        """
        # ---- 第一阶段：LLM 选择已统一收敛到 BaseAgent._resolve_llm() ----
        # EAS / 带温度标准 LLM / 默认 LLM 的决策在父类中完成，此处不再重复创建

        # ---- 第二阶段：调用父类创建基础智能体 ----
        # 父类的 create_agent 方法负责加载提示词、设置 LangChain agent 框架
        agent = super().create_agent()

        # ---- 第三阶段：挂载操作指导工具集 ----
        # 该工具集侧重于材料参数查询和试剂信息检索，
        # 帮助智能体生成更精确的操作建议（如温度、压力、试剂用量等）
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # 端点支持工具调用：加载操作指导工具集
                agent.tools = ToolFactory.create_operation_guidance_tools()
            else:
                # 端点不支持工具调用：清空工具列表，避免运行时错误
                agent.tools = []
        except Exception:
            # 如果 tools_enabled 导入或调用失败，默认启用工具
            # 这是一个保守的容错策略：宁可多加载工具，也不让智能体缺少功能
            agent.tools = ToolFactory.create_operation_guidance_tools()
        return agent
