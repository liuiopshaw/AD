# 导入 logging 模块，用于记录程序运行时的日志信息
import logging
# 从 crewai 框架导入 Agent 类，作为所有自定义代理的基础类
from crewai import Agent
# 导入自定义的 prompt 加载工具函数，用于从外部 .md 文件读取提示词模板
from src.utils.prompt_loader import load_prompt

# 配置 logging 模块的全局日志级别为 WARNING，
# 这样只有 WARNING 及以上级别的日志才会输出，避免 DEBUG/INFO 日志刷屏
logging.basicConfig(level=logging.WARNING)
# 获取当前模块的 logger 实例，通过 __name__ 确保日志带模块名标识，便于追踪来源
logger = logging.getLogger(__name__)

# 定义全局的 Memory-first 使用指导文本，用于在代理的 backstory 末尾追加，
# 提示 LLM 优先从上下文/内存中查找已有信息，减少重复的外部工具调用，降低 API 成本
MEMORY_GUIDANCE_EN = """

## Tool Usage Optimization Strategy ##
1. **Memory First**: Check context or memory for existing information before calling external tools
2. **Avoid Duplicate Queries**: Reuse results if material/chemical info was queried by previous tasks
3. **Minimize Tool Calls**: Only query necessary information, avoid overusing tools
4. **Result Reuse**: Pass organized query results to downstream tasks for reuse
"""


class BaseAgent:
    """ 所有自定义代理的基类，提供通用的代理创建功能，
        封装了 LLM 配置、提示词加载、温度参数、最大迭代次数等通用逻辑"""

    # 默认最大迭代次数为 10，防止代理陷入无限循环或过度的工具调用，
    # 当子类未显式指定 max_iter 时使用此默认值
    DEFAULT_MAX_ITER = 10

    def __init__(self, llm, role, goal, prompt_file, temperature=None, max_iter=None, prompt_params=None):
        # 主 LLM 实例，由外部传入（通常来自 Crew 配置），所有代理共享同一个基础 LLM
        self.llm = llm
        # 代理的角色名称（如 "Material_Design_Expert"），用于 CrewAI 的 role 字段
        self.role = role
        # 代理的目标描述，用于 CrewAI 的 goal 字段，指导 LLM 的行为方向
        self.goal = goal
        # 提示词模板文件路径，指向 prompts 目录下的 .md 文件
        self.prompt_file = prompt_file
        # LLM 温度参数（控制输出随机性），None 表示使用默认温度
        # 子类可以通过此参数为不同的代理设置不同的创造力水平
        self.temperature = temperature
        # 最大迭代次数，优先使用传入的 max_iter，未传入时回退到 DEFAULT_MAX_ITER
        self.max_iter = max_iter or self.DEFAULT_MAX_ITER
        # 提示词参数化替换字典，用于在 backstory 中替换 {key} 占位符
        # 例如 {"EXPERT_ID": "A"} 可将提示词中的 {EXPERT_ID} 替换为 "A"
        self.prompt_params = prompt_params or {}

    def _resolve_llm(self):
        """解析本代理应使用的 LLM 实例，创建逻辑只发生一次。

        优先级（与 Creative_Designing_agent 的模式一致，未配置 EAS 时安静降级）：
        1. EAS 三项配置（EAS_ENDPOINT/EAS_TOKEN/EAS_MODEL_NAME）齐全时，创建 EAS LLM
           （温度参数 self.temperature 正确透传）
        2. 否则若指定了温度参数，创建带该温度的标准 LLM
        3. 否则复用构造函数传入的默认 self.llm

        任何一步失败仅记录 DEBUG 日志并回退到默认 LLM，保证代理始终可用。

        Returns:
            解析后的 LLM 实例
        """
        try:
            # 延迟导入 Config 类，避免循环导入问题
            from src.config.config import Config
            # 检查是否配置了 EAS（Elastic Algorithm Service）端点：
            # 三项 EAS 配置都存在时才使用 EAS 模式创建专用的 LLM 实例
            if Config.EAS_ENDPOINT and Config.EAS_TOKEN and Config.EAS_MODEL_NAME:
                from src.utils.llm_config import create_eas_llm
                agent_llm = create_eas_llm(temperature=self.temperature)
                logger.info("Successfully created EAS LLM instance")
                return agent_llm
        except Exception as e:
            # EAS 创建失败（如配置不完整、网络不通）时仅记录 DEBUG 日志，
            # 继续回退到标准/默认 LLM，保证程序不会因为 LLM 配置问题而崩溃
            logger.debug(f"EAS LLM not available, falling back: {e}")

        # 标准模式：如果指定了温度参数，则创建一个带指定温度的标准 LLM，
        # 否则直接复用传入的默认 self.llm，避免不必要的重复创建
        if self.temperature is not None:
            try:
                from src.utils.llm_config import create_llm
                return create_llm(temperature=self.temperature)
            except Exception as e:
                logger.debug(f"Failed to create custom LLM with temperature {self.temperature}: {e}")
        return self.llm

    def create_agent(self):
        """创建并返回一个配置好的 CrewAI Agent 实例

        此方法负责：
        1. 通过 _resolve_llm() 决定使用哪种 LLM（EAS 模式或标准模式，仅创建一次）
        2. 加载提示词模板并完成参数化替换
        3. 追加 Memory-first 使用指导
        4. 组装最终的 Agent 对象

        Returns:
            Agent: 配置完成的 CrewAI Agent 实例
        """
        # 解析本代理使用的 LLM（EAS / 带温度标准 LLM / 默认传入 LLM）
        agent_llm = self._resolve_llm()

        # 从 .md 文件加载 backstory（提示词模板），返回完整的文本内容
        backstory = load_prompt(self.prompt_file)

        # 参数化替换：如果 self.prompt_params 不为空，遍历所有键值对，
        # 将 backstory 中的 {key} 占位符替换为对应的 value 值
        # 例如 {EXPERT_ID} -> "A"，实现同一模板为不同专家生成不同提示词
        if self.prompt_params:
            for key, value in self.prompt_params.items():
                backstory = backstory.replace(f"{{{key}}}", value)

        # 在 backstory 末尾追加 Memory-first 使用指导文本，
        # 提示每个代理优先从上下文/内存获取已有信息，减少不必要的工具调用
        backstory += MEMORY_GUIDANCE_EN

        # 创建并返回 CrewAI Agent 实例，传入所有配置参数：
        # - role: 代理角色名
        # - goal: 代理目标描述
        # - backstory: 由提示词模板 + 参数替换 + Memory 指导组成的完整提示
        # - verbose=False: 关闭详细输出，避免控制台信息过多
        # - allow_delegation=False: 禁止任务委托，基类代理负责直接执行任务
        # - llm: 配置好的 LLM 实例（可能是 EAS 或标准 LLM）
        # - max_iter: 最大迭代次数限制，防止过度工具调用
        return Agent(
            role=self.role,
            goal=self.goal,
            backstory=backstory,
            verbose=False,
            allow_delegation=False,
            llm=agent_llm,
            max_iter=self.max_iter
        )
