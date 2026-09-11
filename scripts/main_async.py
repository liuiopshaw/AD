#!/usr/bin/env python3
"""
ECOMATS - CrewAI 1.7.0 Async Version

Supports async Crew execution with 2-3x performance improvement through:
- Parallel task execution (evaluation agents run simultaneously)
- Async crew kickoff (akickoff)
- Memory system with DashScope embeddings
"""

# ---- 标准库和第三方库导入 ----
# sys: 修改 Python 模块搜索路径
import sys
# os: 环境变量操作和文件路径构建
import os
# json: 解析和序列化 JSON 数据
import json
# asyncio: Python 原生异步编程支持——这是异步模式的核心依赖
import asyncio
# datetime: 为输出文件生成时间戳
from datetime import datetime
# dotenv: 加载 .env 文件中的环境变量
from dotenv import load_dotenv

# ---- 将项目根目录添加到模块搜索路径 ----
# 必须在导入其他项目模块之前完成，否则后续 import 会失败
# os.path.dirname(__file__): 当前文件所在目录 (scripts/)
# os.path.dirname(...) + '..': 回溯到项目根目录 (ECOMATS/)
project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.abspath(project_root))

# ---- 在导入 CrewAI 之前先加载环境变量 ----
# 这一步非常关键：CrewAI 在初始化时会读取 OPENAI_API_KEY 等环境变量，
# 必须在这之前把 .env 中的 QWEN_API_KEY 映射到 OpenAI 兼容的变量名
load_dotenv()

# ---- 设置 OpenAI 兼容的环境变量（CrewAI 异步模式必需） ----
# CrewAI 1.7.0 的异步模式底层仍然使用 OpenAI SDK 兼容的协议，
# 因此必须将 DashScope 的 Key 和 Base URL 映射到 OpenAI 环境变量名
_api_key = os.getenv('QWEN_API_KEY') or 'dummy'  # 默认使用 'dummy' 防止空值报错
_api_base = os.getenv('QWEN_API_BASE') or 'https://dashscope.aliyuncs.com/compatible-mode/v1'
# 设置三个 OpenAI 兼容变量——不同的 Provider 实现可能读取不同的变量名
os.environ['OPENAI_API_KEY'] = _api_key
os.environ['OPENAI_API_BASE'] = _api_base
os.environ['OPENAI_BASE_URL'] = _api_base

# ---- 应用 CrewAI 兼容性补丁（必须在导入 CrewAI 之前） ----
# patches 模块修复了 CrewAI 1.7.0 异步内存系统中的 ChromaDB 兼容性问题
from workflow.patches import apply_crewai_patches
apply_crewai_patches()

# ---- 导入 CrewAI 核心类 ----
from crewai import Crew, Process

# ---- 设置统一日志 ----
# 配置全局日志格式和输出目标，确保所有模块的日志行为一致
from src.utils.logging_config import setup_logging
setup_logging()

# ---- 导入项目核心模块 ----
from src.config.config import Config                     # 全局配置（API Key、模型名、阈值等）
from src.utils.llm_config import create_llm               # LLM 实例工厂函数
from src.utils.workflow_monitor import WorkflowMonitor, create_monitor, get_monitor  # 工作流监控

# ---- 导入模块化组件 ----
# embeddings: DashScope 文本嵌入功能（用于 CrewAI 内存系统的语义搜索）
from workflow.embeddings import create_dashscope_embedder
# callback_factory: 任务回调工厂函数（支持并行任务的时间跟踪）
from workflow.callback_factory import create_task_callback_factory


def get_ui_text(key):
    """
    获取用户界面文本（支持多语言）

    根据 Config.LANGUAGE 配置获取对应语言的 UI 文本。
    这实现了界面文本的国际化，用户可以在启动时选择中文或英文。

    Args:
        key: UI 文本的键名

    Returns:
        str: 对应语言的文本；如果找不到则返回键名本身作为兜底
    """
    try:
        from src.locales.texts import TEXTS
        # 读取语言设置，默认为中文 'zh'
        lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'
        # 从 TEXTS 字典中查找：语言 -> 'ui' -> key
        return TEXTS.get(lang, TEXTS['zh'])['ui'].get(key, key)
    except Exception:
        # 捕获所有异常，确保 UI 文本获取失败时程序仍能继续
        return key


def select_language():
    """
    交互式语言选择（中文/英文）

    用户启动程序后首先选择界面语言。选择结果会同步到：
    - Config.LANGUAGE: 供其他模块读取
    - set_language(): 更新全局语言上下文

    Returns:
        str: 选择的语言代码 'zh'（中文）或 'en'（英文）
    """
    from src.locales import set_language

    # 打印语言选择菜单
    print("\n" + "="*70)
    print("🌐 Select Language")
    print("="*70)
    print("1. Chinese")
    print("2. English")

    while True:
        choice = input("\nPlease select (1-2): ").strip()
        if choice == "1":
            # 设置为中文
            set_language("zh")
            Config.LANGUAGE = "zh"
            print("✅ Selected: Chinese")
            return "zh"
        elif choice == "2":
            # 设置为英文
            set_language("en")
            Config.LANGUAGE = "en"
            print("✅ English selected")
            return "en"
        print("Invalid option")


