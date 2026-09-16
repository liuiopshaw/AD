#!/usr/bin/env python3
"""
ECOMATS - CrewAI 1.7.0 Async Version

Supports async Crew execution with 2-3x performance improvement through:
- Parallel task execution (evaluation agents run simultaneously)
- Async crew kickoff (akickoff)
- Memory system with DashScope embeddings
"""

# ---- Standard library and third-party library imports ----
# sys: modify the Python module search path
import sys
# os: environment variable operations and file path construction
import os
# json: parse and serialize JSON data
import json
# asyncio: Python's native async programming support — the core dependency of async mode
import asyncio
# datetime: generate timestamps for output files
from datetime import datetime
# dotenv: load environment variables from the .env file
from dotenv import load_dotenv

# ---- Add the project root directory to the module search path ----
# This must be done before importing other project modules, otherwise subsequent imports will fail
# os.path.dirname(__file__): directory containing the current file (scripts/)
# os.path.dirname(...) + '..': go back up to the project root (ECOMATS/)
project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.abspath(project_root))

# ---- Load environment variables before importing CrewAI ----
# This step is critical: CrewAI reads environment variables such as OPENAI_API_KEY
# during initialization, so QWEN_API_KEY from .env must be mapped to
# OpenAI-compatible variable names beforehand
load_dotenv()

# ---- Set OpenAI-compatible environment variables (required for CrewAI async mode) ----
# CrewAI 1.7.0's async mode still uses the OpenAI SDK-compatible protocol under the hood,
# so the DashScope Key and Base URL must be mapped to OpenAI environment variable names
_api_key = os.getenv('QWEN_API_KEY') or 'dummy'  # default to 'dummy' to prevent errors from empty values
_api_base = os.getenv('QWEN_API_BASE') or 'https://dashscope.aliyuncs.com/compatible-mode/v1'
# Set three OpenAI-compatible variables — different provider implementations may read different variable names
os.environ['OPENAI_API_KEY'] = _api_key
os.environ['OPENAI_API_BASE'] = _api_base
os.environ['OPENAI_BASE_URL'] = _api_base

# ---- Apply CrewAI compatibility patches (must be done before importing CrewAI) ----
# The patches module fixes ChromaDB compatibility issues in CrewAI 1.7.0's async memory system
from workflow.patches import apply_crewai_patches
apply_crewai_patches()

# ---- Import CrewAI core classes ----
from crewai import Crew, Process

# ---- Set up unified logging ----
# Configure the global log format and output target to ensure consistent logging behavior across all modules
from src.utils.logging_config import setup_logging
setup_logging()

# ---- Import project core modules ----
from src.config.config import Config                     # Global configuration (API Key, model name, thresholds, etc.)
from src.utils.llm_config import create_llm               # LLM instance factory function
from src.utils.workflow_monitor import WorkflowMonitor, create_monitor, get_monitor  # Workflow monitoring

# ---- Import modular components ----
# embeddings: DashScope text embedding functionality (for semantic search in the CrewAI memory system)
from workflow.embeddings import create_dashscope_embedder
# callback_factory: task callback factory function (supports time tracking for parallel tasks)
from workflow.callback_factory import create_task_callback_factory


def get_ui_text(key):
    """
    Get user interface text (multi-language support)

    Retrieve the UI text for the corresponding language based on the Config.LANGUAGE setting.
    This implements internationalization of the interface text; users can choose Chinese or English at startup.

    Args:
        key: Key name of the UI text

    Returns:
        str: The text in the corresponding language; falls back to the key itself if not found
    """
    try:
        from src.locales.texts import TEXTS
        # Read the language setting, defaulting to Chinese 'zh'
        lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'
        # Look up in the TEXTS dictionary: language -> 'ui' -> key
        return TEXTS.get(lang, TEXTS['zh'])['ui'].get(key, key)
    except Exception:
        # Catch all exceptions to ensure the program can continue even if UI text retrieval fails
        return key


