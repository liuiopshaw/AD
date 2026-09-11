#!/usr/bin/env python3
"""
ECOMATS - Multi-Agent System for Water Treatment Material Design Based on CrewAI

This is the synchronous main program entry point that coordinates multiple AI agents
to design, evaluate, and optimize water treatment materials through a structured workflow.
"""

# ---- 标准库导入 ----
# sys: 用于修改 Python 模块搜索路径，确保项目内的模块能被正确导入
import sys
# os: 用于构建跨平台的文件路径和环境变量操作
import os
# json: 用于解析 Agent 返回的 JSON 格式结果（评估分数、排名等）
import json
# signal: 用于 Windows 兼容性处理——Windows 不支持 SIGHUP 信号
import signal
# time: 用于记录任务执行的时间戳和计算耗时
import time
# dotenv: 从 .env 文件加载 API 密钥等敏感环境变量，避免硬编码
from dotenv import load_dotenv
# CrewAI 核心类：Crew 管理多个 Agent 和 Task；Process 定义执行策略（顺序/层级）
from crewai import Crew, Process
# dashscope: 阿里云 DashScope API（通义千问模型服务），需要在运行时注入 API Key
import dashscope

# ---- 将项目根目录添加到模块搜索路径 ----
# 这样无论从哪个目录运行脚本，都能正确导入 src 和 workflow 等子模块
# os.path.dirname(__file__): 当前文件所在目录 (scripts/)
# os.path.dirname(...) + '..': 上溯到项目根目录 (ECOMATS/)
project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
# 插入到路径列表最前面，确保优先加载项目版本而非系统版本
sys.path.insert(0, os.path.abspath(project_root))

# ---- 导入工作流监控模块 ----
# WorkflowMonitor: 记录每个 Agent 的执行信息、耗时、工具调用等，生成监控报告
# create_monitor/get_monitor: 工厂函数，创建或获取全局监控器实例
from src.utils.workflow_monitor import WorkflowMonitor, create_monitor, get_monitor

# ---- Windows 兼容性补丁 ----
# SIGHUP 信号在 Windows 上不可用，这里创建占位符防止 ImportError
if sys.platform == 'win32':
    if not hasattr(signal, 'SIGHUP'):
        signal.SIGHUP = None  # Windows 不支持 SIGHUP，设为 None 避免 AttributeError
    # 将控制台输出编码设为 UTF-8，避免中文字符在 Windows 终端上显示为乱码
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass  # Python < 3.7 不支持 reconfigure 方法，静默忽略

def get_user_input():
    """
    获取用户自定义的材料设计需求

    交互式地从命令行读取用户想要设计的材料类型和性能要求，
    这是整个多 Agent 工作流的起点——用户需求驱动后续所有任务。

    Returns:
        str: 用户输入的材料设计需求文本
    """
    print("Please enter your material design requirements:")
    print("Example: Design an efficient catalyst for treating cadmium-containing heavy metal wastewater")
    print("Note: The system supports detailed material type classification and structural description requirements")
    # input() 是阻塞调用，等待用户在终端输入
    user_input = input("Material design requirements: ")
    return user_input

def get_workflow_mode():
    """
    获取用户选择的工作流模式

    提供两种执行模式：
    1. preset: 预设流程——按固定顺序执行全部任务（设计→评估→验证→合成→机理→操作建议）
    2. autonomous: Agent 自主调度——由协调 Agent (TOA) 分析意图后动态创建必要任务

    Returns:
        str: 'preset' 或 'autonomous'
    """
    print("\nPlease select workflow mode:")
    print("1. Preset workflow mode (execute all tasks in fixed order)")
    print("2. Agent autonomous scheduling mode (tasks dynamically assigned by coordinator)")
    while True:
        choice = input("Please enter option (1 or 2): ").strip()
        if choice == "1":
            return "preset"
        elif choice == "2":
            return "autonomous"
        else:
            print("Invalid option, please enter 1 or 2")

def check_environment_variables():
    """
    检查必需的环境变量是否已设置

    在启动工作流之前验证 QWEN_API_KEY 和 QWEN_MODEL_NAME 是否已配置，
    避免工作流跑到一半因为缺 API Key 而报错。

    Returns:
        bool: 所有必需变量均已设置返回 True，否则返回 False
    """
    # 延迟导入 Config，确保环境变量已经加载
    from src.config.config import Config
    # 定义必需的环境变量及其当前值
    required_vars = {
        "QWEN_API_KEY": Config.QWEN_API_KEY,
        "QWEN_MODEL_NAME": Config.QWEN_MODEL_NAME
    }

    # 收集所有未设置（值为空）的变量名
    missing_vars = []
    for var_name, var_value in required_vars.items():
        if not var_value:
            missing_vars.append(var_name)

    # 如果有缺失的变量，打印错误提示和配置示例
    if missing_vars:
        print("Error: The following required environment variables are not set:")
        for var in missing_vars:
            print(f"  - {var}")
        print("\nPlease create a .env file in the project root and configure these variables")
        print("Example:")
        print("  QWEN_API_KEY=your_api_key_here")
        print("  QWEN_MODEL_NAME=qwen-max")
        return False

    return True