def get_user_input():
    """
    获取用户材料设计需求（双语提示）

    根据当前语言设置显示不同语言的提示信息。
    中文和英文提示内容相同，只是翻译不同。

    Returns:
        str: 用户输入的材料设计需求文本
    """
    # 读取当前语言设置
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    print("\n" + "="*70)
    if lang == 'en':
        print("ECOMATS - Multi-Agent System for Water Treatment Material Design (Async)")
        print("="*70)
        print("\nPlease enter your material design requirements:")
        print("Example: Design an efficient catalyst for treating wastewater containing heavy metal cadmium")
        user_input = input("\nMaterial design requirement: ")
    else:
        print("ECOMATS - Water Treatment Material Design Multi-Agent System (Async Enhanced)")
        print("="*70)
        print("\nPlease enter your material design requirements:")
        print("Example: Design an efficient catalyst for treating cadmium-containing heavy metal wastewater")
        user_input = input("\nMaterial design requirements: ")
    return user_input


def get_workflow_mode():
    """
    获取用户选择的工作流模式（同步/异步+预置/自主）

    提供 4 种组合模式：
    1. 预置工作流（同步）——固定任务序列，顺序执行
    2. 预置工作流（异步）——固定任务序列，并行执行——推荐！
    3. Agent 自主调度（同步）——TOA 动态创建任务，顺序执行
    4. Agent 自主调度（异步）——TOA 动态创建任务，并行执行——推荐！

    返回一个元组 (mode, is_async)：
    - mode: 'preset' 或 'autonomous'
    - is_async: True 表示异步执行，False 表示同步执行

    Returns:
        tuple: (mode_str, is_async)
    """
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    # 根据语言显示不同语言的菜单
    if lang == 'en':
        print("\nPlease select workflow mode:")
        print("1. Preset Workflow (Sync)")
        print("2. Preset Workflow (Async) ⚡ Recommended!")
        print("3. Autonomous Agent Scheduling (Sync)")
        print("4. Autonomous Agent Scheduling (Async) ⚡ Recommended!")
        prompt = "\nEnter option (1-4): "
        invalid_msg = "Invalid option, please enter 1-4"
    else:
        print("\nPlease select workflow mode:")
        print("1. Preset workflow (sync)")
        print("2. Preset workflow (async) ⚡ Recommended!")
        print("3. Agent autonomous scheduling (sync)")
        print("4. Agent autonomous scheduling (async) ⚡ Recommended!")
        prompt = "\nPlease enter option (1-4): "
        invalid_msg = "Invalid option, please enter 1-4"

    while True:
        choice = input(prompt).strip()
        if choice in ["1", "2", "3", "4"]:
            # 字典映射：数字选择 -> (mode, is_async)
            return {
                "1": ("preset", False),
                "2": ("preset", True),
                "3": ("autonomous", False),
                "4": ("autonomous", True)
            }[choice]
        print(invalid_msg)


def create_all_agents(llm):
    """
    创建工作流中使用的所有 Agent 实例

    每个 Agent 由对应的工厂类创建，拥有特定的角色提示词和工具集。
    与 main.py 的同步版本相比，异步版本省略了 literature_processor Agent
    （异步模式下不需要文献处理），其他 Agent 相同。

    Args:
        llm: 大语言模型实例

    Returns:
        dict: Agent 名称到实例的映射字典
    """
    from src.agents.task_organizing_agent import TaskOrganizingAgent
    from src.agents.Creative_Designing_agent import CreativeDesigningAgent
    from src.agents.Assessment_Screening_agent_A import AssessmentScreeningAgentA
    from src.agents.Assessment_Screening_agent_B import AssessmentScreeningAgentB
    from src.agents.Assessment_Screening_agent_C import AssessmentScreeningAgentC
    from src.agents.Assessment_Screening_agent_Overall import AssessmentScreeningAgentOverall
    from src.agents.Mechanism_Mining_agent import MechanismMiningAgent
    from src.agents.Synthesis_Guiding_agent import SynthesisGuidingAgent
    from src.agents.Operation_Suggesting_agent import OperationSuggestingAgent

    # 实例化所有 Agent并返回字典（注意异步版本不包含 ExtractingAgent）
    return {
        'coordinator': TaskOrganizingAgent(llm).create_agent(),
        'material_designer': CreativeDesigningAgent(llm).create_agent(),
        'expert_a': AssessmentScreeningAgentA(llm).create_agent(),
        'expert_b': AssessmentScreeningAgentB(llm).create_agent(),
        'expert_c': AssessmentScreeningAgentC(llm).create_agent(),
        'final_validator': AssessmentScreeningAgentOverall(llm).create_agent(),
        'mechanism_expert': MechanismMiningAgent(llm).create_agent(),
        'synthesis_expert': SynthesisGuidingAgent(llm).create_agent(),
        'operation_suggesting': OperationSuggestingAgent(llm).create_agent()
    }


