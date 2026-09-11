# 导入 logging 模块，用于记录代理运行时的日志信息
import logging
# 导入 BaseAgent 基类，AssessmentScreeningAgentA 继承自它，复用通用代理创建逻辑
from src.agents.base_agent import BaseAgent
# 导入 ToolFactory 工具工厂类，用于创建评估筛选所需的工具集
from src.tools import ToolFactory

# 配置 logging 模块的全局日志级别为 WARNING，
# 只输出警告和错误级别的日志，避免 INFO/DEBUG 信息刷屏
logging.basicConfig(level=logging.WARNING)
# 获取当前模块的 logger 实例，日志输出会带上模块名，便于追踪来源
logger = logging.getLogger(__name__)

# 评估筛选专家 A 类
# 专家 A 是多专家评估体系中的一个独立评估者，
# 与专家 B、专家 C 并行工作，从不同维度对材料方案进行评估
class AssessmentScreeningAgentA(BaseAgent):
    """评估筛选代理 A（Assessment Screening Agent A）
       负责从特定角度对材料设计方案进行全面评估：
       - 与其他评估专家（B、C）并行工作
       - 使用统一的评估工具集
       - 通过 prompt_params 中的 EXPERT_ID 区分不同专家的评估视角"""

    def __init__(self, llm):
        """初始化评估筛选代理 A

        Args:
            llm: 语言模型实例，由外部传入（通常来自 Crew 配置或主程序）
        """
        # 延迟导入 Config 类，避免模块加载时的循环导入问题
        from src.config.config import Config
        # 调用父类 BaseAgent 的构造函数，传入评估代理 A 的专有配置
        super().__init__(
            llm,  # 语言模型实例
            "Assessment_Screening_agent_A",  # 代理角色名：评估专家 A
            "Comprehensively evaluate various aspects of material proposals",
            # 指定评估代理 A 专用的提示词模板文件
            "assessment_screening_agent_a_prompt.md",
            # 从 Config 读取专家 A 专用的温度参数
            # 较低的评估温度有助于获得更一致、更理性的评估结果
            temperature=Config.EXPERT_A_TEMPERATURE,
            # max_iter=2：性能优化，从原始的 15 次迭代大幅缩减到 2 次
            # 设计原则：Less is More — 聚焦核心评估逻辑，避免不必要的重复推理
            max_iter=2,
            # prompt_params 参数化替换：
            # 将提示词模板中的 {EXPERT_ID} 占位符替换为 "A"
            # 这样多个专家（A/B/C）可以共享同一套提示词模板，
            # 仅通过不同的 EXPERT_ID 来区分各自的评估焦点
            prompt_params={"EXPERT_ID": "A"}
        )

    def create_agent(self):
        """创建并返回配置好的评估专家 A 的 Agent 实例

        此方法覆盖父类的 create_agent，添加了：
        1. EAS（Elastic Algorithm Service）LLM 的创建尝试
        2. 统一评估工具集的附加

        Returns:
            Agent: 配置完成的评估专家 A 的 Agent 实例
        """
        # LLM 的选择（EAS / 带温度标准 LLM / 默认 LLM）已统一收敛到
        # BaseAgent._resolve_llm()，此处不再重复创建

        # 调用父类 BaseAgent 的 create_agent() 创建基础 Agent 实例
        # 父类方法会处理 backstory 加载、参数替换（EXPERT_ID=A）、
        # 以及 Memory-first 指导文本的追加
        agent = super().create_agent()
        # 附加工具集：使用统一的 ASA 评估工具集（专家 A/B/C 共享）
        # 统一工具集确保了不同专家的工具能力一致，评估结果的可比性更强
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # 工具启用时：创建统一评估工具集
                agent.tools = ToolFactory.create_unified_assessment_tools()
            else:
                # 工具禁用时：设置为空列表
                # 代理将完全依赖 LLM 知识和 backstory 中的评估标准进行判断
                agent.tools = []
        except Exception:
            # 异常时默认启用工具（保守策略，优先保证功能完整）
            agent.tools = ToolFactory.create_unified_assessment_tools()

        return agent
