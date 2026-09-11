# 导入 logging 模块，用于记录运行日志，便于调试和追踪 agent 行为
import logging
# 从 base_agent 模块导入 BaseAgent 基类，所有专家 agent 均继承自此基类
from src.agents.base_agent import BaseAgent
# 从 tools 模块导入 ToolFactory，用于统一创建和管理 agent 所使用的工具集
from src.tools import ToolFactory

# 配置日志的基本参数：设置日志级别为 WARNING，过滤掉 INFO/DEBUG 级别的冗余信息
# 这样只输出警告及更高级别的日志，避免控制台输出过多不必要的内容
logging.basicConfig(level=logging.WARNING)
# 获取当前模块的 logger 实例，后续所有日志输出都通过此 logger 进行
logger = logging.getLogger(__name__)

# 评估筛选专家 C 类
# 继承自 BaseAgent，专门负责从技术可行性与工程实现角度对材料提案进行综合评估
class AssessmentScreeningAgentC(BaseAgent):
    """评估筛选专家 C Agent

    一个专门的 agent，负责从多个维度（包括环境影响、安全性和可行性）
    对材料提案进行综合评估。
    """

    def __init__(self, llm):
        """初始化评估筛选专家 C agent。

        Args:
            llm: 该 agent 将使用的大语言模型实例，由上层调用者注入

        """
        # 延迟导入 Config 配置类，避免在模块加载阶段出现循环导入问题
        from src.config.config import Config
        # 调用基类 BaseAgent 的构造函数，传入 agent 的所有核心参数
        # 使用位置参数方式传递，代码更简洁紧凑
        super().__init__(llm,
                         # 角色标识：评估筛选专家 C，在多 agent 协作中用于区分不同的专家身份
                         "Assessment_Screening_agent_C",
                         # 目标描述：告诉 agent 它的核心任务是全面评估材料提案的各个方面
                         "Comprehensively evaluate various aspects of material proposals",
                         # 指定该 agent 使用的提示词模板文件（Markdown 格式），运行时会被加载并填充参数
                         "assessment_screening_agent_c_prompt.md",
                         # 从配置文件读取专家 C 的专用温度参数，控制 LLM 输出的随机性
                         temperature=Config.EXPERT_C_TEMPERATURE,
                         # 最大迭代次数设为 2：
                         # 遵循"少即是多"原则，从原来的 15 次大幅缩减，专注于核心评估逻辑
                         max_iter=2,
                         # 提示词参数：将 EXPERT_ID 替换为 "C"，使提示词模板中的占位符被正确填充
                         prompt_params={"EXPERT_ID": "C"})

    def create_agent(self):
        """创建并配置评估筛选 agent。

        此方法首先尝试创建 EAS（Expert Agent System）LLM 实例，
        如果 EAS 创建失败则回退到构造函数传入的 LLM。
        然后为 agent 添加化学数据库查询工具，以便进行全面的材料评估。

        Returns:
            配置完成的 agent 实例，包含材料评估所需的必要工具
        """
        # LLM 的选择（EAS / 带温度标准 LLM / 默认 LLM）已统一收敛到
        # BaseAgent._resolve_llm()，此处不再重复创建

        # 调用基类的 create_agent 方法，完成 agent 实例的基础创建和配置
        # 此方法会加载提示词、设置角色信息、初始化 CrewAI agent 等
        agent = super().create_agent()

        # 使用统一的 ASA（Assessment Screening Agent）评估工具集
        # 三个评估专家 A/B/C 共享同一套工具，确保评估标准的一致性
        try:
            # 动态导入工具开关检查函数，判断当前环境是否配置为启用外部工具
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # 工具启用时：创建统一的评估工具集
                # 这些工具通常包括化学品性质查询、毒性数据库检索等功能
                agent.tools = ToolFactory.create_unified_assessment_tools()
            else:
                # 工具未启用时：赋予空列表
                # agent 将仅依靠自身训练数据中的知识进行推理，不调用任何外部 API
                agent.tools = []
        except Exception:
            # 如果 tools_enabled 检查本身失败（例如配置模块异常），默认启用工具集
            # 这是一种"宁可多用工具也不错失关键信息"的容错策略
            agent.tools = ToolFactory.create_unified_assessment_tools()

        # 返回配置完成的 agent 实例，供上层调用者（如 Crew 协调器）使用
        return agent
