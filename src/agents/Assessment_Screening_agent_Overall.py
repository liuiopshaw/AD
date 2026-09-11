# 导入 logging 模块，用于记录运行日志，便于调试和追踪 agent 行为
import logging
# 从当前包（agents）的 base_agent 模块导入 BaseAgent 基类
# 使用相对导入（.），表明 base_agent 与当前文件在同一目录下
from .base_agent import BaseAgent
# 从 tools 模块导入 ToolFactory，用于统一创建和管理 agent 所使用的工具集
from src.tools import ToolFactory

# 配置日志的基本参数：设置日志级别为 WARNING，过滤掉 INFO/DEBUG 级别的冗余信息
# 这样只输出警告及更高级别的日志，避免控制台输出过多不必要的内容
logging.basicConfig(level=logging.WARNING)
# 获取当前模块的 logger 实例，后续所有日志输出都通过此 logger 进行
logger = logging.getLogger(__name__)

# 综合评估筛选专家类（最终汇总专家）
# 继承自 BaseAgent，不直接评估材料，而是汇总三个专家（A/B/C）的评估结果
# 进行加权计算和一致性分析，生成最终的综合评估报告
class AssessmentScreeningAgentOverall(BaseAgent):
    """综合评估筛选专家 agent
    负责汇总各专家的评估结果，进行加权计算，并生成最终的材料评估报告和改进建议
    """

    def __init__(self, llm):
        # 延迟导入 Config 配置类，避免在模块加载阶段出现循环导入问题
        from src.config.config import Config
        # 调用基类 BaseAgent 的构造函数，传入 agent 的所有核心参数
        super().__init__(
            llm=llm,
            # 角色标识：综合评估筛选专家（最终验证专家）
            # 这是多 agent 协作流程中的最后一个环节，负责整合所有专家的意见
            role="Assessment_Screening_agent_Overall",
            # 目标描述：明确告诉 agent 它的任务是汇总各专家结果、加权计算并生成最终报告
            # 同时还需要提供改进建议，使输出不仅包含评估结论，还包含可操作的指导
            goal="Synthesize evaluation results from various experts, perform weighted calculations, and generate final material evaluation report, while providing improvement suggestions",
            # 指定该 agent 使用的提示词模板文件（Markdown 格式）
            prompt_file="assessment_screening_agent_overall_prompt.md",
            # 从配置文件读取最终验证专家的专用温度参数，控制 LLM 输出的随机性
            temperature=Config.FINAL_VALIDATOR_TEMPERATURE,
            # 最大迭代次数设为 1：
            # 遵循"少即是多"原则，从原来的 8 次缩减为 1 次
            # 因为该 agent 只负责汇总已有结果，不需要迭代推理
            max_iter=1
        )

    def create_agent(self):
        # LLM 的选择（EAS / 带温度标准 LLM / 默认 LLM）已统一收敛到
        # BaseAgent._resolve_llm()，此处不再重复创建

        # 调用基类的 create_agent 方法，完成 agent 实例的基础创建和配置
        agent = super().create_agent()

        # ASA 最终验证专家特殊处理：
        # 该 agent 不需要任何外部工具，它的唯一职责是汇总 ASA A/B/C 三个专家的输出结果
        # 进行加权计算、一致性分析和最终报告生成
        # 因此将工具列表设置为空，避免不必要的工具调用干扰汇总逻辑
        agent.tools = []

        # 增强提示词，明确说明其聚合角色：
        # 在已有的 backstory（背景故事）之后追加一段说明，让 LLM 清楚知道：
        # 1. 它的核心职责是收集 AssessmentScreeningAgentA、B、C 的评估结果
        # 2. 需要执行加权计算和一致性分析
        # 3. 不需要重新评估材料本身，只负责综合已有意见
        # 这样做可以防止 LLM 重复评估，避免信息冗余和资源浪费
        agent.backstory += "\n\nYour core responsibility is to collect evaluation results from three experts (AssessmentScreeningAgentA, B, C), perform weighted calculations and consistency analysis, and generate the final report. You do not need to re-evaluate the material itself, but synthesize existing opinions."

        # 返回配置完成的综合评估 agent 实例，供上层调用者使用
        return agent