def create_all_agents(llm):
    """
    创建工作流中使用的所有 Agent 实例

    每个 Agent 对应一个专业角色，由各自的工厂类创建：
    - TaskOrganizingAgent: 任务协调器，分析用户意图并调度任务
    - CreativeDesigningAgent: 材料设计师，根据需求创新性地设计材料方案
    - AssessmentScreeningAgent A/B/C: 三位独立评估专家，从不同角度评分
    - AssessmentScreeningAgentOverall: 综合评估专家，汇总评估结果并给出最终排序
    - ExtractingAgent: 文献信息提取专家
    - MechanismMiningAgent: 机理分析专家，解释材料作用原理
    - SynthesisGuidingAgent: 合成指导专家，给出材料制备方案
    - OperationSuggestingAgent: 操作建议专家，提供实际应用操作指南

    Args:
        llm: 大语言模型实例，所有 Agent 共用同一个 LLM 连接

    Returns:
        dict: Agent 名称到实例的映射字典，方便按名称索引
    """
    # 导入各个 Agent 的工厂类（每个类负责特定专业领域的 Agent 创建）
    from src.agents.task_organizing_agent import TaskOrganizingAgent
    from src.agents.Creative_Designing_agent import CreativeDesigningAgent
    from src.agents.Assessment_Screening_agent_A import AssessmentScreeningAgentA
    from src.agents.Assessment_Screening_agent_B import AssessmentScreeningAgentB
    from src.agents.Assessment_Screening_agent_C import AssessmentScreeningAgentC
    from src.agents.Assessment_Screening_agent_Overall import AssessmentScreeningAgentOverall
    from src.agents.Extracting_agent import ExtractingAgent
    from src.agents.Mechanism_Mining_agent import MechanismMiningAgent
    from src.agents.Synthesis_Guiding_agent import SynthesisGuidingAgent
    from src.agents.Operation_Suggesting_agent import OperationSuggestingAgent
    # 实例化各 Agent——每个 Agent 用自己的角色提示词和工具集
    coordinator_agent = TaskOrganizingAgent(llm).create_agent()
    material_designer_agent = CreativeDesigningAgent(llm).create_agent()
    expert_a_agent = AssessmentScreeningAgentA(llm).create_agent()
    expert_b_agent = AssessmentScreeningAgentB(llm).create_agent()
    expert_c_agent = AssessmentScreeningAgentC(llm).create_agent()
    final_validator_agent = AssessmentScreeningAgentOverall(llm).create_agent()
    literature_processor_agent = ExtractingAgent(llm).create_agent()
    mechanism_expert_agent = MechanismMiningAgent(llm).create_agent()
    synthesis_expert_agent = SynthesisGuidingAgent(llm).create_agent()
    operation_suggesting_agent = OperationSuggestingAgent(llm).create_agent()

    # 以字典形式返回，方便外部通过语义化名称访问
    return {
        'coordinator': coordinator_agent,
        'material_designer': material_designer_agent,
        'expert_a': expert_a_agent,
        'expert_b': expert_b_agent,
        'expert_c': expert_c_agent,
        'final_validator': final_validator_agent,
        'literature_processor': literature_processor_agent,
        'mechanism_expert': mechanism_expert_agent,
        'synthesis_expert': synthesis_expert_agent,
        'operation_suggesting': operation_suggesting_agent
    }

def extract_feedback_from_result(result):
    """
    从任务结果中提取反馈信息，用于迭代改进

    当一轮设计评估不理想时，需要提取评估专家的具体批评和建议，
    将这些信息作为上下文注入下一轮设计迭代，形成闭环优化。

    支持两种反馈来源：
    1. final_validator 的结果（包含 recommendations 和 cons 字段）
    2. 评估专家 A/B/C 的结果（包含 cons 字段，标明发现的问题）

    Args:
        result: 任务执行结果（字符串或字典格式）

    Returns:
        str: 提取到的反馈文本，若解析失败则返回兜底提示
    """
    try:
        # 尝试解析 JSON 格式的结果——如果是字符串，先 JSON 反序列化
        if isinstance(result, str):
            result_data = json.loads(result)
        else:
            result_data = result

        # 遍历结果结构，收集反馈信息
        feedback = ""
        if isinstance(result_data, dict):
            # 情况1: 来自综合评估专家的反馈
            # "results" 是一个列表，每个元素包含对某个材料的评分和建议
            if "results" in result_data and isinstance(result_data["results"], list):
                for item in result_data["results"]:
                    if "recommendations" in item:
                        feedback += f"Recommendations: {item['recommendations']}\n"
                    if "cons" in item:
                        feedback += f"Issues found: {item['cons']}\n"
            # 情况2: 来自单个评估专家的反馈
            # "evaluator" 字段标识是哪个专家 (A/B/C)
            elif "evaluator" in result_data:
                if result_data["evaluator"] in ["A", "B", "C"]:
                    if "results" in result_data and isinstance(result_data["results"], list):
                        for item in result_data["results"]:
                            if "cons" in item:
                                feedback += f"Issues pointed out by evaluator {result_data['evaluator']}: {item['cons']}\n"
        return feedback
    except Exception as e:
        # JSON 解析失败时的兜底处理
        print(f"Error parsing feedback information: {e}")
        return "Unable to extract specific feedback information, please redesign the material solution."

def check_if_iteration_needed(result):
    """
    根据评估分数判断是否需要迭代优化设计方案

    检查两种评估来源的分数：
    1. 综合评估专家 (final_validator) 的 weighted_total 加权总分
    2. 各评估专家 (A/B/C) 的 scores 列表平均值

    如果任何一项评分低于 Config.MIN_ACCEPTABLE_SCORE 阈值，
    或者材料被评为 "Invalid"/"Poor" 等级，则需要重新设计。

    Args:
        result: 评估结果（包含分数和排名）

    Returns:
        bool: 需要迭代返回 True，否则返回 False
    """
    from src.config.config import Config
    try:
        # 解析结果格式
        if isinstance(result, str):
            result_data = json.loads(result)
        else:
            result_data = result

        # 处理综合评估专家的结果
        if isinstance(result_data, dict) and "results" in result_data:
            if isinstance(result_data["results"], list):
                for item in result_data["results"]:
                    if "rank" in item:
                        # 如果排名为 Invalid（无效）或 Poor（差），需要迭代
                        if item["rank"] in ["Invalid", "Poor"]:
                            return True
                        # 如果加权总分低于可接受阈值，需要迭代
                        if "weighted_total" in item and item["weighted_total"] < Config.MIN_ACCEPTABLE_SCORE:
                            return True
            # 处理单个评估专家的结果
            elif "evaluator" in result_data and result_data["evaluator"] in ["A", "B", "C"]:
                if "results" in result_data and isinstance(result_data["results"], list):
                    for item in result_data["results"]:
                        if "scores" in item and isinstance(item["scores"], list):
                            # 计算所有评分的平均值
                            avg_score = sum(item["scores"]) / len(item["scores"]) if item["scores"] else 0
                            if avg_score < Config.MIN_ACCEPTABLE_SCORE:
                                return True
        return False
    except Exception as e:
        print(f"Error checking iteration requirements: {e}")
        return False