def select_language():
    """
    Interactive language selection (Chinese/English)

    The user first selects the interface language after starting the program. The selection is synced to:
    - Config.LANGUAGE: for other modules to read
    - set_language(): updates the global language context

    Returns:
        str: The selected language code 'zh' (Chinese) or 'en' (English)
    """
    from src.locales import set_language

    # Print the language selection menu
    print("\n" + "="*70)
    print("🌐 Select Language")
    print("="*70)
    print("1. Chinese")
    print("2. English")

    while True:
        choice = input("\nPlease select (1-2): ").strip()
        if choice == "1":
            # Set to Chinese
            set_language("zh")
            Config.LANGUAGE = "zh"
            print("✅ Selected: Chinese")
            return "zh"
        elif choice == "2":
            # Set to English
            set_language("en")
            Config.LANGUAGE = "en"
            print("✅ English selected")
            return "en"
        print("Invalid option")


def get_user_input():
    """
    Get the user's material design requirements (bilingual prompts)

    Display prompts in different languages based on the current language setting.
    The Chinese and English prompts have the same content, only translated differently.

    Returns:
        str: The material design requirement text entered by the user
    """
    # Read the current language setting
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
    Get the workflow mode selected by the user (sync/async + preset/autonomous)

    Provides 4 combination modes:
    1. Preset workflow (sync) — fixed task sequence, executed sequentially
    2. Preset workflow (async) — fixed task sequence, executed in parallel — recommended!
    3. Autonomous agent scheduling (sync) — TOA dynamically creates tasks, executed sequentially
    4. Autonomous agent scheduling (async) — TOA dynamically creates tasks, executed in parallel — recommended!

    Returns a tuple (mode, is_async):
    - mode: 'preset' or 'autonomous'
    - is_async: True means async execution, False means sync execution

    Returns:
        tuple: (mode_str, is_async)
    """
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    # Display menus in different languages based on the language
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
            # Dictionary mapping: numeric choice -> (mode, is_async)
            return {
                "1": ("preset", False),
                "2": ("preset", True),
                "3": ("autonomous", False),
                "4": ("autonomous", True)
            }[choice]
        print(invalid_msg)


def create_all_agents(llm):
    """
    Create all Agent instances used in the workflow

    Each Agent is created by its corresponding factory class, with a specific role prompt and toolset.
    Compared with the sync version in main.py, the async version omits the literature_processor Agent
    (literature processing is not needed in async mode); the other Agents are the same.

    Args:
        llm: Large language model instance

    Returns:
        dict: A dictionary mapping Agent names to instances
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

    # Instantiate all Agents and return a dictionary (note: the async version does not include ExtractingAgent)
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
    Async autonomous scheduling workflow (based on the TOA intent-driven architecture)

    Instead of rigidly executing all tasks, this mode:
    1. TOA (Task Organizing Agent) analyzes the user intent
    2. Dynamically creates only the necessary tasks
    3. Sets async_execution=True for parallelizable tasks, leveraging CrewAI's async capabilities
    4. Executes asynchronously via crew.akickoff()

    Key advantages of async execution:
    - The three evaluation experts' tasks run in parallel (originally requiring 3x time, now only 1x)
    - Mechanism analysis and synthesis method tasks run in parallel
    - Overall performance improvement of 2-3x

    Args:
        user_requirement: User's material design requirement
        llm: Large language model instance
        monitor: Workflow monitor instance (optional)

    Returns:
        Crew execution result
    """
    # Dynamically import task creation classes and TOA
    from src.agents.task_organizing_agent import TaskOrganizingAgent
    from src.tasks.design_task import DesignTask
    from src.tasks.evaluation_task import EvaluationTask
    from src.tasks.final_validation_task import FinalValidationTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.synthesis_method_task import SynthesisMethodTask
    from src.tasks.operation_suggesting_task import OperationSuggestingTask
    from crewai import Task

    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    # Startup prompt
    if lang == 'en':
        print("\n🚀 Starting async autonomous scheduling workflow...")
    else:
        print("\n🚀 Starting async autonomous workflow...")
    print("-" * 70)

    # Create all Agents
    agents = create_all_agents(llm)

    # ---- Create the TOA instance and register all Agents ----
    # TOA learns about available Agents and their capabilities through the registry, so it can assign tasks correctly
    coordinator = TaskOrganizingAgent(llm)
    coordinator_agent = coordinator.create_agent()

    # Register each type of Agent with TOA, establishing capability-mapping relationships
    coordinator.register_agent("TaskOrganizingAgent", coordinator_agent)
    coordinator.register_agent("CreativeDesigningAgent", agents['material_designer'])
    # Register the evaluation experts as a list (a group of three experts)
    coordinator.register_agent("AssessmentScreeningAgent", [agents['expert_a'], agents['expert_b'], agents['expert_c']])
    coordinator.register_agent("AssessmentScreeningAgentOverall", agents['final_validator'])
    coordinator.register_agent("MechanismMiningAgent", agents['mechanism_expert'])
    coordinator.register_agent("SynthesisGuidingAgent", agents['synthesis_expert'])
    coordinator.register_agent("OperationSuggestingAgent", agents['operation_suggesting'])

    # ---- Initialize the monitor ----
    if monitor is None:
        monitor = create_monitor()
    # Mark as an async workflow
    monitor.set_workflow_info(user_requirement, "autonomous", is_async=True)

    # ---- Task start time tracking ----
    import time
    task_start_times = {}

    # ============================================================
    # TOA intent analysis
    # ============================================================
    # TOA uses the LLM to analyze the intent of the user input and determine which steps are needed
    # The returned intent dictionary contains:
    #   needs_design, needs_evaluation, needs_mechanism, needs_synthesis, needs_operation
    #   evaluation_mode: 'experts_only' or 'with_summary'
    #   material_provided: whether the user provided material information
    if lang == 'en':
        print("\n🧠 TOA analyzing user intent...")
    else:
        print("\n🧠 TOA analyzing user intent...")

    intent = coordinator.analyze_user_intent(user_requirement)

    # Print the intent analysis results — helps the user understand the system's decision-making process
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

    # ---- Initialize task and Agent lists ----
    required_tasks = []     # Dynamically collect the tasks to execute
    required_agents = []    # Dynamically collect the required Agents
    seen_roles = set()      # Used for deduplication: ensure the same Agent is not added twice
    design_task = None      # Design task (may be a real task or a virtual context)
    final_validation_task = None  # Final validation task

    # ============================================================
    # Step 1: Handle material design requirements
    # ============================================================
    # If TOA determines that a new material needs to be designed, create a full design task
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
        # The user has already provided material information, so no design task needs to be created
        # However, downstream tasks need the design task's output as context, so a virtual task is created
        material_info = intent.get('material_provided') or user_requirement
        if lang == 'en':
            print(f"\n📝 Using user-provided material: {material_info[:50]}...")
        else:
            print(f"\n📝 Using user-provided material: {material_info[:50]}...")
        # Virtual context task — only used to pass material information; it will not actually be executed
        design_task = Task(
            description=f"Existing material provided by user:\n{user_requirement}",
            expected_output="Material information for downstream tasks",
            agent=coordinator_agent  # Use the coordinator as a placeholder Agent
        )

    # ============================================================
    # Step 2: Handle evaluation tasks (the core async acceleration point)
    # ============================================================
    if intent.get('needs_evaluation', False):
        evaluation_mode = intent.get('evaluation_mode', 'with_summary')
        # Get all evaluation expert Agents (A, B, and C)
        evaluation_agents = coordinator.get_all_agents_for_task("evaluation")
        print(f"\n🔍 Number of evaluation experts: {len(evaluation_agents)} - {[a.role for a in evaluation_agents]}")
        evaluation_tasks = []

        # Create an independent evaluation task for each evaluation expert
        for agent in evaluation_agents:
            if agent.role not in seen_roles:
                required_agents.append(agent)
                seen_roles.add(agent.role)
            task = EvaluationTask(llm).create_task(agent, design_task, user_requirement)
            # Key! Setting async_execution=True enables CrewAI async parallel execution
            # This means the evaluations by experts A, B, and C can run simultaneously, greatly reducing total time
            task.async_execution = True  # Enable async parallel execution!
            evaluation_tasks.append(task)

        required_tasks.extend(evaluation_tasks)

        # Decide whether a comprehensive summary is needed based on the evaluation mode
        if evaluation_mode == 'experts_only':
            # Experts-only scoring mode — no comprehensive summary needed
            if lang == 'en':
                print(f"\n✅ Experts-only mode: 3 ASA experts, no final summary")
            else:
                print(f"\n✅ Experts-only mode: 3 ASA experts scoring, no final summary")
        else:
            # Full evaluation mode — the comprehensive summary Agent aggregates the results of the three experts
            if lang == 'en':
                print(f"\n📊 Full evaluation mode: 3 ASA experts + final summary")
            else:
                print(f"\n📊 Full evaluation mode: 3 ASA experts + final summary")

            final_validation_agent = coordinator.get_agent_for_task("final_validation")
            if final_validation_agent and final_validation_agent.role not in seen_roles:
                required_agents.append(final_validation_agent)
                seen_roles.add(final_validation_agent.role)
                # Debug check: verify that the ASA Overall Agent has no tools
                # ASA Overall only performs analysis and summarization and should not carry any tools
                agent_tools = getattr(final_validation_agent, 'tools', None)
                if agent_tools:
                    print(f"  ⚠️ ASA Overall unexpectedly contains {len(agent_tools)} tools: {[t.name if hasattr(t, 'name') else str(t) for t in agent_tools]}")
                else:
                    print(f"  ✅ ASA Overall has no tools (analysis only)")
            # Create the final validation task, whose context includes the design task and all evaluation tasks
            final_validation_task = FinalValidationTask(llm).create_task(
                final_validation_agent,
                [design_task] + evaluation_tasks if design_task else evaluation_tasks,
                user_requirement=user_requirement
            )
            required_tasks.append(final_validation_task)

    # ============================================================
    # Step 3: Handle the mechanism analysis task
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
        # Mechanism analysis depends on the final validation result; if absent, it depends on the design task
        context_task = final_validation_task or design_task
        mechanism_task = MechanismAnalysisTask(llm).create_task(
            mechanism_agent, context_task, user_requirement=user_requirement
        )
        mechanism_task.async_execution = True  # Enable async! Can run in parallel with the synthesis method
        required_tasks.append(mechanism_task)

    # ============================================================
    # Step 4: Handle the synthesis method task
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
        synthesis_task.async_execution = True  # Enable async! Can run in parallel with mechanism analysis
        required_tasks.append(synthesis_task)

    # ============================================================
    # Step 5: Handle the operation guidance task
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
    # Safety check: ensure there is at least one task
    # ============================================================
    if not required_tasks:
        # Fallback when TOA cannot identify the intent: create a material design task by default
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
    # Print the task summary (with async labels)
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
        # Mark tasks that execute asynchronously, so the user can understand the degree of parallelization
        async_flag = "⚡" if getattr(task, 'async_execution', False) else ""
        print(f"   {i}. {agent_role} {async_flag}")
    print(f"{'='*60}\n")

    # ---- Create the Crew and configure async execution ----
    # Get the DashScope embedding function class (for CrewAI's memory system)
    DashScopeEmbedder = create_dashscope_embedder()

    # ---- Tool call tracking ----
    # Use a thread lock to protect the shared dictionary, avoiding data corruption from concurrent multi-threaded writes
    import threading
    tool_calls_by_agent = {}         # {agent_role: {tool_name: count}} — tool call statistics grouped by Agent
    tool_call_lock = threading.Lock()  # Thread lock: protects concurrent access to tool_calls_by_agent
    current_agent_context = threading.local()  # Thread-local storage: each thread maintains its own current Agent context
    last_completed_agent = [None]    # Records the role of the last completed Agent (for interaction tracking)

    # Create task_callback using the module-level factory function
    # The factory function receives shared state such as the monitor, time tracking, and thread context, and returns a usable callback
    create_task_callback = create_task_callback_factory(monitor, task_start_times, current_agent_context, last_completed_agent)

    # ---- Step callback function: track tool calls ----
    def step_callback(step_output):
        """
        Capture execution details of each step, including tool calls

        CrewAI calls this callback on every Agent execution step (thinking, calling tools, generating replies).
        It is mainly used to:
        1. Identify which Agent is currently executing
        2. If it is a tool call (tool attribute), record it in the tool call statistics
        3. Print tool call logs in real time

        Agent identification tries three methods (in priority order):
        1. Get it directly from the step_output.agent attribute
        2. Get it from the step_output.agent_name attribute
        3. Get the current Agent from thread-local storage (fallback)
        """
        try:
            # Try to get the current Agent role from different sources
            agent_role = 'Unknown'

            # Method 1: Get directly from step_output's agent attribute (most reliable)
            if hasattr(step_output, 'agent'):
                agent = step_output.agent
                if hasattr(agent, 'role'):
                    agent_role = agent.role
                elif isinstance(agent, str):
                    agent_role = agent

            # Method 2: Get from the agent_name attribute
            if agent_role == 'Unknown' and hasattr(step_output, 'agent_name'):
                agent_role = step_output.agent_name

            # Method 3: Get from thread-local storage (fallback)
            if agent_role == 'Unknown':
                agent_role = getattr(current_agent_context, 'role', 'Unknown')

            # Update the current Agent role in thread-local storage
            if agent_role != 'Unknown':
                current_agent_context.role = agent_role

            # Check whether this is a tool call (AgentAction type)
            if hasattr(step_output, 'tool'):
                tool_name = step_output.tool
                # Update the tool call statistics in a thread-safe manner
                with tool_call_lock:
                    if agent_role not in tool_calls_by_agent:
                        tool_calls_by_agent[agent_role] = {}
                    if tool_name not in tool_calls_by_agent[agent_role]:
                        tool_calls_by_agent[agent_role][tool_name] = 0
                    tool_calls_by_agent[agent_role][tool_name] += 1
                    count = tool_calls_by_agent[agent_role][tool_name]
                    # Output tool call logs in real time (Agent name abbreviated to the first 15 characters)
                    print(f"  🔧 [{agent_role[:15]}] {tool_name} (#{count})")
        except Exception:
            pass  # Ignore tracking errors — do not block the main flow

    # Set the step callback for each Agent
    for agent in required_agents:
        original_execute = None
        agent_role = getattr(agent, 'role', 'Unknown')
        # Set the step_callback attribute by assignment; CrewAI will call it when the Agent executes
        agent.step_callback = step_callback

    # ---- Create the task callback for monitoring ----
    task_completion_times = []      # Records the completion time of each task
    crew_start_time = [None]        # Wrapped in a list so modifications inside the closure can propagate out
    task_counter = [0]              # Task sequence number counter
    task_callback = create_task_callback(task_completion_times, crew_start_time, task_counter, suffix="")

    # ---- Create the Crew instance ----
    crew = Crew(
        name="ECOMATS",  # Set the Crew name (shown in logs and metadata)
        agents=required_agents,
        tasks=required_tasks,
        process=Process.sequential,  # Sequential execution — but tasks marked with async_execution can run in parallel
        verbose=Config.VERBOSE,      # Read from config whether to output verbose logs
        memory=False,                # Disable the memory system — each task would trigger 7 Embedding API calls, hurting performance
        task_callback=task_callback, # Task completion callback
        step_callback=step_callback, # Step callback (tracks tool calls)
        embedder={
            # Configure a custom embedder: use DashScope's text-embedding-v2 model
            "provider": "custom",
            "config": {
                "embedding_callable": DashScopeEmbedder  # Pass the class (not an instance); CrewAI instantiates it itself
            }
        }
    )

    # Startup prompt
    if lang == 'en':
        print("⚡ Using async execution mode...")
    else:
        print("⚡ Using async execution mode...")

    # Record the Crew start time (used to calculate total elapsed time)
    crew_start_time[0] = time.time()

    # ---- Async execution! ----
    # crew.akickoff() is CrewAI 1.7.0's async entry point and returns an awaitable
    # The inputs parameter injects the user requirement into the Agents' prompt templates
    result = await crew.akickoff(inputs={'requirement': user_requirement})

    # ---- Save monitoring reports (after successful execution) ----
    if monitor:
        monitor.set_final_result(result, "completed")
        monitor.save_report()          # JSON format
        monitor.save_readable_report() # Human-readable text format
        monitor.print_summary()        # Terminal summary

    return result


async def run_preset_workflow_async(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    Async preset workflow (fixed task sequence + parallel execution optimization)

    Execution order (same as the sync version, but accelerated with async parallelism):
    1. Material design (sequential) — must be completed first
    2. Evaluations A/B/C (parallel — the 3 experts score independently at the same time)
    3. Final validation (sequential) — aggregates the evaluation results
    4. Mechanism analysis + synthesis method (parallel — the two are independent and run simultaneously)
    5. Operation guidance (sequential) — depends on the previous results

    Sources of performance improvement:
    - 3 evaluation tasks in parallel: originally ~3T time, now only ~T
    - 2 analysis tasks in parallel: originally ~2T time, now only ~T
    - Overall expected 2-3x performance improvement

    Args:
        user_requirement: User's material design requirement
        llm: Large language model instance
        monitor: Workflow monitor instance (optional)

    Returns:
        Crew execution result
    """
    import time

    print("\n🚀 Starting async preset workflow...")
    print("-" * 70)

    # Initialize the monitor (marked as async preset mode)
    if monitor is None:
        monitor = create_monitor()
    monitor.set_workflow_info(user_requirement, "preset", is_async=True)

    # Task start time tracking
    task_start_times = {}

    # Import task factory classes
    from src.tasks.design_task import DesignTask
    from src.tasks.evaluation_task import EvaluationTask
    from src.tasks.final_validation_task import FinalValidationTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.synthesis_method_task import SynthesisMethodTask
    from src.tasks.operation_suggesting_task import OperationSuggestingTask

    # Create all Agent instances
    agents = create_all_agents(llm)

    # ---- 1. Material design task (sequential, no parallelism) ----
    design_task = DesignTask(
        agent=agents['material_designer']
    ).create_task(
        agent=agents['material_designer'],
        user_requirement=user_requirement
    )

    # ---- 2. Tasks for the three evaluation experts (can run in parallel) ----
    # Evaluation expert A
    eval_a_task = EvaluationTask(
        agent=agents['expert_a']
    ).create_task(
        agent=agents['expert_a'],
        context_task=design_task
    )
    eval_a_task.async_execution = True  # Enable async!

    # Evaluation expert B
    eval_b_task = EvaluationTask(
        agent=agents['expert_b']
    ).create_task(
        agent=agents['expert_b'],
        context_task=design_task
    )
    eval_b_task.async_execution = True  # Enable async!

    # Evaluation expert C
    eval_c_task = EvaluationTask(
        agent=agents['expert_c']
    ).create_task(
        agent=agents['expert_c'],
        context_task=design_task
    )
    eval_c_task.async_execution = True  # Enable async!

    # ---- 3. Final validation task (depends on the results of the three evaluation experts) ----
    final_validation_task = FinalValidationTask(
        agent=agents['final_validator']
    ).create_task(
        agent=agents['final_validator'],
        context_task=[eval_a_task, eval_b_task, eval_c_task]
    )

    # ---- 4. Mechanism analysis task (can run in parallel with the synthesis method) ----
    mechanism_task = MechanismAnalysisTask(
        agent=agents['mechanism_expert']
    ).create_task(
        agent=agents['mechanism_expert'],
        context_task=final_validation_task
    )
    mechanism_task.async_execution = True  # Enable async — runs in parallel with the synthesis method

    # ---- 5. Synthesis method task (can run in parallel with mechanism analysis) ----
    synthesis_task = SynthesisMethodTask(
        agent=agents['synthesis_expert']
    ).create_task(
        agent=agents['synthesis_expert'],
        context_task=final_validation_task
    )
    synthesis_task.async_execution = True  # Enable async — runs in parallel with mechanism analysis

    # ---- 6. Operation guidance task (depends on the results of mechanism analysis and synthesis method) ----
    operation_task = OperationSuggestingTask(
        agent=agents['operation_suggesting']
    ).create_task(
        agent=agents['operation_suggesting'],
        context_task=[mechanism_task, synthesis_task]
    )

    # ---- Create the Crew and configure DashScope embedding ----
    # Note: pass the class rather than an instance; CrewAI manages instance creation
    DashScopeEmbedder = create_dashscope_embedder()

    # ---- Create the task callback for monitoring ----
    import threading
    current_agent_context = threading.local()
    last_completed_agent = [None]
    create_task_callback = create_task_callback_factory(monitor, task_start_times, current_agent_context, last_completed_agent)

    task_completion_times_2 = []
    crew_start_time_2 = [None]
    task_counter_2 = [0]
    task_callback = create_task_callback(task_completion_times_2, crew_start_time_2, task_counter_2, suffix="_2")

    # ---- Create the Crew instance (configuring all Agents, Tasks, and async options) ----
    crew = Crew(
        name="ECOMATS",  # Set the Crew name
        agents=list(agents.values()),  # Register all Agents
        tasks=[
            design_task,
            eval_a_task, eval_b_task, eval_c_task,  # Parallel evaluations
            final_validation_task,
            mechanism_task, synthesis_task,  # Parallel analyses
            operation_task
        ],
        process=Process.sequential,  # Sequential mode — but async_execution can override it
        verbose=Config.VERBOSE,      # Verbose output is controlled by .env
        memory=False,                # Disable the memory system (to avoid Embedding API overhead)
        task_callback=task_callback, # Task completion callback
        embedder={
            # Custom embedder configuration
            "provider": "custom",
            "config": {
                "embedding_callable": DashScopeEmbedder  # Pass the embedding class
            }
        }
    )

    # Get the language setting for displaying prompts
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    # Print parallel execution hints — helps the user understand the performance optimization details
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

    # Record the Crew start time
    crew_start_time_2[0] = time.time()

    # ---- Execute the Crew asynchronously! ----
    # akickoff() is CrewAI 1.7.0's async entry method
    result = await crew.akickoff(inputs={'requirement': user_requirement})

    # ---- Save monitoring reports ----
    if monitor:
        monitor.set_final_result(result, "completed")
        monitor.save_report()
        monitor.save_readable_report()
        monitor.print_summary()

    return result


