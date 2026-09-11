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

# 评估筛选专家 B 类
# 继承自 BaseAgent，专门负责从环境健康与安全（EHS）角度对材料提案进行综合评估
class AssessmentScreeningAgentB(BaseAgent):
    """评估筛选专家 B agent
    负责对材料提案的各个方面进行全面评估，聚焦于环境影响与人体健康风险评估
    """

    def __init__(self, llm):
        # 延迟导入 Config 配置类，避免循环导入问题，同时保证配置在需要时才加载
        from src.config.config import Config
        # 调用基类 BaseAgent 的构造函数，传入 agent 的所有核心参数
        super().__init__(
            llm=llm,
            # 角色标识：评估筛选专家 B，在多 agent 协作中用于区分不同的专家身份
            role="Assessment_Screening_agent_B",
            # 目标描述：告诉 agent 它的核心任务是全面评估材料提案的各个方面
            goal="Comprehensively evaluate various aspects of material proposals",
            # 指定该 agent 使用的提示词模板文件（Markdown 格式），运行时会被加载并填充参数
            prompt_file="assessment_screening_agent_b_prompt.md",
            # 从配置文件读取专家 B 的专用温度参数，控制 LLM 输出的随机性
            temperature=Config.EXPERT_B_TEMPERATURE,
            # 最大迭代次数设为 2：
            # 遵循"少即是多"原则，从原来的 15 次大幅缩减，专注于核心评估逻辑
            max_iter=2,
            # 提示词参数：将 EXPERT_ID 替换为 "B"，使提示词模板中的占位符被正确填充
            prompt_params={"EXPERT_ID": "B"}
        )

    def create_agent(self):
        # LLM 的选择（EAS / 带温度标准 LLM / 默认 LLM）已统一收敛到
        # BaseAgent._resolve_llm()，此处不再重复创建

        # 调用基类的 create_agent 方法，完成 agent 实例的基础创建和配置
        agent = super().create_agent()

        # 使用统一的 ASA（Assessment Screening Agent）评估工具集
        # ASA 工具集由 A/B/C 三个专家共享，提供化学性质查询、环境评估等能力
        try:
            # 动态导入工具开关检查函数，判断是否启用外部工具
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # 工具启用时：创建统一的评估工具集，包含化学品数据库查询等功能
                agent.tools = ToolFactory.create_unified_assessment_tools()
            else:
                # 工具未启用时：赋予空列表，agent 仅依靠自身知识进行推理
                agent.tools = []
        except Exception:
            # 如果 tools_enabled 检查失败（例如配置缺失），默认启用工具集
            # 这是一种"宁可多用工具也不错失信息"的容错策略
            agent.tools = ToolFactory.create_unified_assessment_tools()

        # 返回配置完成的 agent 实例，供上层调用者使用
        return agent