def run_design_iteration(user_requirement, llm, iteration_count=0):
    """
    运行迭代式设计流程，直到结果满足要求或达到最大迭代次数

    这是一个递归函数：
    1. 首先检查是否已达最大迭代次数（防止无限循环）
    2. 运行一轮预设工作流，获得设计+评估结果
    3. 检查评估结果是否满足质量要求
    4. 如果不满足：提取反馈信息，将反馈拼接到需求中，递归进入下一轮迭代
    5. 如果满足：返回最终结果

    这种迭代机制实现了"设计-评估-反馈-改进"的闭环优化，
    类似人类材料学家反复实验改进配方的过程。

    Args:
        user_requirement: 用户材料设计需求
        llm: 大语言模型实例
        iteration_count: 当前迭代次数（默认 0）

    Returns:
        str: 最终设计结果或达到最大迭代次数的提示信息
    """
    from src.config.config import Config
    # 递归终止条件：防止无限迭代耗尽 API 配额
    if iteration_count >= Config.MAX_DESIGN_ITERATIONS:
        return "Maximum iterations reached, stopping iterative design."

    print(f"Starting design iteration {iteration_count + 1}...")

    # 运行一轮完整的预设工作流（设计→评估→验证→合成→机理→操作建议）
    result = run_preset_workflow(user_requirement, llm)

    # 检查本轮结果是否需要继续迭代优化
    if check_if_iteration_needed(result):
        print("Current design does not meet requirements, iterative optimization needed...")
        # 从评估结果中提取具体的改进点和批评意见
        feedback = extract_feedback_from_result(result)
        if feedback:
            # 将反馈信息作为改进建议追加到原始需求中
            # 这样设计 Agent 在下一轮可以看到之前的问题并针对性改进
            updated_requirement = f"{user_requirement}\n\nImprovement suggestions based on previous evaluation: {feedback}"
            # 递归调用，进入下一轮迭代（iteration_count + 1）
            return run_design_iteration(updated_requirement, llm, iteration_count + 1)
        else:
            # 如果无法提取反馈，直接返回当前结果（没有改进线索，停止迭代）
            return result
    else:
        # 结果满足要求，返回最终结果
        return result

