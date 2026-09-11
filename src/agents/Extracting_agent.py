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


class ExtractingAgent(BaseAgent):
    """文献处理智能体

    一个负责处理和分析科学文献的智能体，
    从文献中提取与材料评估相关的信息。

    在多智能体协作流程中，该智能体接收用户输入的材料需求，
    检索并分析相关技术文献，为后续的合成设计和操作建议提供背景知识支撑。
    """

    def __init__(self, llm):
        """初始化文献提取智能体。

        设置智能体的角色定位、目标任务和提示词模板。
        注意：该智能体的输出用于支撑下游智能体的决策，
        因此温度参数通过 Config 统一管理，确保输出的一致性和可靠性。

        Args:
            llm: 语言模型实例，作为智能体的推理引擎
        """
        # 延迟导入 Config，避免循环依赖问题
        # Config 中包含了各个智能体专用的温度等参数配置
        from src.config.config import Config
        super().__init__(
            llm=llm,
            role="Extracting_agent",  # 角色名：文献处理专家，用于日志和标识
            goal="Process and analyze relevant technical literature to provide background information for material evaluation",  # 目标描述：指导 LLM 提取和整理文献中的关键信息
            prompt_file="extracting_agent_prompt.md",  # 提示词模板文件：定义该角色的文献分析方法和输出格式
            temperature=Config.LITERATURE_PROCESSOR_TEMPERATURE  # 温度参数：从配置文件读取，控制 LLM 输出的随机性
            # 注意：该智能体未设置 max_iter 参数，使用 BaseAgent 的默认值
            # 这意味着文献提取任务可能需要进行更多轮迭代以确保信息完整性
        )

    def create_agent(self):
        """创建并配置智能体实例，挂载文献提取工具。

        该方法的执行流程：
        1. 优先尝试创建 EAS（弹性算法服务）LLM 实例，以获得更好的性能
        2. 如果 EAS 不可用，则使用初始化时传入的默认 LLM 作为降级方案
        3. 直接加载文献提取工具集（不需要条件判断，因为文献处理工具通常是必需的）

        与其他智能体的区别：
        - 不检查 tools_enabled 开关，总是加载工具（因为文献检索是核心功能，不可缺失）
        - 不设置 max_iter（使用默认值，允许更多迭代以深入分析文献）

        Returns:
            配置完成的智能体实例，已挂载文献提取工具集
        """
        # ---- 第一阶段：LLM 选择已统一收敛到 BaseAgent._resolve_llm() ----
        # EAS / 带温度标准 LLM / 默认 LLM 的决策在父类中完成，此处不再重复创建

        # ---- 第二阶段：调用父类创建基础智能体 ----
        # 父类的 create_agent 方法负责加载提示词、设置 LangChain agent 框架
        agent = super().create_agent()

        # ---- 第三阶段：挂载文献提取工具集 ----
        # 使用标准化的文献提取工具集，帮助智能体检索和分析科学文献
        # 注意：与其他两个智能体不同，这里不检查 tools_enabled 开关
        # 原因是文献检索工具是该智能体的核心能力，必须始终可用
        agent.tools = ToolFactory.create_literature_extraction_tools()
        return agent
