# 导入 logging 模块，用于记录代理运行时的日志信息
import logging
# 导入 json 模块，用于解析 LLM 返回的 JSON 格式意图分析结果
import json
# 导入 re 模块（正则表达式），用于清除 LLM 响应中可能存在的 Markdown 代码块标记
import re
# 导入类型提示工具，增强代码可读性和 IDE 支持
from typing import List, Union, Dict, Any
# 从 crewai 框架导入 Agent 类
from crewai import Agent
# 导入自定义的 prompt 加载工具函数，用于从外部 .md 文件读取提示词
from src.utils.prompt_loader import load_prompt
# 导入 BaseAgent 基类，TaskOrganizingAgent 继承自它，复用通用的代理创建逻辑
from src.agents.base_agent import BaseAgent

# 配置 logging 模块的全局日志级别为 WARNING，
# 避免 INFO/DEBUG 级别的日志刷屏，保持输出清爽
logging.basicConfig(level=logging.WARNING)
# 获取当前模块的 logger 实例，日志输出会带上模块名称，便于定位问题来源
logger = logging.getLogger(__name__)

# 任务组织代理类，负责整个系统的"大脑"功能：
# 1. 分析用户意图（intent recognition）
# 2. 将意图映射为具体的任务类型
# 3. 管理代理注册表（agent registry）
# 4. 将任务委派给合适的专家代理
class TaskOrganizingAgent(BaseAgent):
    """任务组织代理 - 负责意图识别和代理调度
       是整个多代理系统的协调中心，接收用户需求，分析意图，
       将任务分配给正确的专家代理执行"""

    # 任务类型到代理类名的映射表（类级别常量）
    # 每个 key 代表一种任务类型，value 是对应的代理类名
    # 这个映射表定义了系统支持的任务类型以及每种类型的处理者
    TASK_AGENT_MAPPING = {
        "material_design": "CreativeDesigningAgent",           # 材料设计任务 -> 创意设计代理
        "evaluation": "AssessmentScreeningAgent",              # 评估任务 -> 评估筛选代理
        "final_validation": "AssessmentScreeningAgentOverall", # 最终验证 -> 综合评估代理
        "mechanism_analysis": "MechanismMiningAgent",          # 机理分析 -> 机理挖掘代理
        "synthesis_method": "SynthesisGuidingAgent",           # 合成方法 -> 合成指导代理
        "operation_suggestion": "OperationSuggestingAgent",     # 操作建议 -> 操作建议代理
        "literature_processing": "ExtractingAgent",            # 文献处理 -> 信息提取代理
        "coordinator": "TaskOrganizingAgent"                   # 协调任务 -> 自身
    }

    def __init__(self, llm):
        """初始化任务组织代理

        Args:
            llm: 语言模型实例，由外部传入（通常来自 Crew 配置）
        """
        # 调用父类 BaseAgent 的构造函数，传入预先定义的角色和目标
        # role 和 goal 用于 CrewAI 框架识别代理的职责
        super().__init__(
            llm=llm,
            role="Task_Organizing_agent",  # 代理角色：任务组织者
            goal="Organize and coordinate the work of various expert agents to ensure tasks are completed according to plan",
            # 指定该代理使用的提示词模板文件
            prompt_file="task_organizing_agent_prompt.md"
        )
        # 代理注册表：一个字典，key 为代理类型名（str），
        # value 为对应的 Agent 实例或 Agent 列表
        # 使用 Dict 类型注解提高代码可读性
        self._agent_registry: Dict[str, Union[Agent, List[Agent]]] = {}

    def create_agent(self):
        """创建并返回任务组织代理的 CrewAI Agent 实例

        与基类的 create_agent 不同，此方法覆盖了父类实现：
        - 使用构造函数指定的 task_organizing_agent_prompt 作为 backstory
        - allow_delegation=True 允许此代理将子任务委派给其他专家代理
        - 此代理是整个系统的协调中心，必须启用任务委托功能

        Returns:
            Agent: 配置好的协调者 Agent 实例
        """
        return Agent(
            role="Task_Organizing_agent",
            goal="Organize and coordinate experts' work to ensure efficient task completion",
            # 加载构造函数中指定的提示词模板（task_organizing_agent_prompt.md，zh/en 均存在）
            backstory=load_prompt(self.prompt_file),
            verbose=False,           # 关闭详细输出
            allow_delegation=True,   # 关键：协调者必须允许委托，才能将子任务分派给专家代理
            llm=self.llm
        )

    # ============================================================
    #  代理注册表函数（Agent Registry Functions）
    #  管理系统中所有可用代理的注册和查找
    # ============================================================

    def register_agent(self, agent_type: str, agent: Union[Agent, List[Agent]]):
        """注册单个代理到注册表

        将代理实例按类型名存入 self._agent_registry 字典，
        后续可以通过 get_agent_for_task 按类型查找。

        Args:
            agent_type: 代理类型名称（如 "CreativeDesigningAgent"）
            agent: 单个 Agent 实例或 Agent 实例列表
                   （列表形式用于同类型多实例场景，如多个评估专家）
        """
        self._agent_registry[agent_type] = agent
        # 记录 DEBUG 日志，便于追踪注册过程
        logger.debug(f"Registered agent: {agent_type}")

    def register_agents(self, agents_dict: Dict[str, Any]):
        """批量注册代理

        遍历传入的字典，逐个调用 register_agent 完成注册，
        简化多处代理初始化的重复代码。

        Args:
            agents_dict: 格式为 {类型名: 代理实例} 的字典
        """
        for agent_type, agent in agents_dict.items():
            self.register_agent(agent_type, agent)

    def get_agent_for_task(self, task_type: str) -> Union[Agent, None]:
        """根据任务类型获取对应的代理实例

        首先通过 TASK_AGENT_MAPPING 查找任务类型对应的代理类名，
        然后从注册表中取出该代理实例。
        如果注册的是列表，则返回列表中的第一个代理。

        Args:
            task_type: 任务类型字符串（如 "material_design", "evaluation" 等）

        Returns:
            Agent 实例（找到时）或 None（未找到时）
        """
        # 第一步：从映射表查找任务类型对应的代理类名
        agent_type = self.TASK_AGENT_MAPPING.get(task_type)
        if not agent_type:
            # 如果任务类型不在映射表中，记录警告日志
            logger.warning(f"No agent mapping for task type: {task_type}")
            return None

        # 第二步：从注册表中获取代理实例
        agent = self._agent_registry.get(agent_type)
        if agent is None:
            # 代理类型未注册时记录警告
            logger.warning(f"Agent type '{agent_type}' not registered")
            return None

        # 第三步：处理列表形式的代理（同类型多实例）
        # 如果是列表，返回第一个；否则直接返回
        if isinstance(agent, list):
            return agent[0] if agent else None
        return agent

    def get_all_agents_for_task(self, task_type: str) -> List[Agent]:
        """获取任务类型对应的所有代理实例

        与 get_agent_for_task 的区别：
        - get_agent_for_task 返回单个代理（列表取第一个）
        - 此方法返回完整的代理列表，用于需要所有专家同时评估的场景

        Args:
            task_type: 任务类型字符串

        Returns:
            Agent 列表（找到时）或空列表（未找到时）
        """
        # 从映射表查找代理类名
        agent_type = self.TASK_AGENT_MAPPING.get(task_type)
        if not agent_type:
            logger.warning(f"No agent mapping for task type: {task_type}")
            return []

        # 从注册表获取代理
        agent = self._agent_registry.get(agent_type)
        if agent is None:
            logger.warning(f"Agent type '{agent_type}' not registered")
            return []

        # 统一返回列表格式：单个代理包装为列表，列表直接返回
        if isinstance(agent, list):
            return agent
        return [agent]

    # ============================================================
    #  意图识别函数（Intent Recognition Functions）
    #  使用 LLM 分析用户的自然语言需求，提取结构化的意图信息
    # ============================================================

    def analyze_user_intent(self, user_requirement: str) -> dict:
        """使用 LLM 分析用户意图，确定需要执行的任务

        此方法是系统的入口分析点：
        1. 加载意图识别专用的提示词模板
        2. 将用户需求拼接到提示词中
        3. 调用 LLM 获取结构化的 JSON 分析结果
        4. 解析 JSON 并返回意图字典

        Args:
            user_requirement: 用户的自然语言需求描述

        Returns:
            意图分析结果字典，包含以下字段：
            {
                "needs_design": bool,          # 是否需要材料设计
                "needs_evaluation": bool,      # 是否需要评估
                "evaluation_mode": str | null, # 评估模式："experts_only" | "with_summary"
                "needs_mechanism": bool,       # 是否需要机理分析
                "needs_synthesis": bool,       # 是否需要合成方法建议
                "needs_operation": bool,       # 是否需要操作指导
                "material_provided": str | null, # 用户是否提供了具体材料名称
                "reasoning": str               # LLM 的推理过程文本
            }
        """
        try:
            # 加载意图识别专用的提示词模板（intent_recognition_prompt.md）
            intent_prompt = load_prompt("intent_recognition_prompt.md")

            # 构建完整的 Prompt：将提示词模板与用户需求拼接
            # 这样 LLM 可以根据模板要求的结构化格式来分析用户需求
            full_prompt = f"{intent_prompt}\n\nUser requirement:\n{user_requirement}"

            # 调用 LLM 分析意图，传入用户消息
            # 期望 LLM 返回 JSON 格式的分析结果
            response = self.llm.call([{"role": "user", "content": full_prompt}])
            # 去除响应文本的首尾空白字符
            response_text = response.strip()

            # 清除 Markdown 代码块标记（```json 和 ```）
            # LLM 有时会在 JSON 外面包裹 Markdown 格式，需要先移除以确保 JSON 解析成功
            response_text = re.sub(r'^```json\s*', '', response_text)  # 移除开头的 ```json
            response_text = re.sub(r'\s*```$', '', response_text)       # 移除结尾的 ```
            response_text = response_text.strip()                       # 再次去除空白

            # 将清理后的文本解析为 JSON 字典
            intent = json.loads(response_text)

            # 记录 INFO 日志，输出 LLM 的推理过程，便于调试和审计
            # 使用 .get 防止 LLM 返回的 JSON 缺少 reasoning 键时抛出 KeyError
            logger.info(f"TOA Intent Analysis: {intent.get('reasoning', '')}")
            return intent

        except json.JSONDecodeError as e:
            # JSON 解析失败：记录错误详情和原始响应文本，便于排查问题
            logger.error(f"Failed to parse intent JSON: {e}")
            logger.error(f"Response text: {response_text}")
            # 使用默认意图作为降级方案，确保系统不会因为解析失败而崩溃
            # 默认执行最保守的方案：进行材料设计和评估（带总结）
            return {
                "needs_design": True,
                "needs_evaluation": True,
                "evaluation_mode": "with_summary",
                "needs_mechanism": False,
                "needs_synthesis": False,
                "needs_operation": False,
                "material_provided": None,
                "reasoning": "Fallback to default due to JSON parse error"
            }
        except Exception as e:
            # 捕获所有其他异常（如 LLM 调用失败、网络错误等）
            logger.error(f"Intent analysis failed: {e}")
            # 同样使用默认意图作为降级方案
            return {
                "needs_design": True,
                "needs_evaluation": True,
                "evaluation_mode": "with_summary",
                "needs_mechanism": False,
                "needs_synthesis": False,
                "needs_operation": False,
                "material_provided": None,
                "reasoning": "Fallback to default due to error"
            }