def run_preset_workflow(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    运行预设工作流模式，按固定序列执行任务

    此模式按预定义顺序执行全部任务：
    1. 材料设计 (CreativeDesigningAgent)
    2. 评估 (3 位专家并行: A/B/C)
    3. 最终验证 (AssessmentScreeningAgentOverall)
    4. 合成方法 (SynthesisGuidingAgent)
    5. 机理分析 (MechanismMiningAgent)
    6. 操作建议 (OperationSuggestingAgent)

    CrewAI 的 Process.sequential 保证任务按依赖关系依次执行，
    而依赖同一任务的任务（如三个评估任务都依赖设计任务）可以并行执行。

    Args:
        user_requirement: 用户的材料设计需求
        llm: 大语言模型实例
        monitor: 工作流监控器实例（可选），用于记录执行过程

    Returns:
        Crew 执行结果
    """
    print("Starting preset workflow mode...")
    # 确保项目路径在搜索路径中（防御性编码）
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    sys.path.insert(0, os.path.abspath(project_root))
    # 导入配置和任务工厂类
    from src.config.config import Config
    from src.tasks.design_task import DesignTask
    from src.tasks.evaluation_task import EvaluationTask
    from src.tasks.final_validation_task import FinalValidationTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.synthesis_method_task import SynthesisMethodTask
    from src.tasks.operation_suggesting_task import OperationSuggestingTask

    # 如果未提供监控器，创建一个默认的
    if monitor is None:
        monitor = create_monitor()

    # 设置监控器的工作流基本信息（需求文本、模式、是否异步）
    monitor.set_workflow_info(user_requirement, "preset", is_async=False)

    # 创建所有 Agent 实例
    agents = create_all_agents(llm)

    # ---- 创建任务及其依赖关系 ----
    # 每个任务通过 context_task 参数指定其依赖的前置任务
    # CrewAI 根据这些依赖自动处理执行顺序

    # 1. 首先创建材料设计任务（无前置依赖，是工作流的起点）
    design_task = DesignTask(llm).create_task(agents['material_designer'], user_requirement=user_requirement)

    # 工具由 Agent 按需调用，并通过 ContextStore 缓存结果
    # 已移除预执行逻辑以避免冗余

    # 2. 为三位评估专家创建评估任务，均依赖设计任务
    # 三个评估任务共享同一个设计任务作为上下文，CrewAI 会在设计完成后并行调度它们
    # 显式传递 user_requirement 确保工具调用策略能正确执行
    evaluation_task_a = EvaluationTask(llm).create_task(agents['expert_a'], design_task, user_requirement=user_requirement)
    evaluation_task_b = EvaluationTask(llm).create_task(agents['expert_b'], design_task, user_requirement=user_requirement)
    evaluation_task_c = EvaluationTask(llm).create_task(agents['expert_c'], design_task, user_requirement=user_requirement)

    # 3. 创建最终验证任务——综合分析设计结果和三位专家的评估意见
    # context 是一个列表，包含设计任务和三个评估任务，CrewAI 会等全部完成后才执行此任务
    final_validation_task = FinalValidationTask(llm).create_task(agents['final_validator'],
                                                           [design_task, evaluation_task_a, evaluation_task_b, evaluation_task_c], user_requirement=user_requirement)

    # 4. 创建合成方法任务——为材料制备提供工艺指南
    synthesis_method_task = SynthesisMethodTask(llm).create_task(agents['synthesis_expert'], final_validation_task, user_requirement=user_requirement)

    # 5. 创建机理分析任务——深入分析材料的微观作用原理
    mechanism_analysis_task = MechanismAnalysisTask(llm).create_task(agents['mechanism_expert'], final_validation_task, user_requirement=user_requirement)

    # 6. 创建操作建议任务——提供实际应用中的操作指南
    operation_suggesting_task = OperationSuggestingTask(llm).create_task(agents['operation_suggesting'], final_validation_task, user_requirement=user_requirement)

    # ---- 创建任务-Agent 映射表，用于回调跟踪 ----
    # 每个元组包含：(任务, Agent, 角色名称)
    task_agent_map = [
        (design_task, agents['material_designer'], 'Creative_Designing_agent'),
        (evaluation_task_a, agents['expert_a'], 'Assessment_Screening_agent_A'),
        (evaluation_task_b, agents['expert_b'], 'Assessment_Screening_agent_B'),
        (evaluation_task_c, agents['expert_c'], 'Assessment_Screening_agent_C'),
        (final_validation_task, agents['final_validator'], 'Assessment_Screening_agent_Overall'),
        (synthesis_method_task, agents['synthesis_expert'], 'Synthesis_Guiding_agent'),
        (mechanism_analysis_task, agents['mechanism_expert'], 'Mechanism_Mining_agent'),
        (operation_suggesting_task, agents['operation_suggesting'], 'Operation_Suggesting_agent'),
    ]

    # 创建从任务描述到 Agent 的快速查找字典
    # key: 任务描述的前 100 个字符（用作简化的唯一标识）
    # value: (Agent 实例, 角色名称) 元组
    task_desc_to_agent = {}
    for task, agent, role_name in task_agent_map:
        desc_key = str(task.description)[:100]  # 取描述前 100 字符作为键，避免因完整描述变动导致匹配失败
        task_desc_to_agent[desc_key] = (agent, role_name)

    # ---- 创建全局时间戳，用于生成输出文件名 ----
    import datetime
    global_workflow_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # ---- 跟踪变量初始化 ----
    task_start_times = {}        # 记录每个任务的开始时间
    task_completion_order = []   # 按完成顺序记录任务名称
    last_task_end_time = time.time()  # 上一个任务结束的时间，用于计算当前任务的等待/运行时长

    def task_callback(task_output):
        """
        任务完成时的回调函数

        每个任务执行完毕后由 CrewAI 自动调用，完成以下工作：
        1. 计算任务耗时（相对于上一个任务结束的时间）
        2. 将执行结果写入 outputs/ 目录下的日志文件
        3. 通知监控器更新执行状态

        CrewAI 的 task_callback 机制是同步回调——任务完成即触发，
        因此在 sequential 模式下，回调顺序与任务完成顺序一致。
        """
        nonlocal last_task_end_time  # 修改外部闭包变量
        import json
        import os

        # 确保 outputs 输出目录存在
        outputs_dir = os.path.join(project_root, "outputs")
        os.makedirs(outputs_dir, exist_ok=True)

        # 构建输出文件路径（同一个工作流的所有任务写入同一个文件）
        workflow_result_filename = f"workflow_result_{global_workflow_timestamp}.txt"
        workflow_result_filepath = os.path.join(outputs_dir, workflow_result_filename)

        # 从 task_output 中提取任务描述和名称
        task_description = getattr(task_output, 'description', 'N/A')
        task_name_raw = getattr(task_output, 'name', None)

        # 用描述的前 100 字符作为键，查找是哪个 Agent 执行的任务
        desc_key = str(task_description)[:100]
        agent_info = task_desc_to_agent.get(desc_key)

        if agent_info:
            agent, agent_role = agent_info
            agent_name = getattr(agent, 'name', agent_role)
        else:
            # 如果在映射表中找不到，从 TaskOutput 对象中获取 Agent 信息
            agent = getattr(task_output, 'agent', None)
            agent_name = getattr(agent, 'name', 'Unknown') if agent else 'Unknown'
            agent_role = getattr(agent, 'role', 'Unknown') if agent else 'Unknown'

        # 生成任务序号和名称
        task_idx = len(task_completion_order) + 1
        task_name = task_name_raw or f"Task_{task_idx}_{agent_role}"
        task_completion_order.append(task_name)

        # 尝试提取 JSON 格式的结构化输出（如评估分数等）
        json_output = None
        if hasattr(task_output, 'json_dict') and task_output.json_dict:
            json_output = task_output.json_dict

        # 计算任务执行耗时
        current_time = time.time()
        task_start_time = last_task_end_time
        task_duration = current_time - task_start_time

        # 将执行信息汇报给监控器
        if monitor:
            monitor.start_agent_execution(agent_name, agent_role, task_name, str(task_description)[:200])
            if monitor._current_execution:
                monitor._current_execution.start_time = task_start_time
            monitor.end_agent_execution(output=str(task_output)[:5000], json_output=json_output)

        # 更新最后完成任务的时间，供下一个任务计算耗时
        last_task_end_time = current_time

        # 将任务结果追加写入输出文件（以追加模式，保留之前任务的内容）
        with open(workflow_result_filepath, 'a', encoding='utf-8') as f:
            f.write(f"\n\n{'='*60}\n")
            f.write(f"Task Name: {task_name}\n")
            f.write(f"Agent: {agent_role}\n")
            f.write(f"Execution Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Duration: {task_duration:.2f}s ({task_duration/60:.1f}min)\n")
            f.write("=" * 60 + "\n")
            f.write(f"Task Description: {str(task_description)[:500]}\n")
            f.write(f"Expected Output: {getattr(task_output, 'expected_output', 'N/A')}\n")
            f.write("=" * 60 + "\n")
            f.write(f"Actual Output:\n{str(task_output)}\n")

            if json_output:
                f.write("\n" + "=" * 60 + "\n")
                f.write("JSON Output:\n")
                # ensure_ascii=False 确保中文字符不转义为 Unicode 编码
                json.dump(json_output, f, ensure_ascii=False, indent=2)
            f.write(f"\n{'='*60}\n")

    # ---- 创建 Crew 实例，注册所有 Agent 和 Task ----
    # Crew 是 CrewAI 的核心调度器，负责按依赖关系和 Process 策略调度任务执行
    ecomats_crew = Crew(
        agents=[
            # 列出所有 Agent（包括可能不直接执行任务但提供支持的 Agent）
            agents['coordinator'],
            agents['material_designer'],
            agents['expert_a'],
            agents['expert_b'],
            agents['expert_c'],
            agents['final_validator'],
            agents['literature_processor'],
            agents['mechanism_expert'],
            agents['synthesis_expert'],
            agents['operation_suggesting']
        ],
        tasks=[
            # 任务按执行顺序排列——CrewAI 根据 context 依赖自动推断实际顺序
            design_task,
            evaluation_task_a,
            evaluation_task_b,
            evaluation_task_c,
            final_validation_task,
            synthesis_method_task,
            mechanism_analysis_task,
            operation_suggesting_task
        ],  # 任务按顺序执行——依赖同一前置任务的可并行
        process=Process.sequential,  # 顺序执行模式：完成一个任务再开始下一个
        verbose=Config.VERBOSE,       # 从配置读取详细输出设置
        task_callback=task_callback   # 每个任务完成时触发的回调，用于记录和监控
    )

    # ---- 执行工作流 ----
    try:
        # kickoff() 是 CrewAI 的入口方法，启动整个工作流
        # CrewAI 内部会根据 task 的 context 依赖关系和 Process 策略自动调度
        result = ecomats_crew.kickoff()

        # 执行成功后，通知监控器记录最终状态并保存报告
        if monitor:
            monitor.set_final_result(result, "completed")
            monitor.save_report()          # 保存 JSON 格式的监控报告
            monitor.save_readable_report() # 保存可读文本格式的监控报告
            monitor.print_summary()        # 在终端打印执行摘要

        return result
    except Exception as e:
        # 执行失败时同样记录错误状态，然后执行仅工具调用的兜底方案
        if monitor:
            monitor.set_final_result(None, "error", str(e))
            monitor.save_report()
            monitor.save_readable_report()
        return run_tool_only_summary(user_requirement)

def _execute_material_tools(user_requirement: str, project_root: str):
    """
    已废弃: 预执行材料相关工具调用

    此函数已不再使用。Agent 现在按需自行调用工具，并通过 ContextStore 缓存结果。

    保留此函数是为了向后兼容，确保旧代码引用不会报错。
    """
    pass  # 不再预执行工具调用

def run_autonomous_workflow(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    运行 Agent 自主调度模式：基于 TOA 意图识别动态创建任务

    与预设模式不同，此模式不是死板地执行全部任务，而是：
    1. 由 TOA (Task Organizing Agent) 分析用户意图
    2. 根据意图只创建必要的任务（例如用户只问机理分析，就不创建设计任务）
    3. 动态组合需要的 Agent 和 Task

    这避免了不需要的任务浪费 token 和时间，同时保持了灵活性。

    Args:
        user_requirement: 用户材料设计需求
        llm: 大语言模型实例
        monitor: 工作流监控器实例（可选）

    Returns:
        Crew 执行结果
    """
    print("Starting autonomous scheduling mode...")
    # 确保项目路径在搜索路径中
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    sys.path.insert(0, os.path.abspath(project_root))
    # 导入必要的模块
    from src.config.config import Config
    from src.agents.task_organizing_agent import TaskOrganizingAgent
    from src.tasks.design_task import DesignTask
    from src.tasks.evaluation_task import EvaluationTask
    from src.tasks.final_validation_task import FinalValidationTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.synthesis_method_task import SynthesisMethodTask
    from src.tasks.operation_suggesting_task import OperationSuggestingTask
    from crewai import Task  # 用于创建虚拟上下文任务

    # 创建所有 Agent 实例
    agents = create_all_agents(llm)

    # ---- 创建任务协调 Agent (TOA) ----
    # TOA 是整个自主调度模式的核心：负责分析意图并分配任务
    coordinator = TaskOrganizingAgent(llm)
    coordinator_agent = coordinator.create_agent()

    # 将每种类型的 Agent 注册到 TOA 的注册表中
    # TOA 通过这个注册表知道有哪些 Agent 可用以及它们各自的能力
    coordinator.register_agent("TaskOrganizingAgent", coordinator_agent)
    coordinator.register_agent("CreativeDesigningAgent", agents['material_designer'])
    # 评估专家是一个组（A/B/C 三位），作为列表注册
    coordinator.register_agent("AssessmentScreeningAgent", [agents['expert_a'], agents['expert_b'], agents['expert_c']])
    coordinator.register_agent("AssessmentScreeningAgentOverall", agents['final_validator'])
    coordinator.register_agent("ExtractingAgent", agents['literature_processor'])
    coordinator.register_agent("MechanismMiningAgent", agents['mechanism_expert'])
    coordinator.register_agent("SynthesisGuidingAgent", agents['synthesis_expert'])
    coordinator.register_agent("OperationSuggestingAgent", agents['operation_suggesting'])

    # 初始化监控器
    if monitor is None:
        monitor = create_monitor()
    monitor.set_workflow_info(user_requirement, "autonomous", is_async=False)

    # ============================================================
    # TOA 意图驱动工作流：分析用户意图
    # ============================================================
    # TOA 通过 LLM 分析用户输入，判断需要哪些步骤：
    #   needs_design: 是否需要设计新材料
    #   needs_evaluation: 是否需要评估/筛选
    #   evaluation_mode: 'experts_only'（仅三位专家评分）或 'with_summary'（含综合汇总）
    #   needs_mechanism: 是否需要机理分析
    #   needs_synthesis: 是否需要合成方法指导
    #   needs_operation: 是否需要操作建议
    #   material_provided: 用户是否已经提供了材料信息（如果有则跳过设计）
    print("\n🧠 TOA analyzing user intent...")
    intent = coordinator.analyze_user_intent(user_requirement)
    print(f"✅ Intent analysis complete: {intent['reasoning']}")

    # 打印意图分析的详细结果，便于调试和用户了解系统决策
    print(f"\n📊 Intent Details:")
    print(f"   • Needs Design: {intent.get('needs_design', False)}")
    print(f"   • Needs Evaluation: {intent.get('needs_evaluation', False)}")
    print(f"   • Evaluation Mode: {intent.get('evaluation_mode', None)}")
    print(f"   • Needs Mechanism: {intent.get('needs_mechanism', False)}")
    print(f"   • Needs Synthesis: {intent.get('needs_synthesis', False)}")
    print(f"   • Needs Operation: {intent.get('needs_operation', False)}")
    print(f"   • Material Provided: {intent.get('material_provided', None)}")

    # ---- 初始化任务和 Agent 列表 ----
    required_tasks = []     # 根据意图动态收集需要执行的任务
    required_agents = []    # 根据意图动态收集需要的 Agent
    seen_roles = set()      # 用于去重：确保同一个 Agent 角色只添加一次
    design_task = None      # 设计任务引用（可能是实际任务或虚拟上下文任务）
    final_validation_task = None  # 最终验证任务引用

    # ============================================================
    # Step 1: 处理材料设计需求
    # ============================================================
    if intent.get('needs_design', False):
        # 用户需要新材料设计：创建完整的设计任务
        print("\n🛠️ Creating material design task...")
        design_agent = coordinator.get_agent_for_task("material_design")
        if design_agent and design_agent.role not in seen_roles:
            required_agents.append(design_agent)
            seen_roles.add(design_agent.role)

        design_task = DesignTask(llm).create_task(design_agent, user_requirement=user_requirement)
        required_tasks.append(design_task)

        # 工具由 Agent 按需调用，通过 ContextStore 缓存

    elif intent.get('needs_evaluation', False) or intent.get('needs_mechanism', False) or intent.get('needs_synthesis', False) or intent.get('needs_operation', False):
        # 用户提供了材料信息，不需要新设计——创建虚拟上下文任务用于传递材料信息
        # 这个任务不会被实际执行（不加入 required_tasks），但作为下游任务的 context 依赖
        material_info = intent.get('material_provided') or user_requirement
        print(f"\n📝 Using user-provided material info: {material_info[:50]}...")

        # 创建虚拟上下文任务——只用于传递材料信息给下游任务
        # agent 设为 coordinator_agent 占位（虚拟任务不会被实际分派执行）
        design_task = Task(
            description=f"Existing material provided by user:\n{user_requirement}",
            expected_output="Material information for downstream tasks",
            agent=coordinator_agent  # 使用协调器作为占位 Agent
        )
        # 注意: 虚拟任务不加入 required_tasks 列表

    # ============================================================
    # Step 2: 处理评估任务
    # ============================================================
    if intent.get('needs_evaluation', False):
        evaluation_mode = intent.get('evaluation_mode', 'with_summary')

        # 获取所有评估专家 Agent (A, B, C 三位)
        evaluation_agents = coordinator.get_all_agents_for_task("evaluation")
        evaluation_tasks = []

        for agent in evaluation_agents:
            if agent.role not in seen_roles:
                required_agents.append(agent)
                seen_roles.add(agent.role)
            # 创建评估任务，依赖设计任务（或虚拟上下文任务）
            task = EvaluationTask(llm).create_task(agent, design_task, user_requirement)
            evaluation_tasks.append(task)

        required_tasks.extend(evaluation_tasks)

        if evaluation_mode == 'experts_only':
            # 仅专家评分模式：三位 ASA 专家独立打分，不需要综合汇总
            print(f"\n✅ Experts-only mode: 3 ASA experts scoring, no final summary")
            print(f"   Experts-only mode: 3 ASA experts scoring, no final summary")
        else:
            # 完整评估模式（含综合汇总）
            print(f"\n📊 Full evaluation mode: 3 ASA experts + final summary")
            print(f"   Full evaluation mode: 3 ASA experts + final summary")

            # 获取综合评估 Agent
            final_validation_agent = coordinator.get_agent_for_task("final_validation")
            if final_validation_agent and final_validation_agent.role not in seen_roles:
                required_agents.append(final_validation_agent)
                seen_roles.add(final_validation_agent.role)

            # 创建最终验证任务，其 context 包含设计任务和所有评估任务的汇总
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
        print(f"\n🔬 Creating mechanism analysis task...")
        mechanism_agent = coordinator.get_agent_for_task("mechanism_analysis")
        if mechanism_agent and mechanism_agent.role not in seen_roles:
            required_agents.append(mechanism_agent)
            seen_roles.add(mechanism_agent.role)

        # 机理分析依赖最终验证结果；如果没有综合评估，则依赖设计任务
        context_task = final_validation_task or design_task
        mechanism_task = MechanismAnalysisTask(llm).create_task(
            mechanism_agent, context_task, user_requirement=user_requirement
        )
        required_tasks.append(mechanism_task)

    # ============================================================
    # Step 4: 处理合成方法任务
    # ============================================================
    if intent.get('needs_synthesis', False):
        print(f"\n🧪 Creating synthesis method task...")
        synthesis_agent = coordinator.get_agent_for_task("synthesis_method")
        if synthesis_agent and synthesis_agent.role not in seen_roles:
            required_agents.append(synthesis_agent)
            seen_roles.add(synthesis_agent.role)

        # 合成方法同样依赖最终验证结果或设计任务
        context_task = final_validation_task or design_task
        synthesis_task = SynthesisMethodTask(llm).create_task(
            synthesis_agent, context_task, user_requirement=user_requirement
        )
        required_tasks.append(synthesis_task)

    # ============================================================
    # Step 5: 处理操作建议任务
    # ============================================================
    if intent.get('needs_operation', False):
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
        # TOA 无法识别任何意图时的兜底策略：默认创建材料设计任务
        print("\n⚠️ No tasks identified, defaulting to material design")
        design_agent = coordinator.get_agent_for_task("material_design")
        if design_agent and design_agent.role not in seen_roles:
            required_agents.append(design_agent)
            seen_roles.add(design_agent.role)
        design_task = DesignTask(llm).create_task(design_agent, user_requirement=user_requirement)
        required_tasks.append(design_task)

    # ============================================================
    # 打印任务摘要，让用户了解系统将执行哪些步骤
    # ============================================================
    print(f"\n{'='*60}")
    print(f"📝 Task Summary")
    print(f"{'='*60}")
    print(f"   Total tasks: {len(required_tasks)}")
    print(f"   Total agents: {len(required_agents)}")
    for i, task in enumerate(required_tasks, 1):
        agent_role = getattr(task.agent, 'role', 'Unknown') if task.agent else 'None'
        print(f"   {i}. {agent_role}")
    print(f"{'='*60}\n")

    # ---- 创建任务描述到 Agent 的映射（用于回调中识别 Agent） ----
    task_desc_to_agent = {}
    for task in required_tasks:
        if task and task.agent:
            desc_key = str(task.description)[:100]
            task_desc_to_agent[desc_key] = (task.agent, getattr(task.agent, 'role', 'Unknown'))

    # ---- 创建全局时间戳和跟踪变量 ----
    import datetime
    global_workflow_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    task_start_times = {}
    task_completion_order = []
    last_task_end_time = time.time()

    def task_callback(task_output):
        """
        任务完成回调——与预设工作流中的回调逻辑完全相同。
        负责记录每个任务的输出、耗时，并更新监控器。
        各任务的结果会追加写入同一个输出文件。
        """
        nonlocal last_task_end_time
        import json
        import os

        # 确保 outputs 目录存在
        outputs_dir = os.path.join(project_root, "outputs")
        os.makedirs(outputs_dir, exist_ok=True)

        workflow_result_filename = f"workflow_result_{global_workflow_timestamp}.txt"
        workflow_result_filepath = os.path.join(outputs_dir, workflow_result_filename)

        task_description = getattr(task_output, 'description', 'N/A')
        task_name_raw = getattr(task_output, 'name', None)

        desc_key = str(task_description)[:100]
        agent_info = task_desc_to_agent.get(desc_key)

        if agent_info:
            agent, agent_role = agent_info
            agent_name = getattr(agent, 'name', agent_role)
        else:
            # 从 TaskOutput 中获取 Agent 信息
            agent = getattr(task_output, 'agent', None)
            agent_name = getattr(agent, 'name', 'Unknown') if agent else 'Unknown'
            agent_role = getattr(agent, 'role', 'Unknown') if agent else 'Unknown'

        task_idx = len(task_completion_order) + 1
        task_name = task_name_raw or f"Task_{task_idx}_{agent_role}"
        task_completion_order.append(task_name)

        # 提取 JSON 结构化输出
        json_output = None
        if hasattr(task_output, 'json_dict') and task_output.json_dict:
            json_output = task_output.json_dict

        # 计算任务耗时
        current_time = time.time()
        task_start_time = last_task_end_time
        task_duration = current_time - task_start_time

        # 更新监控器
        if monitor:
            monitor.start_agent_execution(agent_name, agent_role, task_name, str(task_description)[:200])
            if monitor._current_execution:
                monitor._current_execution.start_time = task_start_time
            monitor.end_agent_execution(output=str(task_output)[:5000], json_output=json_output)

        last_task_end_time = current_time

        # 追加写入输出文件
        with open(workflow_result_filepath, 'a', encoding='utf-8') as f:
            f.write(f"\n\n{'='*60}\n")
            f.write(f"Task Name: {task_name}\n")
            f.write(f"Agent: {agent_role}\n")
            f.write(f"Execution Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Duration: {task_duration:.2f}s ({task_duration/60:.1f}min)\n")
            f.write("=" * 60 + "\n")
            f.write(f"Task Description: {str(task_description)[:500]}\n")
            f.write(f"Expected Output: {getattr(task_output, 'expected_output', 'N/A')}\n")
            f.write("=" * 60 + "\n")
            f.write(f"Actual Output:\n{str(task_output)}\n")

            if json_output:
                f.write("\n" + "=" * 60 + "\n")
                f.write("JSON Output:\n")
                json.dump(json_output, f, ensure_ascii=False, indent=2)
            f.write(f"\n{'='*60}\n")

    # ---- 创建 Crew 实例 ----
    # 根据意图驱动选择的任务和 Agent 动态构建 Crew
    all_tasks = required_tasks
    if design_task and intent.get('needs_design', False):
        # 如果需要设计，design_task 已经在 Step 1 中加入了 required_tasks
        all_tasks = required_tasks
    elif design_task:
        # 虚拟上下文任务不加入任务列表（不会被实际执行）
        all_tasks = required_tasks

    ecomats_crew = Crew(
        agents=required_agents,      # 只包含根据意图选择的 Agent
        tasks=all_tasks,             # 只包含根据意图选择的任务
        process=Process.sequential,  # 顺序执行模式
        verbose=Config.VERBOSE,
        task_callback=task_callback
    )

    # ---- 执行工作流 ----
    try:
        result = ecomats_crew.kickoff()

        if monitor:
            monitor.set_final_result(result, "completed")
            monitor.save_report()
            monitor.save_readable_report()
            monitor.print_summary()

        return result
    except Exception as e:
        if monitor:
            monitor.set_final_result(None, "error", str(e))
            monitor.save_report()
            monitor.save_readable_report()
        # 如果 Crew 执行失败，回退到仅工具调用模式
        return run_tool_only_summary(user_requirement)

def main():
    """
    同步模式的主入口函数

    完整的启动流程：
    1. 加载环境变量（API Key 等）
    2. 检查必需的环境变量是否已配置
    3. 获取用户输入的材料设计需求
    4. 让用户选择工作流模式（预置或自主调度）
    5. 验证 API Key 有效性
    6. 设置 DashScope API Key 和 OpenAI 兼容环境变量
    7. 创建 LLM 实例
    8. 创建监控器
    9. 根据选择的工作流模式执行相应流程
    """
    print("ECOMATS Multi-Agent System Based on CrewAI")
    print("=" * 50)
    # 计算项目根目录路径
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    sys.path.insert(0, os.path.abspath(project_root))
    # 强制从项目根目录加载 .env 文件（覆盖系统环境变量），确保与独立测试行为一致
    from dotenv import load_dotenv, dotenv_values
    import os as _os
    _dotenv_path = os.path.join(project_root, '.env')
    # override=True: 即使系统环境变量中有同名变量，也用 .env 中的值覆盖
    load_dotenv(_dotenv_path, override=True)
    # 再次将 .env 中的值写入 os.environ，避免 IDE 或任务运行器覆盖环境变量
    try:
        _vals = dotenv_values(_dotenv_path)
        for k, v in (_vals or {}).items():
            if v is not None:
                _os.environ[k] = v
    except Exception:
        pass  # 如果读取 .env 失败（文件不存在等），静默忽略
    from src.config.config import Config

    # 检查必需的环境变量
    if not check_environment_variables():
        return

    # 获取用户输入的材料设计需求
    user_requirement = get_user_input()

    # 获取用户选择的工作流模式
    workflow_mode = get_workflow_mode()

    # 验证 API Key（检查格式有效性）
    if not Config.is_api_key_valid(Config.QWEN_API_KEY):
        print("Error: API key not set correctly")
        return

    # 设置 DashScope API Key
    dashscope.api_key = Config.QWEN_API_KEY
    # 显式设置 OpenAI 兼容环境变量，确保底层 Provider 不会读到过时的值
    # CrewAI 内部可能使用 OpenAI SDK 兼容的配置
    import os as _os
    _os.environ["OPENAI_API_KEY"] = Config.QWEN_API_KEY or ""
    _os.environ["OPENAI_API_BASE"] = Config.QWEN_API_BASE or ""
    _os.environ["OPENAI_BASE_URL"] = Config.QWEN_API_BASE or ""

    # 创建 LLM 实例（根据配置选择 Qwen 模型）
    from src.utils.llm_config import create_llm
    llm = create_llm()
    print("Successfully created Qwen3 LLM instance for main program")

    # 创建监控器用于跟踪工作流执行全过程
    monitor = create_monitor()
    print("📊 Workflow monitor initialized")

    # 根据用户选择的工作流模式执行相应流程
    if workflow_mode == "preset":
        # 预设模式：在迭代循环中运行（支持自动反馈优化）
        run_design_iteration(user_requirement, llm)
    else:
        # 自主调度模式：由 TOA 分析意图后动态创建任务
        run_autonomous_workflow(user_requirement, llm, monitor)

    # 工作流结果和监控报告已通过 task_callback 保存到 outputs 目录
    print("\nWorkflow execution completed, results saved to outputs folder")
    print("📊 Monitoring reports include: JSON format (monitor_report_*.json) and readable format (monitor_report_*.txt)")

def run_tool_only_summary(user_requirement):
    """
    Crew 执行失败时的兜底函数：仅执行必须的工具调用

    当整个 Crew 工作流因为某种原因失败时（如 LLM 超时、网络错误等），
    此函数作为降级方案，跳过 Agent 评估流程，直接调用底层工具获取数据。

    Args:
        user_requirement: 用户需求文本，其中包含材料化学式

    Returns:
        dict: 工具执行结果
    """
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    sys.path.insert(0, os.path.abspath(project_root))
    # 使用评估工具执行器直接调用底层计算工具
    from src.utils.assessment_tool_executor import AssessmentToolExecutor
    executor = AssessmentToolExecutor()
    # 尝试从用户输入中提取材料化学式（如 NiFe2O4、ZnO 等）
    import re as _re
    m = _re.search(r"\b(?:[A-Z][a-z]?\d*){2,}\b", user_requirement or "")
    material_formula = m.group(0) if m else (user_requirement or "")
    # 执行必须的工具调用（计算材料性质等）
    results = executor.execute_mandatory_tool_calls(material_formula)
    # 将结果保存到 outputs 目录
    import datetime, json
    outputs_dir = os.path.join(project_root, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fp = os.path.join(outputs_dir, f"workflow_result_{ts}.txt")
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(json.dumps(results, ensure_ascii=False, indent=2))
    print("Switched to tool-only execution mode, results saved to", fp)
    return results

# Python 标准入口点：当通过 python main.py 直接运行时执行 main()
if __name__ == "__main__":
    main()