def run_preset_workflow_sync(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    Sync preset workflow (retained for backward compatibility)

    In the async version of the program, if the user selects the sync preset mode,
    this function directly delegates to the sync version of run_preset_workflow in main.py.
    This avoids code duplication while maintaining backward compatibility.

    Args:
        user_requirement: User's material design requirement
        llm: Large language model instance
        monitor: Workflow monitor instance (optional)

    Returns:
        Workflow execution result
    """
    print("\n📌 Starting sync preset workflow...")
    print("-" * 70)

    # Ensure the current directory is on the search path so that from main import ... resolves correctly
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # Delegate to the existing sync preset workflow implementation in main.py
    from main import run_preset_workflow

    # Pass the monitor to the sync workflow
    return run_preset_workflow(user_requirement, llm, monitor)


async def main_async():
    """
    Main entry function for async mode (async)

    The complete startup flow:
    1. Load environment variables
    2. Check whether the API Key is configured
    3. Select the interface language (Chinese/English)
    4. Create the LLM instance
    5. Get the user's material design requirements
    6. Get the workflow mode selected by the user (sync/async + preset/autonomous)
    7. Create the monitor
    8. Execute the corresponding workflow based on the selection

    This is an async function (async def) and can directly await async workflows.
    """
    # Load environment variables again (ensuring any earlier possible modifications are overridden)
    load_dotenv()

    # Check whether the API Key is configured — exit directly if not, to avoid later errors
    if not Config.QWEN_API_KEY:
        print("❌ Error: QWEN_API_KEY not set")
        return

    # Select the interface language
    select_language()

    # Create the LLM instance
    llm = create_llm()

    # Get the material design requirements entered by the user
    user_requirement = get_user_input()

    # Get the workflow mode (returns two values: mode and use_async)
    mode, use_async = get_workflow_mode()

    # Create a monitor to track workflow execution
    monitor = create_monitor()
    print("📊 Workflow monitor initialized")

    # ---- Execute the corresponding workflow combination based on the user's selection ----
    if mode == "preset":
        # Preset workflow mode
        if use_async:
            # Async preset — execute evaluation and analysis tasks in parallel
            result = await run_preset_workflow_async(user_requirement, llm, monitor)
        else:
            # Sync preset — delegate to the sync implementation in main.py
            result = run_preset_workflow_sync(user_requirement, llm, monitor)
    else:
        # Autonomous scheduling mode
        if use_async:
            # Async autonomous — TOA analyzes intent + async parallel execution
            result = await run_autonomous_workflow_async(user_requirement, llm, monitor)
        else:
            # Sync autonomous — delegate to the sync implementation in main.py
            from main import run_autonomous_workflow
            result = run_autonomous_workflow(user_requirement, llm, monitor)

    # ---- Output execution completion message ----
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'
    print("\n" + "="*70)
    if lang == 'en':
        print("Execution Complete!")
    else:
        print("Execution complete!")
    print("="*70)

    # Save the result to the outputs directory (avoids printing the full result in the terminal)
    save_result(result, user_requirement, mode, use_async, workflow_id=monitor.workflow_id)

    # Output monitoring report file information
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
    Save the execution result to the outputs directory

    Create a result file with a timestamp and mode label, containing:
    - Execution time and mode
    - The user's original requirement
    - The workflow output result

    Args:
        result: Workflow execution result
        user_requirement: The user's original requirement text
        mode: Workflow mode ('preset' or 'autonomous')
        use_async: Whether async mode is used
        workflow_id: Workflow ID (from the monitor), used to generate the file name
    """
    lang = Config.LANGUAGE if hasattr(Config, 'LANGUAGE') else 'zh'

    # Ensure the outputs directory exists
    outputs_dir = os.path.join(project_root, 'outputs')
    os.makedirs(outputs_dir, exist_ok=True)

    # Generate a file name containing timestamp and mode information
    # e.g.: workflow_result_20240617_143025_preset_async.txt
    timestamp = workflow_id or datetime.now().strftime('%Y%m%d_%H%M%S')
    mode_str = f"{mode}_{'async' if use_async else 'sync'}"
    filename = f"workflow_result_{timestamp}_{mode_str}.txt"
    filepath = os.path.join(outputs_dir, filename)

    # Write the result file (including metadata and actual output)
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

    # Inform the user where the file was saved
    if lang == 'en':
        print(f"\n📁 Result saved to: {filepath}")
    else:
        print(f"\n📁 Results saved to: {filepath}")


# Python standard entry point
if __name__ == "__main__":
    # Startup banner: showcase the async enhanced edition features
    print("\n" + "="*70)
    print("ECOMATS - CrewAI 1.7.0 Async Enhanced Edition")
    print("="*70)
    print("\n🚀 New Features:")
    print("  - Async Crew execution (akickoff)")
    print("  - Parallel Task execution (async_execution=True)")
    print("  - 2-3x performance improvement")
    print("  - Fully backward compatible")
    print("\n" + "="*70)

    # Use asyncio.run() to start the async main function
    # asyncio.run() creates the event loop, executes main_async(), and cleans up afterwards
    asyncio.run(main_async())