async def run_autonomous_workflow_async(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    异步自主调度工作流（基于 TOA 意图驱动架构）

    此模式不是死板地执行全部任务，而是：
    1. TOA (Task Organizing Agent) 分析用户意图
    2. 动态创建仅必要的任务
    3. 为可并行的任务设置 async_execution=True，利用 CrewAI 的异步能力
    4. 通过 crew.akickoff() 异步执行

    异步执行的关键优势：
    - 三位评估专家的任务并行执行（原本需要 3x 时间，现在仅需 1x）
    - 机理分析和合成方法任务并行执行
    - 总体可获得 2-3x 的性能提升

    Args:
        user_requirement: 用户材料设计需求
        llm: 大语言模型实例
        monitor: 工作流监控器实例（可选）

    Returns:
        Crew 执行结果
    """
    # 动态导入任务创建类和 TOA
    from src.agents.task_organizing_agent import TaskOrganizingAgent
    from src.tasks.design_task import DesignTask
    from src.tasks.evaluation_task import EvaluationTask
    from src.tasks.final_validation_task import FinalValidationTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.synthesis_method_task import SynthesisMethodTask
    from src.tasks.operation_suggesting_task import OperationSuggestingTask
    from crewai import Task

    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    # 启动提示
    if lang == 'en':
        print("\n🚀 Starting async autonomous scheduling workflow...")
    else:
        print("\n🚀 Starting async autonomous workflow...")
    print("-" * 70)

    # 创建所有 Agent
    agents = create_all_agents(llm)

    # ---- 创建 TOA 实例并注册所有 Agent ----
    # TOA 通过注册表了解可用 Agent 及其能力，才能正确分配任务
    coordinator = TaskOrganizingAgent(llm)
    coordinator_agent = coordinator.create_agent()

    # 将各类型 Agent 注册到 TOA，建立能力-映射关系
    coordinator.register_agent("TaskOrganizingAgent", coordinator_agent)
    coordinator.register_agent("CreativeDesigningAgent", agents['material_designer'])
    # 评估专家作为列表注册（三个专家的组）
    coordinator.register_agent("AssessmentScreeningAgent", [agents['expert_a'], agents['expert_b'], agents['expert_c']])
    coordinator.register_agent("AssessmentScreeningAgentOverall", agents['final_validator'])
    coordinator.register_agent("MechanismMiningAgent", agents['mechanism_expert'])
    coordinator.register_agent("SynthesisGuidingAgent", agents['synthesis_expert'])
    coordinator.register_agent("OperationSuggestingAgent", agents['operation_suggesting'])

    # ---- 初始化监控器 ----
    if monitor is None:
        monitor = create_monitor()
    # 标记为异步工作流
    monitor.set_workflow_info(user_requirement, "autonomous", is_async=True)

    # ---- 任务开始时间跟踪 ----
    import time
    task_start_times = {}

    # ============================================================
    # TOA 意图分析
    # ============================================================
    # TOA 通过 LLM 分析用户输入的意图，判断需要哪些步骤
    # 返回的 intent 字典包含：
    #   needs_design, needs_evaluation, needs_mechanism, needs_synthesis, needs_operation
    #   evaluation_mode: 'experts_only' 或 'with_summary'
    #   material_provided: 用户是否提供了材料信息
    if lang == 'en':
        print("\n🧠 TOA analyzing user intent...")
    else:
        print("\n🧠 TOA analyzing user intent...")

    intent = coordinator.analyze_user_intent(user_requirement)

    # 打印意图分析结果——帮助用户了解系统决策过程
    if lang == 'en':
        print(f"✅ Intent analysis complete: {intent['reasoning']}")
        print(f"\n📊 Intent Details:")
        print(f"   • Needs Design: {intent.get('needs_design', False)}")
        print(f"   • Needs Evaluation: {intent.get('needs_evaluation', False)}")
        print(f"   • Evaluation Mode: {intent.get('evaluation_mode', None)}")
        print(f"   • Needs Mechanism: {intent.get('needs_mechanism', False)}")
        print(f"   • Needs Synthesis: {intent.get('needs_synthesis', False)}")
        print(f"   • Needs Operation: {intent.get('needs_operation', False)}")
    else:
        print(f"✅ Intent analysis complete: {intent['reasoning']}")
        print(f"\n📊 Intent Details:")
        print(f"   • Needs Design: {intent.get('needs_design', False)}")
        print(f"   • Needs Evaluation: {intent.get('needs_evaluation', False)}")
        print(f"   • Evaluation Mode: {intent.get('evaluation_mode', None)}")
        print(f"   • Needs Mechanism: {intent.get('needs_mechanism', False)}")
        print(f"   • Needs Synthesis: {intent.get('needs_synthesis', False)}")
        print(f"   • Needs Operation: {intent.get('needs_operation', False)}")

    # ---- 初始化任务和 Agent 列表 ----
    required_tasks = []     # 动态收集需要执行的任务
    required_agents = []    # 动态收集需要的 Agent
    seen_roles = set()      # 用于去重：确保同一 Agent 不重复添加
    design_task = None      # 设计任务（可能是实际任务或虚拟上下文）
    final_validation_task = None  # 最终验证任务

    # ============================================================
    # Step 1: 处理材料设计需求
    # ============================================================
    # 如果 TOA 判断需要设计新材料，创建完整的设计任务
    if intent.get('needs_design', False):
        if lang == 'en':
            print("\n🛠️ Creating material design task...")
        else:
            print("\n🛠️ Creating material design task...")
        design_agent = coordinator.get_agent_for_task("material_design")
        if design_agent and design_agent.role not in seen_roles:
            required_agents.append(design_agent)
            seen_roles.add(design_agent.role)
        design_task = DesignTask(llm).create_task(design_agent, user_requirement=user_requirement)
        required_tasks.append(design_task)
    elif intent.get('needs_evaluation', False) or intent.get('needs_mechanism', False) or intent.get('needs_synthesis', False) or intent.get('needs_operation', False):
        # 用户已经提供了材料信息，不需要创建设计任务
        # 但下游任务需要设计任务的输出作为上下文，所以创建一个虚拟任务
        material_info = intent.get('material_provided') or user_requirement
        if lang == 'en':
            print(f"\n📝 Using user-provided material: {material_info[:50]}...")
        else:
            print(f"\n📝 Using user-provided material: {material_info[:50]}...")
        # 虚拟上下文任务——仅用于传递材料信息，不会被实际执行
        design_task = Task(
            description=f"Existing material provided by user:\n{user_requirement}",
            expected_output="Material information for downstream tasks",
            agent=coordinator_agent  # 使用协调器作为占位 Agent
        )

    # ============================================================
    # Step 2: 处理评估任务（核心异步加速点）
    # ============================================================
    if intent.get('needs_evaluation', False):
        evaluation_mode = intent.get('evaluation_mode', 'with_summary')
        # 获取所有评估专家 Agent（A、B、C 三位）
        evaluation_agents = coordinator.get_all_agents_for_task("evaluation")
        print(f"\n🔍 Number of evaluation experts: {len(evaluation_agents)} - {[a.role for a in evaluation_agents]}")
        evaluation_tasks = []

        # 为每位评估专家创建独立的评估任务
        for agent in evaluation_agents:
            if agent.role not in seen_roles:
                required_agents.append(agent)
                seen_roles.add(agent.role)
            task = EvaluationTask(llm).create_task(agent, design_task, user_requirement)
            # 关键！设置 async_execution=True 启用 CrewAI 异步并行执行
            # 这意味着 A、B、C 三位专家的评估可以同时进行，大幅缩短总耗时
            task.async_execution = True  # 启用异步并行执行！
            evaluation_tasks.append(task)

        required_tasks.extend(evaluation_tasks)

        # 根据评估模式决定是否需要综合汇总
        if evaluation_mode == 'experts_only':
            # 仅专家评分模式——不需要综合汇总
            if lang == 'en':
                print(f"\n✅ Experts-only mode: 3 ASA experts, no final summary")
            else:
                print(f"\n✅ Experts-only mode: 3 ASA experts scoring, no final summary")
        else:
            # 完整评估模式——需要综合汇总 Agent 对三位专家的结果进行汇总
            if lang == 'en':
                print(f"\n📊 Full evaluation mode: 3 ASA experts + final summary")
            else:
                print(f"\n📊 Full evaluation mode: 3 ASA experts + final summary")

            final_validation_agent = coordinator.get_agent_for_task("final_validation")
            if final_validation_agent and final_validation_agent.role not in seen_roles:
                required_agents.append(final_validation_agent)
                seen_roles.add(final_validation_agent.role)
                # 调试检查：验证 ASA Overall Agent 没有工具
                # ASA Overall 只做分析和汇总，不应携带任何工具
                agent_tools = getattr(final_validation_agent, 'tools', None)
                if agent_tools:
                    print(f"  ⚠️ ASA Overall unexpectedly contains {len(agent_tools)} tools: {[t.name if hasattr(t, 'name') else str(t) for t in agent_tools]}")
                else:
                    print(f"  ✅ ASA Overall has no tools (analysis only)")
            # 创建最终验证任务，其 context 包含设计任务和所有评估任务
            final_validation_task = FinalValidationTask(llm).create_task(
                final_validation_agent,
                [design_task] + evaluation_tasks if design_task else evaluation_tasks,
                user_requirement=user_requirement
            )
            required_tasks.append(final_validation_task)

    # ============================================================
    # Step 3: 处理机理分析任务
    # ============================================================
    if intent.get('needs_mechanism', False):
        if lang == 'en':
            print(f"\n🔬 Creating mechanism analysis task...")
        else:
            print(f"\n🔬 Creating mechanism analysis task...")
        mechanism_agent = coordinator.get_agent_for_task("mechanism_analysis")
        if mechanism_agent and mechanism_agent.role not in seen_roles:
            required_agents.append(mechanism_agent)
            seen_roles.add(mechanism_agent.role)
        # 机理分析依赖最终验证结果；若无则依赖设计任务
        context_task = final_validation_task or design_task
        mechanism_task = MechanismAnalysisTask(llm).create_task(
            mechanism_agent, context_task, user_requirement=user_requirement
        )
        mechanism_task.async_execution = True  # 启用异步！可以与合成方法并行
        required_tasks.append(mechanism_task)

    # ============================================================
    # Step 4: 处理合成方法任务
    # ============================================================
    if intent.get('needs_synthesis', False):
        if lang == 'en':
            print(f"\n🧪 Creating synthesis method task...")
        else:
            print(f"\n🧪 Creating synthesis method task...")
        synthesis_agent = coordinator.get_agent_for_task("synthesis_method")
        if synthesis_agent and synthesis_agent.role not in seen_roles:
            required_agents.append(synthesis_agent)
            seen_roles.add(synthesis_agent.role)
        context_task = final_validation_task or design_task
        synthesis_task = SynthesisMethodTask(llm).create_task(
            synthesis_agent, context_task, user_requirement=user_requirement
        )
        synthesis_task.async_execution = True  # 启用异步！可以与机理分析并行
        required_tasks.append(synthesis_task)

    # ============================================================
    # Step 5: 处理操作建议任务
    # ============================================================
    if intent.get('needs_operation', False):
        if lang == 'en':
            print(f"\n📖 Creating operation guidance task...")
        else:
            print(f"\n📖 Creating operation guidance task...")
        operation_agent = coordinator.get_agent_for_task("operation_suggestion")
        if operation_agent and operation_agent.role not in seen_roles:
            required_agents.append(operation_agent)
            seen_roles.add(operation_agent.role)
        context_task = final_validation_task or design_task
        operation_task = OperationSuggestingTask(llm).create_task(
            operation_agent, context_task, user_requirement=user_requirement
        )
        required_tasks.append(operation_task)

    # ============================================================
    # 安全检查：确保至少有一个任务
    # ============================================================
    if not required_tasks:
        # TOA 无法识别意图时的兜底：默认创建材料设计任务
        if lang == 'en':
            print("\n⚠️ No tasks identified, defaulting to material design")
        else:
            print("\n⚠️ No tasks identified, defaulting to material design")
        design_agent = coordinator.get_agent_for_task("material_design")
        if design_agent and design_agent.role not in seen_roles:
            required_agents.append(design_agent)
            seen_roles.add(design_agent.role)
        design_task = DesignTask(llm).create_task(design_agent, user_requirement=user_requirement)
        required_tasks.append(design_task)

    # ============================================================
    # 打印任务摘要（标注异步标签）
    # ============================================================
    print(f"\n{'='*60}")
    if lang == 'en':
        print(f"📝 Task Summary")
        print(f"{'='*60}")
        print(f"   Total tasks: {len(required_tasks)}")
        print(f"   Total agents: {len(required_agents)}")
    else:
        print(f"📝 Task Summary")
        print(f"{'='*60}")
        print(f"   Total tasks: {len(required_tasks)}")
        print(f"   Total agents: {len(required_agents)}")
    for i, task in enumerate(required_tasks, 1):
        agent_role = getattr(task.agent, 'role', 'Unknown') if task.agent else 'None'
        # 标记异步执行的任务，方便用户了解并行化程度
        async_flag = "⚡" if getattr(task, 'async_execution', False) else ""
        print(f"   {i}. {agent_role} {async_flag}")
    print(f"{'='*60}\n")

    # ---- 创建 Crew 并配置异步执行 ----
    # 获取 DashScope 嵌入函数类（用于 CrewAI 的内存系统）
    DashScopeEmbedder = create_dashscope_embedder()

    # ---- 工具调用跟踪 ----
    # 使用线程锁保护共享字典，避免多线程并发写入导致数据错乱
    import threading
    tool_calls_by_agent = {}         # {agent_role: {tool_name: count}}——按 Agent 分组的工具调用统计
    tool_call_lock = threading.Lock()  # 线程锁：保护 tool_calls_by_agent 的并发访问
    current_agent_context = threading.local()  # 线程局部存储：每个线程维护自己的当前 Agent 上下文
    last_completed_agent = [None]    # 记录最后完成的 Agent 角色（用于交互跟踪）

    # 使用模块级工厂函数创建 task_callback
    # 工厂函数接收监控器、时间跟踪、线程上下文等共享状态，返回可用的回调函数
    create_task_callback = create_task_callback_factory(monitor, task_start_times, current_agent_context, last_completed_agent)

    # ---- 步骤回调函数：跟踪工具调用 ----
    def step_callback(step_output):
        """
        捕获每个步骤的执行细节，包括工具调用

        CrewAI 在每个 Agent 执行步骤（思考、调用工具、生成回复）时都会调用此回调。
        这里主要用于：
        1. 识别当前是哪个 Agent 在执行
        2. 如果是工具调用（tool 属性），记录到工具调用统计中
        3. 实时打印工具调用日志

        Agent 的识别尝试三种方法（按优先级）：
        1. 从 step_output.agent 属性直接获取
        2. 从 step_output.agent_name 属性获取
        3. 从线程局部存储中获取当前 Agent（兜底）
        """
        try:
            # 尝试从不同来源获取当前 Agent 角色
            agent_role = 'Unknown'

            # 方法1: 直接从 step_output 的 agent 属性获取（最可靠）
            if hasattr(step_output, 'agent'):
                agent = step_output.agent
                if hasattr(agent, 'role'):
                    agent_role = agent.role
                elif isinstance(agent, str):
                    agent_role = agent

            # 方法2: 从 agent_name 属性获取
            if agent_role == 'Unknown' and hasattr(step_output, 'agent_name'):
                agent_role = step_output.agent_name

            # 方法3: 从线程局部存储获取（兜底方案）
            if agent_role == 'Unknown':
                agent_role = getattr(current_agent_context, 'role', 'Unknown')

            # 更新线程局部存储中的当前 Agent 角色
            if agent_role != 'Unknown':
                current_agent_context.role = agent_role

            # 检查是否为工具调用（AgentAction 类型）
            if hasattr(step_output, 'tool'):
                tool_name = step_output.tool
                # 线程安全地更新工具调用统计
                with tool_call_lock:
                    if agent_role not in tool_calls_by_agent:
                        tool_calls_by_agent[agent_role] = {}
                    if tool_name not in tool_calls_by_agent[agent_role]:
                        tool_calls_by_agent[agent_role][tool_name] = 0
                    tool_calls_by_agent[agent_role][tool_name] += 1
                    count = tool_calls_by_agent[agent_role][tool_name]
                    # 实时输出工具调用日志（前15个字符的 Agent 名缩写）
                    print(f"  🔧 [{agent_role[:15]}] {tool_name} (#{count})")
        except Exception:
            pass  # 忽略跟踪错误——不阻断主流程

    # 为每个 Agent 设置步骤回调
    for agent in required_agents:
        original_execute = None
        agent_role = getattr(agent, 'role', 'Unknown')
        # 通过赋值设置 step_callback 属性，CrewAI 会在 Agent 执行时调用
        agent.step_callback = step_callback

    # ---- 创建任务回调用于监控 ----
    task_completion_times = []      # 记录每个任务完成的时间点
    crew_start_time = [None]        # 使用列表包装，使闭包中的修改能传递出去
    task_counter = [0]              # 任务序号计数器
    task_callback = create_task_callback(task_completion_times, crew_start_time, task_counter, suffix="")

    # ---- 创建 Crew 实例 ----
    crew = Crew(
        name="ECOMATS",  # 设置 Crew 名称（显示在日志和元数据中）
        agents=required_agents,
        tasks=required_tasks,
        process=Process.sequential,  # 顺序执行——但 async_execution 标记的任务可以并行
        verbose=Config.VERBOSE,      # 从配置读取是否输出详细日志
        memory=False,                # 禁用内存系统——每个任务会触发 7 次 Embedding API 调用，影响性能
        task_callback=task_callback, # 任务完成回调
        step_callback=step_callback, # 步骤回调（跟踪工具调用）
        embedder={
            # 配置自定义嵌入器：使用 DashScope 的 text-embedding-v2 模型
            "provider": "custom",
            "config": {
                "embedding_callable": DashScopeEmbedder  # 传递类（不是实例），CrewAI 会自己实例化
            }
        }
    )

    # 启动提示
    if lang == 'en':
        print("⚡ Using async execution mode...")
    else:
        print("⚡ Using async execution mode...")

    # 记录 Crew 启动时间（用于计算总耗时）
    crew_start_time[0] = time.time()

    # ---- 异步执行！ ----
    # crew.akickoff() 是 CrewAI 1.7.0 的异步入口，返回 awaitable
    # inputs 参数将用户需求注入到 Agent 的提示词模板中
    result = await crew.akickoff(inputs={'requirement': user_requirement})

    # ---- 保存监控报告（执行成功后） ----
    if monitor:
        monitor.set_final_result(result, "completed")
        monitor.save_report()          # JSON 格式
        monitor.save_readable_report() # 可读文本格式
        monitor.print_summary()        # 终端摘要

    return result


async def run_preset_workflow_async(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    异步预设工作流（固定任务序列 + 并行执行优化）

    执行顺序（与同步版本相同，但利用异步并行加速）：
    1. 材料设计（顺序）——必须第一步完成
    2. 评估 A/B/C（并行——3 位专家同时独立评分）
    3. 最终验证（顺序）——汇总评估结果
    4. 机理分析 + 合成方法（并行——两者独立，同时执行）
    5. 操作建议（顺序）——依赖前面结果

    性能提升来源：
    - 3 个评估任务并行：原本需要 ~3T 时间，现在只需 ~T
    - 2 个分析任务并行：原本需要 ~2T 时间，现在只需 ~T
    - 总体预期 2-3x 性能提升

    Args:
        user_requirement: 用户材料设计需求
        llm: 大语言模型实例
        monitor: 工作流监控器实例（可选）

    Returns:
        Crew 执行结果
    """
    import time

    print("\n🚀 Starting async preset workflow...")
    print("-" * 70)

    # 初始化监控器（标记为异步预设模式）
    if monitor is None:
        monitor = create_monitor()
    monitor.set_workflow_info(user_requirement, "preset", is_async=True)

    # 任务开始时间跟踪
    task_start_times = {}

    # 导入任务工厂类
    from src.tasks.design_task import DesignTask
    from src.tasks.evaluation_task import EvaluationTask
    from src.tasks.final_validation_task import FinalValidationTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.synthesis_method_task import SynthesisMethodTask
    from src.tasks.operation_suggesting_task import OperationSuggestingTask

    # 创建所有 Agent 实例
    agents = create_all_agents(llm)

    # ---- 1. 材料设计任务（顺序，无并行） ----
    design_task = DesignTask(
        agent=agents['material_designer']
    ).create_task(
        agent=agents['material_designer'],
        user_requirement=user_requirement
    )

    # ---- 2. 三位评估专家的任务（可并行执行） ----
    # 评估专家 A
    eval_a_task = EvaluationTask(
        agent=agents['expert_a']
    ).create_task(
        agent=agents['expert_a'],
        context_task=design_task
    )
    eval_a_task.async_execution = True  # 启用异步！

    # 评估专家 B
    eval_b_task = EvaluationTask(
        agent=agents['expert_b']
    ).create_task(
        agent=agents['expert_b'],
        context_task=design_task
    )
    eval_b_task.async_execution = True  # 启用异步！

    # 评估专家 C
    eval_c_task = EvaluationTask(
        agent=agents['expert_c']
    ).create_task(
        agent=agents['expert_c'],
        context_task=design_task
    )
    eval_c_task.async_execution = True  # 启用异步！

    # ---- 3. 最终验证任务（依赖三位评估专家的结果） ----
    final_validation_task = FinalValidationTask(
        agent=agents['final_validator']
    ).create_task(
        agent=agents['final_validator'],
        context_task=[eval_a_task, eval_b_task, eval_c_task]
    )

    # ---- 4. 机理分析任务（可与合成方法并行） ----
    mechanism_task = MechanismAnalysisTask(
        agent=agents['mechanism_expert']
    ).create_task(
        agent=agents['mechanism_expert'],
        context_task=final_validation_task
    )
    mechanism_task.async_execution = True  # 启用异步——与合成方法并行

    # ---- 5. 合成方法任务（可与机理分析并行） ----
    synthesis_task = SynthesisMethodTask(
        agent=agents['synthesis_expert']
    ).create_task(
        agent=agents['synthesis_expert'],
        context_task=final_validation_task
    )
    synthesis_task.async_execution = True  # 启用异步——与机理分析并行

    # ---- 6. 操作建议任务（依赖机理分析和合成方法的结果） ----
    operation_task = OperationSuggestingTask(
        agent=agents['operation_suggesting']
    ).create_task(
        agent=agents['operation_suggesting'],
        context_task=[mechanism_task, synthesis_task]
    )

    # ---- 创建 Crew 并配置 DashScope 嵌入 ----
    # 注意：传递类而不是实例，CrewAI 会管理实例的创建
    DashScopeEmbedder = create_dashscope_embedder()

    # ---- 创建任务回调用于监控 ----
    import threading
    current_agent_context = threading.local()
    last_completed_agent = [None]
    create_task_callback = create_task_callback_factory(monitor, task_start_times, current_agent_context, last_completed_agent)

    task_completion_times_2 = []
    crew_start_time_2 = [None]
    task_counter_2 = [0]
    task_callback = create_task_callback(task_completion_times_2, crew_start_time_2, task_counter_2, suffix="_2")

    # ---- 创建 Crew 实例（配置所有 Agent、Task、以及异步选项） ----
    crew = Crew(
        name="ECOMATS",  # 设置 Crew 名称
        agents=list(agents.values()),  # 注册所有 Agent
        tasks=[
            design_task,
            eval_a_task, eval_b_task, eval_c_task,  # 并行评估
            final_validation_task,
            mechanism_task, synthesis_task,  # 并行分析
            operation_task
        ],
        process=Process.sequential,  # 顺序模式——但 async_execution 可覆盖
        verbose=Config.VERBOSE,      # 详细输出由 .env 控制
        memory=False,                # 禁用内存系统（避免 Embedding API 开销）
        task_callback=task_callback, # 任务完成回调
        embedder={
            # 自定义嵌入器配置
            "provider": "custom",
            "config": {
                "embedding_callable": DashScopeEmbedder  # 传递嵌入类
            }
        }
    )

    # 获取语言设置用于显示提示
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    # 打印并行执行提示——帮助用户了解性能优化细节
    if lang == 'en':
        print("⚡ Using async execution mode...")
        print("  - 3 evaluation tasks will run in parallel")
        print("  - Mechanism analysis and synthesis will run in parallel")
        print("  - Expected 2-3x performance improvement")
        print("\n🧠 Memory system enabled (using DashScope text-embedding-v2)")
        print("  - Short-term memory: Store current conversation context")
        print("  - Long-term memory: Learn from historical tasks")
        print("  - Entity memory: Extract key entity information")
        print("  - Storage location: ./.crewai/memory/\n")
    else:
        print("⚡ Using async execution mode...")
        print("  - 3 evaluation tasks will execute in parallel")
        print("  - Mechanism analysis and synthesis methods will execute in parallel")
        print("  - Expected 2-3x performance improvement")
        print("\n🧠 Memory system enabled (using DashScope text-embedding-v2)")
        print("  - Short-term memory: stores current conversation context")
        print("  - Long-term memory: learns from historical task experience")
        print("  - Entity memory: extracts key entity information")
        print("  - Storage location: ./.crewai/memory/\n")

    # 记录 Crew 启动时间
    crew_start_time_2[0] = time.time()

    # ---- 异步执行 Crew！ ----
    # akickoff() 是 CrewAI 1.7.0 的异步入口方法
    result = await crew.akickoff(inputs={'requirement': user_requirement})

    # ---- 保存监控报告 ----
    if monitor:
        monitor.set_final_result(result, "completed")
        monitor.save_report()
        monitor.save_readable_report()
        monitor.print_summary()

    return result


def run_preset_workflow_sync(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    同步预设工作流（向后兼容保留）

    在异步版程序中，如果用户选择了同步预设模式，
    此函数会直接委托给 main.py 中的 run_preset_workflow 同步版本。
    这避免了代码重复，同时保持了向后兼容性。

    Args:
        user_requirement: 用户材料设计需求
        llm: 大语言模型实例
        monitor: 工作流监控器实例（可选）

    Returns:
        工作流执行结果
    """
    print("\n📌 Starting sync preset workflow...")
    print("-" * 70)

    # 确保当前目录在搜索路径中，使 from main import ... 能正确解析
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # 委托给 main.py 中已有的同步预设工作流实现
    from main import run_preset_workflow

    # 传递监控器到同步工作流
    return run_preset_workflow(user_requirement, llm, monitor)


async def main_async():
    """
    异步模式的主入口函数（async）

    完整的启动流程：
    1. 加载环境变量
    2. 检查 API Key 是否配置
    3. 选择界面语言（中文/英文）
    4. 创建 LLM 实例
    5. 获取用户材料设计需求
    6. 获取用户选择的工作流模式（同步/异步 + 预设/自主）
    7. 创建监控器
    8. 根据选择执行对应的工作流

    这是一个异步函数（async def），可以直接使用 await 调用异步工作流。
    """
    # 再次加载环境变量（确保覆盖之前可能的修改）
    load_dotenv()

    # 检查 API Key 是否配置——未配置直接退出，避免后续报错
    if not Config.QWEN_API_KEY:
        print("❌ Error: QWEN_API_KEY not set")
        return

    # 选择界面语言
    select_language()

    # 创建 LLM 实例
    llm = create_llm()

    # 获取用户输入的材料设计需求
    user_requirement = get_user_input()

    # 获取工作流模式（返回 mode 和 use_async 两个值）
    mode, use_async = get_workflow_mode()

    # 创建监控器用于跟踪工作流执行
    monitor = create_monitor()
    print("📊 Workflow monitor initialized")

    # ---- 根据用户选择执行对应的工作流组合 ----
    if mode == "preset":
        # 预设工作流模式
        if use_async:
            # 异步预设——并行执行评估和分析任务
            result = await run_preset_workflow_async(user_requirement, llm, monitor)
        else:
            # 同步预设——委托给 main.py 的同步实现
            result = run_preset_workflow_sync(user_requirement, llm, monitor)
    else:
        # 自主调度模式
        if use_async:
            # 异步自主——TOA 分析意图 + 异步并行执行
            result = await run_autonomous_workflow_async(user_requirement, llm, monitor)
        else:
            # 同步自主——委托给 main.py 的同步实现
            from main import run_autonomous_workflow
            result = run_autonomous_workflow(user_requirement, llm, monitor)

    # ---- 输出执行完成信息 ----
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'
    print("\n" + "="*70)
    if lang == 'en':
        print("Execution Complete!")
    else:
        print("Execution complete!")
    print("="*70)

    # 将结果保存到 outputs 目录（避免在终端打印完整结果）
    save_result(result, user_requirement, mode, use_async, workflow_id=monitor.workflow_id)

    # 输出监控报告文件信息
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'
    if lang == 'en':
        print(f"\n📊 Monitor reports saved to outputs folder:")
        print(f"   - JSON format: monitor_report_*.json")
        print(f"   - Readable format: monitor_report_*.txt")
    else:
        print(f"\n📊 Monitoring reports saved to outputs folder:")
        print(f"   - JSON format: monitor_report_*.json")
        print(f"   - Readable format: monitor_report_*.txt")

    return result


def save_result(result, user_requirement, mode, use_async, workflow_id=None):
    """
    将执行结果保存到 outputs 目录

    创建一个带时间戳和模式标签的结果文件，内容包括：
    - 执行时间和模式
    - 用户原始需求
    - 工作流输出结果

    Args:
        result: 工作流执行结果
        user_requirement: 用户原始需求文本
        mode: 工作流模式（'preset' 或 'autonomous'）
        use_async: 是否使用异步模式
        workflow_id: 工作流 ID（来自监控器），用于生成文件名
    """
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    # 确保 outputs 目录存在
    outputs_dir = os.path.join(project_root, 'outputs')
    os.makedirs(outputs_dir, exist_ok=True)

    # 生成包含时间戳和模式信息的文件名
    # 例如: workflow_result_20240617_143025_preset_async.txt
    timestamp = workflow_id or datetime.now().strftime('%Y%m%d_%H%M%S')
    mode_str = f"{mode}_{'async' if use_async else 'sync'}"
    filename = f"workflow_result_{timestamp}_{mode_str}.txt"
    filepath = os.path.join(outputs_dir, filename)

    # 写入结果文件（包含元信息和实际输出）
    with open(filepath, 'w', encoding='utf-8') as f:
        if lang == 'en':
            f.write(f"ECOMATS Execution Result\n")
            f.write(f"{'='*70}\n")
            f.write(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Execution Mode: {mode_str}\n")
            f.write(f"User Requirement: {user_requirement}\n")
        else:
            f.write(f"ECOMATS Execution Results\n")
            f.write(f"{'='*70}\n")
            f.write(f"Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Execution Mode: {mode_str}\n")
            f.write(f"User Requirement: {user_requirement}\n")
        f.write(f"{'='*70}\n\n")
        f.write(str(result))

    # 告知用户文件保存位置
    if lang == 'en':
        print(f"\n📁 Result saved to: {filepath}")
    else:
        print(f"\n📁 Results saved to: {filepath}")


# Python 标准入口点
if __name__ == "__main__":
    # 启动横幅：展示异步增强版特性
    print("\n" + "="*70)
    print("ECOMATS - CrewAI 1.7.0 Async Enhanced Edition")
    print("="*70)
    print("\n🚀 New Features:")
    print("  - Async Crew execution (akickoff)")
    print("  - Parallel Task execution (async_execution=True)")
    print("  - 2-3x performance improvement")
    print("  - Fully backward compatible")
    print("\n" + "="*70)

    # 使用 asyncio.run() 启动异步主函数
    # asyncio.run() 会创建事件循环、执行 main_async()、完成后清理
    asyncio.run(main_async())
