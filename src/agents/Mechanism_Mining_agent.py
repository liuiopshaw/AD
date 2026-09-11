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

# 机理挖掘专家类
# 继承自 BaseAgent，专门负责挖掘和分析污染物降解的反应机理与动力学特性
class MechanismMiningAgent(BaseAgent):
    """机理挖掘专家 agent
    负责挖掘污染物降解的反应机理和动力学特性，
    通过分析材料结构与化学性质，揭示降解路径和关键中间产物。
    """

    def __init__(self, llm):
        # 延迟导入 Config 配置类，避免在模块加载阶段出现循环导入问题
        from src.config.config import Config
        # 调用基类 BaseAgent 的构造函数，传入 agent 的所有核心参数
        super().__init__(
            llm=llm,
            # 角色标识：机理挖掘专家，在多 agent 协作中负责化学机理分析环节
            role="Mechanism_Mining_agent",
            # 目标描述：明确告诉 agent 它的核心任务
            # 聚焦于挖掘污染物降解过程中的反应机理和动力学特征
            goal="Mine reaction mechanisms and kinetic characteristics of pollutant degradation",
            # 指定该 agent 使用的提示词模板文件（Markdown 格式），运行时会被加载并填充参数
            prompt_file="mechanism_mining_agent_prompt.md",
            # 从配置文件读取机理专家的专用温度参数
            # 通常设为较低值，以保证机理分析的严谨性和一致性
            temperature=Config.MECHANISM_EXPERT_TEMPERATURE,
            # 最大迭代次数设为 2：
            # 遵循"少即是多"原则，从原来的 8 次缩减为 2 次
            # 该 agent 主要复用上游（如材料表征、评估筛选）的分析结果
            # 只需在此基础上进行机理分析，不需要过多的迭代
            max_iter=2
        )

    def create_agent(self):
        # LLM 的选择（EAS / 带温度标准 LLM / 默认 LLM）已统一收敛到
        # BaseAgent._resolve_llm()，此处不再重复创建

        # 调用基类的 create_agent 方法，完成 agent 实例的基础创建和配置
        # 此方法会加载提示词、设置角色信息、初始化 CrewAI agent 等
        agent = super().create_agent()

        # 使用机理分析专用工具集
        # 与评估筛选专家不同，机理挖掘专家需要的工具侧重于化学结构分析和反应路径计算
        try:
            # 动态导入工具开关检查函数，判断当前环境是否配置为启用外部工具
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # 工具启用时：创建机理分析专用工具集
                # 这些工具通常包括反应路径分析、过渡态计算、结构-活性关系查询等
                agent.tools = ToolFactory.create_mechanism_analysis_tools()
            else:
                # 工具未启用时：赋予空列表
                # agent 将仅依靠自身训练数据中的化学知识进行机理推断
                agent.tools = []
        except Exception:
            # 如果 tools_enabled 检查本身失败（例如配置模块异常），默认启用工具集
            # 这是一种"宁可多用工具也不错失关键信息"的容错策略
            agent.tools = ToolFactory.create_mechanism_analysis_tools()

        # 返回配置完成的机理挖掘 agent 实例，供上层调用者使用
        return agent
