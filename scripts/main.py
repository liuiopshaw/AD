#!/usr/bin/env python3
"""
ECOMATS - Multi-Agent System for Water Treatment Material Design Based on CrewAI

This is the synchronous main program entry point that coordinates multiple AI agents
to design, evaluate, and optimize water treatment materials through a structured workflow.
"""

# ---- Standard library imports ----
# sys: used to modify the Python module search path so that project modules can be imported correctly
import sys
# os: used to build cross-platform file paths and perform environment variable operations
import os
# json: used to parse the JSON-formatted results returned by Agents (evaluation scores, rankings, etc.)
import json
# signal: used for Windows compatibility handling — Windows does not support the SIGHUP signal
import signal
# time: used to record task execution timestamps and compute elapsed time
import time
# dotenv: loads sensitive environment variables such as API keys from a .env file, avoiding hardcoding
from dotenv import load_dotenv
# CrewAI core classes: Crew manages multiple Agents and Tasks; Process defines the execution strategy (sequential/hierarchical)
from crewai import Crew, Process
# dashscope: Alibaba Cloud DashScope API (Tongyi Qianwen model service); the API Key must be injected at runtime
import dashscope

# ---- Add the project root directory to the module search path ----
# This ensures that submodules such as src and workflow can be imported correctly
# no matter which directory the script is run from
# os.path.dirname(__file__): the directory containing the current file (scripts/)
# os.path.dirname(...) + '..': goes up to the project root directory (ECOMATS/)
project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
# Insert at the front of the path list so the project version is loaded preferentially over the system version
sys.path.insert(0, os.path.abspath(project_root))

# ---- Import the workflow monitoring module ----
# WorkflowMonitor: records execution information, elapsed time, tool calls, etc. for each Agent and generates monitoring reports
# create_monitor/get_monitor: factory functions that create or retrieve the global monitor instance
from src.utils.workflow_monitor import WorkflowMonitor, create_monitor, get_monitor

# ---- Windows compatibility patch ----
# The SIGHUP signal is unavailable on Windows; create a placeholder here to prevent ImportError
if sys.platform == 'win32':
    if not hasattr(signal, 'SIGHUP'):
        signal.SIGHUP = None  # Windows does not support SIGHUP; set to None to avoid AttributeError
    # Set console output encoding to UTF-8 to prevent Chinese characters from showing as garbled text in the Windows terminal
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass  # Python < 3.7 does not support the reconfigure method; ignore silently

def get_user_input():
    """
    Get the user-defined material design requirements

    Interactively reads from the command line the material type and performance
    requirements the user wants to design. This is the starting point of the entire
    multi-Agent workflow — user requirements drive all subsequent tasks.

    Returns:
        str: The material design requirement text entered by the user
    """
    print("Please enter your material design requirements:")
    print("Example: Design an efficient catalyst for treating cadmium-containing heavy metal wastewater")
    print("Note: The system supports detailed material type classification and structural description requirements")
    # input() is a blocking call that waits for user input in the terminal
    user_input = input("Material design requirements: ")
    return user_input

def get_workflow_mode():
    """
    Get the workflow mode selected by the user

    Two execution modes are provided:
    1. preset: preset workflow — executes all tasks in a fixed order (design → evaluation → validation → synthesis → mechanism → operation suggestions)
    2. autonomous: Agent autonomous scheduling — the coordinator Agent (TOA) analyzes the intent and dynamically creates the necessary tasks

    Returns:
        str: 'preset' or 'autonomous'
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
    Check whether the required environment variables are set

    Before starting the workflow, verify that QWEN_API_KEY and QWEN_MODEL_NAME
    are configured, so the workflow does not fail halfway due to a missing API Key.

    Returns:
        bool: True if all required variables are set, otherwise False
    """
    # Lazily import Config to ensure the environment variables have been loaded
    from src.config.config import Config
    # Define the required environment variables and their current values
    required_vars = {
        "QWEN_API_KEY": Config.QWEN_API_KEY,
        "QWEN_MODEL_NAME": Config.QWEN_MODEL_NAME
    }

    # Collect the names of all unset (empty-valued) variables
    missing_vars = []
    for var_name, var_value in required_vars.items():
        if not var_value:
            missing_vars.append(var_name)

    # If any variables are missing, print an error message and a configuration example
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
    Create all Agent instances used in the workflow

    Each Agent corresponds to a specialized role and is created by its own factory class:
    - TaskOrganizingAgent: task coordinator; analyzes user intent and schedules tasks
    - CreativeDesigningAgent: material designer; creatively designs material solutions based on requirements
    - AssessmentScreeningAgent A/B/C: three independent evaluation experts who score from different perspectives
    - AssessmentScreeningAgentOverall: overall evaluation expert; aggregates evaluation results and gives the final ranking
    - ExtractingAgent: literature information extraction expert
    - MechanismMiningAgent: mechanism analysis expert; explains how the material works
    - SynthesisGuidingAgent: synthesis guidance expert; provides material preparation plans
    - OperationSuggestingAgent: operation suggestion expert; provides practical application operation guides

    Args:
        llm: the large language model instance; all Agents share the same LLM connection

    Returns:
        dict: a mapping from Agent names to instances, for convenient name-based indexing
    """
    # Import the factory class of each Agent (each class is responsible for creating an Agent for a specific domain)
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
    # Instantiate each Agent — each Agent uses its own role prompt and tool set
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

    # Return as a dictionary so callers can access Agents by semantic names
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
    Extract feedback information from a task result for iterative improvement

    When a round of design evaluation is unsatisfactory, the evaluation experts'
    specific criticisms and suggestions need to be extracted and injected as context
    into the next design iteration, forming a closed-loop optimization.

    Two feedback sources are supported:
    1. The final_validator result (contains recommendations and cons fields)
    2. The results of evaluation experts A/B/C (contain a cons field indicating the issues found)

    Args:
        result: the task execution result (string or dictionary format)

    Returns:
        str: the extracted feedback text, or a fallback message if parsing fails
    """
    try:
        # Try to parse a JSON-formatted result — if it is a string, deserialize it as JSON first
        if isinstance(result, str):
            result_data = json.loads(result)
        else:
            result_data = result

        # Traverse the result structure and collect feedback information
        feedback = ""
        if isinstance(result_data, dict):
            # Case 1: feedback from the overall evaluation expert
            # "results" is a list; each element contains the score and suggestions for one material
            if "results" in result_data and isinstance(result_data["results"], list):
                for item in result_data["results"]:
                    if "recommendations" in item:
                        feedback += f"Recommendations: {item['recommendations']}\n"
                    if "cons" in item:
                        feedback += f"Issues found: {item['cons']}\n"
            # Case 2: feedback from a single evaluation expert
            # The "evaluator" field identifies which expert (A/B/C) it is
            elif "evaluator" in result_data:
                if result_data["evaluator"] in ["A", "B", "C"]:
                    if "results" in result_data and isinstance(result_data["results"], list):
                        for item in result_data["results"]:
                            if "cons" in item:
                                feedback += f"Issues pointed out by evaluator {result_data['evaluator']}: {item['cons']}\n"
        return feedback
    except Exception as e:
        # Fallback handling when JSON parsing fails
        print(f"Error parsing feedback information: {e}")
        return "Unable to extract specific feedback information, please redesign the material solution."

def check_if_iteration_needed(result):
    """
    Determine whether the design solution needs iterative optimization based on evaluation scores

    Scores from two evaluation sources are checked:
    1. The weighted_total weighted total score from the overall evaluation expert (final_validator)
    2. The average of the scores list from each evaluation expert (A/B/C)

    If any score is below the Config.MIN_ACCEPTABLE_SCORE threshold,
    or a material is rated "Invalid"/"Poor", a redesign is required.

    Args:
        result: the evaluation result (contains scores and rankings)

    Returns:
        bool: True if iteration is needed, otherwise False
    """
    from src.config.config import Config
    try:
        # Parse the result format
        if isinstance(result, str):
            result_data = json.loads(result)
        else:
            result_data = result

        # Handle the result from the overall evaluation expert
        if isinstance(result_data, dict) and "results" in result_data:
            if isinstance(result_data["results"], list):
                for item in result_data["results"]:
                    if "rank" in item:
                        # If the rank is Invalid or Poor, iteration is needed
                        if item["rank"] in ["Invalid", "Poor"]:
                            return True
                        # If the weighted total score is below the acceptable threshold, iteration is needed
                        if "weighted_total" in item and item["weighted_total"] < Config.MIN_ACCEPTABLE_SCORE:
                            return True
            # Handle the result from a single evaluation expert
            elif "evaluator" in result_data and result_data["evaluator"] in ["A", "B", "C"]:
                if "results" in result_data and isinstance(result_data["results"], list):
                    for item in result_data["results"]:
                        if "scores" in item and isinstance(item["scores"], list):
                            # Compute the average of all scores
                            avg_score = sum(item["scores"]) / len(item["scores"]) if item["scores"] else 0
                            if avg_score < Config.MIN_ACCEPTABLE_SCORE:
                                return True
        return False
    except Exception as e:
        print(f"Error checking iteration requirements: {e}")
        return False

def run_design_iteration(user_requirement, llm, iteration_count=0):
    """
    Run the iterative design process until the result meets requirements or the maximum iteration count is reached

    This is a recursive function:
    1. First check whether the maximum iteration count has been reached (to prevent infinite loops)
    2. Run one round of the preset workflow to obtain design + evaluation results
    3. Check whether the evaluation result meets the quality requirements
    4. If not: extract feedback information, append the feedback to the requirement, and recursively enter the next iteration
    5. If yes: return the final result

    This iterative mechanism implements a closed-loop "design-evaluate-feedback-improve" optimization,
    similar to how human materials scientists repeatedly experiment to improve a formulation.

    Args:
        user_requirement: the user's material design requirement
        llm: the large language model instance
        iteration_count: the current iteration count (default 0)

    Returns:
        str: the final design result or a message indicating the maximum iteration count was reached
    """
    from src.config.config import Config
    # Recursion termination condition: prevent infinite iterations from exhausting the API quota
    if iteration_count >= Config.MAX_DESIGN_ITERATIONS:
        return "Maximum iterations reached, stopping iterative design."

    print(f"Starting design iteration {iteration_count + 1}...")

    # Run one full round of the preset workflow (design → evaluation → validation → synthesis → mechanism → operation suggestions)
    result = run_preset_workflow(user_requirement, llm)

    # Check whether this round's result requires further iterative optimization
    if check_if_iteration_needed(result):
        print("Current design does not meet requirements, iterative optimization needed...")
        # Extract the specific improvement points and criticisms from the evaluation result
        feedback = extract_feedback_from_result(result)
        if feedback:
            # Append the feedback to the original requirement as improvement suggestions
            # so the design Agent can see the previous problems and address them in the next round
            updated_requirement = f"{user_requirement}\n\nImprovement suggestions based on previous evaluation: {feedback}"
            # Recursively call to enter the next iteration (iteration_count + 1)
            return run_design_iteration(updated_requirement, llm, iteration_count + 1)
        else:
            # If feedback cannot be extracted, return the current result directly (no improvement clues; stop iterating)
            return result
    else:
        # The result meets the requirements; return the final result
        return result

def run_preset_workflow(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    Run the preset workflow mode, executing tasks in a fixed sequence

    This mode executes all tasks in a predefined order:
    1. Material design (CreativeDesigningAgent)
    2. Evaluation (3 experts in parallel: A/B/C)
    3. Final validation (AssessmentScreeningAgentOverall)
    4. Synthesis method (SynthesisGuidingAgent)
    5. Mechanism analysis (MechanismMiningAgent)
    6. Operation suggestions (OperationSuggestingAgent)

    CrewAI's Process.sequential ensures tasks execute sequentially according to their dependencies,
    while tasks that depend on the same task (e.g., the three evaluation tasks all depend on the design task) can run in parallel.

    Args:
        user_requirement: the user's material design requirement
        llm: the large language model instance
        monitor: the workflow monitor instance (optional), used to record the execution process

    Returns:
        Crew execution result
    """
    print("Starting preset workflow mode...")
    # Ensure the project path is in the search path (defensive coding)
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    sys.path.insert(0, os.path.abspath(project_root))
    # Import the configuration and task factory classes
    from src.config.config import Config
    from src.tasks.design_task import DesignTask
    from src.tasks.evaluation_task import EvaluationTask
    from src.tasks.final_validation_task import FinalValidationTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.synthesis_method_task import SynthesisMethodTask
    from src.tasks.operation_suggesting_task import OperationSuggestingTask

    # If no monitor is provided, create a default one
    if monitor is None:
        monitor = create_monitor()

    # Set the monitor's basic workflow information (requirement text, mode, whether async)
    monitor.set_workflow_info(user_requirement, "preset", is_async=False)

    # Create all Agent instances
    agents = create_all_agents(llm)

    # ---- Create tasks and their dependencies ----
    # Each task specifies its prerequisite tasks via the context_task parameter
    # CrewAI automatically handles the execution order based on these dependencies

    # 1. First create the material design task (no prerequisites; the starting point of the workflow)
    design_task = DesignTask(llm).create_task(agents['material_designer'], user_requirement=user_requirement)

    # Tools are invoked by Agents on demand, with results cached through ContextStore
    # Pre-execution logic has been removed to avoid redundancy

    # 2. Create evaluation tasks for the three evaluation experts, all depending on the design task
    # The three evaluation tasks share the same design task as context; CrewAI schedules them in parallel after design completes
    # Explicitly passing user_requirement ensures the tool invocation strategy executes correctly
    evaluation_task_a = EvaluationTask(llm).create_task(agents['expert_a'], design_task, user_requirement=user_requirement)
    evaluation_task_b = EvaluationTask(llm).create_task(agents['expert_b'], design_task, user_requirement=user_requirement)
    evaluation_task_c = EvaluationTask(llm).create_task(agents['expert_c'], design_task, user_requirement=user_requirement)

    # 3. Create the final validation task — comprehensively analyzes the design result and the three experts' evaluations
    # context is a list containing the design task and the three evaluation tasks; CrewAI waits for all of them to complete before executing this task
    final_validation_task = FinalValidationTask(llm).create_task(agents['final_validator'],
                                                           [design_task, evaluation_task_a, evaluation_task_b, evaluation_task_c], user_requirement=user_requirement)

    # 4. Create the synthesis method task — provides process guidance for material preparation
    synthesis_method_task = SynthesisMethodTask(llm).create_task(agents['synthesis_expert'], final_validation_task, user_requirement=user_requirement)

    # 5. Create the mechanism analysis task — deeply analyzes the material's microscopic working principles
    mechanism_analysis_task = MechanismAnalysisTask(llm).create_task(agents['mechanism_expert'], final_validation_task, user_requirement=user_requirement)

    # 6. Create the operation suggestion task — provides operation guidance for practical applications
    operation_suggesting_task = OperationSuggestingTask(llm).create_task(agents['operation_suggesting'], final_validation_task, user_requirement=user_requirement)

    # ---- Create the task-Agent mapping table for callback tracking ----
    # Each tuple contains: (task, Agent, role name)
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

    # Create a quick lookup dictionary from task description to Agent
    # key: the first 100 characters of the task description (used as a simplified unique identifier)
    # value: a (Agent instance, role name) tuple
    task_desc_to_agent = {}
    for task, agent, role_name in task_agent_map:
        desc_key = str(task.description)[:100]  # Use the first 100 characters of the description as the key, avoiding match failures caused by changes to the full description
        task_desc_to_agent[desc_key] = (agent, role_name)

    # ---- Create a global timestamp for generating output file names ----
    import datetime
    global_workflow_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # ---- Initialize tracking variables ----
    task_start_times = {}        # Record the start time of each task
    task_completion_order = []   # Record task names in completion order
    last_task_end_time = time.time()  # The end time of the previous task, used to compute the current task's waiting/running duration

    def task_callback(task_output):
        """
        Callback function invoked when a task completes

        Automatically called by CrewAI after each task finishes; it does the following:
        1. Computes the task duration (relative to the end time of the previous task)
        2. Writes the execution result to a log file under the outputs/ directory
        3. Notifies the monitor to update the execution status

        CrewAI's task_callback mechanism is a synchronous callback — it fires as soon as a task completes,
        so in sequential mode the callback order matches the task completion order.
        """
        nonlocal last_task_end_time  # Modify the outer closure variable
        import json
        import os

        # Ensure the outputs directory exists
        outputs_dir = os.path.join(project_root, "outputs")
        os.makedirs(outputs_dir, exist_ok=True)

        # Build the output file path (all tasks of the same workflow write to the same file)
        workflow_result_filename = f"workflow_result_{global_workflow_timestamp}.txt"
        workflow_result_filepath = os.path.join(outputs_dir, workflow_result_filename)

        # Extract the task description and name from task_output
        task_description = getattr(task_output, 'description', 'N/A')
        task_name_raw = getattr(task_output, 'name', None)

        # Use the first 100 characters of the description as the key to look up which Agent executed the task
        desc_key = str(task_description)[:100]
        agent_info = task_desc_to_agent.get(desc_key)

        if agent_info:
            agent, agent_role = agent_info
            agent_name = getattr(agent, 'name', agent_role)
        else:
            # If not found in the mapping table, get the Agent information from the TaskOutput object
            agent = getattr(task_output, 'agent', None)
            agent_name = getattr(agent, 'name', 'Unknown') if agent else 'Unknown'
            agent_role = getattr(agent, 'role', 'Unknown') if agent else 'Unknown'

        # Generate the task sequence number and name
        task_idx = len(task_completion_order) + 1
        task_name = task_name_raw or f"Task_{task_idx}_{agent_role}"
        task_completion_order.append(task_name)

        # Try to extract the JSON-formatted structured output (such as evaluation scores)
        json_output = None
        if hasattr(task_output, 'json_dict') and task_output.json_dict:
            json_output = task_output.json_dict

        # Compute the task execution duration
        current_time = time.time()
        task_start_time = last_task_end_time
        task_duration = current_time - task_start_time

        # Report the execution information to the monitor
        if monitor:
            monitor.start_agent_execution(agent_name, agent_role, task_name, str(task_description)[:200])
            if monitor._current_execution:
                monitor._current_execution.start_time = task_start_time
            monitor.end_agent_execution(output=str(task_output)[:5000], json_output=json_output)

        # Update the completion time of the last task for the next task's duration calculation
        last_task_end_time = current_time

        # Append the task result to the output file (append mode, preserving previous tasks' content)
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
                # ensure_ascii=False ensures Chinese characters are not escaped as Unicode sequences
                json.dump(json_output, f, ensure_ascii=False, indent=2)
            f.write(f"\n{'='*60}\n")

    # ---- Create the Crew instance, registering all Agents and Tasks ----
    # Crew is CrewAI's core scheduler, responsible for scheduling task execution according to dependencies and the Process strategy
    ecomats_crew = Crew(
        agents=[
            # List all Agents (including those that may not directly execute tasks but provide support)
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
            # Tasks are listed in execution order — CrewAI infers the actual order from context dependencies
            design_task,
            evaluation_task_a,
            evaluation_task_b,
            evaluation_task_c,
            final_validation_task,
            synthesis_method_task,
            mechanism_analysis_task,
            operation_suggesting_task
        ],  # Tasks execute in order — those depending on the same prerequisite can run in parallel
        process=Process.sequential,  # Sequential execution mode: finish one task before starting the next
        verbose=Config.VERBOSE,       # Read the verbose output setting from the configuration
        task_callback=task_callback   # Callback triggered when each task completes, used for logging and monitoring
    )

    # ---- Execute the workflow ----
    try:
        # kickoff() is CrewAI's entry method that starts the entire workflow
        # Internally, CrewAI automatically schedules based on each task's context dependencies and the Process strategy
        result = ecomats_crew.kickoff()

        # On successful execution, notify the monitor to record the final state and save reports
        if monitor:
            monitor.set_final_result(result, "completed")
            monitor.save_report()          # Save the JSON-format monitoring report
            monitor.save_readable_report() # Save the human-readable text monitoring report
            monitor.print_summary()        # Print the execution summary in the terminal

        return result
    except Exception as e:
        # On failure, record the error state as well, then run the tool-only fallback
        if monitor:
            monitor.set_final_result(None, "error", str(e))
            monitor.save_report()
            monitor.save_readable_report()
        return run_tool_only_summary(user_requirement)

def _execute_material_tools(user_requirement: str, project_root: str):
    """
    Deprecated: pre-execute material-related tool calls

    This function is no longer used. Agents now invoke tools on demand and cache results through ContextStore.

    This function is kept for backward compatibility so that old code references do not raise errors.
    """
    pass  # Tool calls are no longer pre-executed

def run_autonomous_workflow(user_requirement, llm, monitor: WorkflowMonitor = None):
    """
    Run the Agent autonomous scheduling mode: dynamically create tasks based on TOA intent recognition

    Unlike the preset mode, this mode does not rigidly execute all tasks; instead it:
    1. Has the TOA (Task Organizing Agent) analyze the user intent
    2. Creates only the necessary tasks based on the intent (e.g., if the user only asks for mechanism analysis, no design task is created)
    3. Dynamically assembles the required Agents and Tasks

    This avoids wasting tokens and time on unneeded tasks while preserving flexibility.

    Args:
        user_requirement: the user's material design requirement
        llm: the large language model instance
        monitor: the workflow monitor instance (optional)

    Returns:
        Crew execution result
    """
    print("Starting autonomous scheduling mode...")
    # Ensure the project path is in the search path
    project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    sys.path.insert(0, os.path.abspath(project_root))
    # Import the necessary modules
    from src.config.config import Config
    from src.agents.task_organizing_agent import TaskOrganizingAgent
    from src.tasks.design_task import DesignTask
    from src.tasks.evaluation_task import EvaluationTask
    from src.tasks.final_validation_task import FinalValidationTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.synthesis_method_task import SynthesisMethodTask
    from src.tasks.operation_suggesting_task import OperationSuggestingTask
    from crewai import Task  # Used to create virtual context tasks

    # Create all Agent instances
    agents = create_all_agents(llm)

    # ---- Create the task coordinator Agent (TOA) ----
    # The TOA is the core of the entire autonomous scheduling mode: it analyzes intent and assigns tasks
    coordinator = TaskOrganizingAgent(llm)
    coordinator_agent = coordinator.create_agent()

    # Register each type of Agent into the TOA's registry
    # Through this registry, the TOA knows which Agents are available and what each can do
    coordinator.register_agent("TaskOrganizingAgent", coordinator_agent)
    coordinator.register_agent("CreativeDesigningAgent", agents['material_designer'])
    # The evaluation experts form a group (three experts A/B/C) and are registered as a list
    coordinator.register_agent("AssessmentScreeningAgent", [agents['expert_a'], agents['expert_b'], agents['expert_c']])
    coordinator.register_agent("AssessmentScreeningAgentOverall", agents['final_validator'])
    coordinator.register_agent("ExtractingAgent", agents['literature_processor'])
    coordinator.register_agent("MechanismMiningAgent", agents['mechanism_expert'])
    coordinator.register_agent("SynthesisGuidingAgent", agents['synthesis_expert'])
    coordinator.register_agent("OperationSuggestingAgent", agents['operation_suggesting'])

    # Initialize the monitor
    if monitor is None:
        monitor = create_monitor()
    monitor.set_workflow_info(user_requirement, "autonomous", is_async=False)

    # ============================================================
    # TOA intent-driven workflow: analyze user intent
    # ============================================================
    # The TOA analyzes the user input via the LLM to determine which steps are needed:
    #   needs_design: whether a new material needs to be designed
    #   needs_evaluation: whether evaluation/screening is needed
    #   evaluation_mode: 'experts_only' (only the three experts score) or 'with_summary' (includes an overall summary)
    #   needs_mechanism: whether mechanism analysis is needed
    #   needs_synthesis: whether synthesis method guidance is needed
    #   needs_operation: whether operation suggestions are needed
    #   material_provided: whether the user has already provided material information (if so, skip design)
    print("\n🧠 TOA analyzing user intent...")
    intent = coordinator.analyze_user_intent(user_requirement)
    print(f"✅ Intent analysis complete: {intent['reasoning']}")

    # Print the detailed intent analysis results for debugging and to let the user understand the system's decisions
    print(f"\n📊 Intent Details:")
    print(f"   • Needs Design: {intent.get('needs_design', False)}")
    print(f"   • Needs Evaluation: {intent.get('needs_evaluation', False)}")
    print(f"   • Evaluation Mode: {intent.get('evaluation_mode', None)}")
    print(f"   • Needs Mechanism: {intent.get('needs_mechanism', False)}")
    print(f"   • Needs Synthesis: {intent.get('needs_synthesis', False)}")
    print(f"   • Needs Operation: {intent.get('needs_operation', False)}")
    print(f"   • Material Provided: {intent.get('material_provided', None)}")

    # ---- Initialize task and Agent lists ----
    required_tasks = []     # Dynamically collect the tasks to execute based on the intent
    required_agents = []    # Dynamically collect the required Agents based on the intent
    seen_roles = set()      # Used for deduplication: ensure the same Agent role is added only once
    design_task = None      # Reference to the design task (may be a real task or a virtual context task)
    final_validation_task = None  # Reference to the final validation task

    # ============================================================
    # Step 1: Handle the material design requirement
    # ============================================================
    if intent.get('needs_design', False):
        # The user needs a new material design: create the full design task
        print("\n🛠️ Creating material design task...")
        design_agent = coordinator.get_agent_for_task("material_design")
        if design_agent and design_agent.role not in seen_roles:
            required_agents.append(design_agent)
            seen_roles.add(design_agent.role)

        design_task = DesignTask(llm).create_task(design_agent, user_requirement=user_requirement)
        required_tasks.append(design_task)

        # Tools are invoked by Agents on demand and cached through ContextStore

    elif intent.get('needs_evaluation', False) or intent.get('needs_mechanism', False) or intent.get('needs_synthesis', False) or intent.get('needs_operation', False):
        # The user provided material information and no new design is needed — create a virtual context task to pass the material information along
        # This task will not actually be executed (not added to required_tasks), but serves as a context dependency for downstream tasks
        material_info = intent.get('material_provided') or user_requirement
        print(f"\n📝 Using user-provided material info: {material_info[:50]}...")

        # Create a virtual context task — only used to pass material information to downstream tasks
        # agent is set to coordinator_agent as a placeholder (the virtual task will not actually be dispatched for execution)
        design_task = Task(
            description=f"Existing material provided by user:\n{user_requirement}",
            expected_output="Material information for downstream tasks",
            agent=coordinator_agent  # Use the coordinator as the placeholder Agent
        )
        # Note: the virtual task is not added to the required_tasks list

    # ============================================================
    # Step 2: Handle evaluation tasks
    # ============================================================
    if intent.get('needs_evaluation', False):
        evaluation_mode = intent.get('evaluation_mode', 'with_summary')

        # Get all evaluation expert Agents (three experts: A, B, C)
        evaluation_agents = coordinator.get_all_agents_for_task("evaluation")
        evaluation_tasks = []

        for agent in evaluation_agents:
            if agent.role not in seen_roles:
                required_agents.append(agent)
                seen_roles.add(agent.role)
            # Create an evaluation task that depends on the design task (or the virtual context task)
            task = EvaluationTask(llm).create_task(agent, design_task, user_requirement)
            evaluation_tasks.append(task)

        required_tasks.extend(evaluation_tasks)

        if evaluation_mode == 'experts_only':
            # Experts-only mode: the three ASA experts score independently; no overall summary is needed
            print(f"\n✅ Experts-only mode: 3 ASA experts scoring, no final summary")
            print(f"   Experts-only mode: 3 ASA experts scoring, no final summary")
        else:
            # Full evaluation mode (with overall summary)
            print(f"\n📊 Full evaluation mode: 3 ASA experts + final summary")
            print(f"   Full evaluation mode: 3 ASA experts + final summary")

            # Get the overall evaluation Agent
            final_validation_agent = coordinator.get_agent_for_task("final_validation")
            if final_validation_agent and final_validation_agent.role not in seen_roles:
                required_agents.append(final_validation_agent)
                seen_roles.add(final_validation_agent.role)

            # Create the final validation task, whose context includes the design task and the aggregation of all evaluation tasks
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
        print(f"\n🔬 Creating mechanism analysis task...")
        mechanism_agent = coordinator.get_agent_for_task("mechanism_analysis")
        if mechanism_agent and mechanism_agent.role not in seen_roles:
            required_agents.append(mechanism_agent)
            seen_roles.add(mechanism_agent.role)

        # Mechanism analysis depends on the final validation result; if there is no overall evaluation, it depends on the design task
        context_task = final_validation_task or design_task
        mechanism_task = MechanismAnalysisTask(llm).create_task(
            mechanism_agent, context_task, user_requirement=user_requirement
        )
        required_tasks.append(mechanism_task)

    # ============================================================
    # Step 4: Handle the synthesis method task
    # ============================================================
    if intent.get('needs_synthesis', False):
        print(f"\n🧪 Creating synthesis method task...")
        synthesis_agent = coordinator.get_agent_for_task("synthesis_method")
        if synthesis_agent and synthesis_agent.role not in seen_roles:
            required_agents.append(synthesis_agent)
            seen_roles.add(synthesis_agent.role)

        # The synthesis method likewise depends on the final validation result or the design task
        context_task = final_validation_task or design_task
        synthesis_task = SynthesisMethodTask(llm).create_task(
            synthesis_agent, context_task, user_requirement=user_requirement
        )
        required_tasks.append(synthesis_task)

    # ============================================================
    # Step 5: Handle the operation suggestion task
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
    # Safety check: ensure there is at least one task
    # ============================================================
    if not required_tasks:
        # Fallback strategy when the TOA cannot identify any intent: create a material design task by default
        print("\n⚠️ No tasks identified, defaulting to material design")
        design_agent = coordinator.get_agent_for_task("material_design")
        if design_agent and design_agent.role not in seen_roles:
            required_agents.append(design_agent)
            seen_roles.add(design_agent.role)
        design_task = DesignTask(llm).create_task(design_agent, user_requirement=user_requirement)
        required_tasks.append(design_task)

    # ============================================================
    # Print a task summary so the user knows which steps the system will execute
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

    # ---- Create the task-description-to-Agent mapping (used to identify the Agent in callbacks) ----
    task_desc_to_agent = {}
    for task in required_tasks:
        if task and task.agent:
            desc_key = str(task.description)[:100]
            task_desc_to_agent[desc_key] = (task.agent, getattr(task.agent, 'role', 'Unknown'))

    # ---- Create the global timestamp and tracking variables ----
    import datetime
    global_workflow_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    task_start_times = {}
    task_completion_order = []
    last_task_end_time = time.time()

    def task_callback(task_output):
        """
        Task completion callback — identical in logic to the callback in the preset workflow.
        Records each task's output and duration, and updates the monitor.
        The results of all tasks are appended to the same output file.
        """
        nonlocal last_task_end_time
        import json
        import os

        # Ensure the outputs directory exists
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
            # Get the Agent information from the TaskOutput
            agent = getattr(task_output, 'agent', None)
            agent_name = getattr(agent, 'name', 'Unknown') if agent else 'Unknown'
            agent_role = getattr(agent, 'role', 'Unknown') if agent else 'Unknown'

        task_idx = len(task_completion_order) + 1
        task_name = task_name_raw or f"Task_{task_idx}_{agent_role}"
        task_completion_order.append(task_name)

        # Extract the JSON structured output
        json_output = None
        if hasattr(task_output, 'json_dict') and task_output.json_dict:
            json_output = task_output.json_dict

        # Compute the task duration
        current_time = time.time()
        task_start_time = last_task_end_time
        task_duration = current_time - task_start_time

        # Update the monitor
        if monitor:
            monitor.start_agent_execution(agent_name, agent_role, task_name, str(task_description)[:200])
            if monitor._current_execution:
                monitor._current_execution.start_time = task_start_time
            monitor.end_agent_execution(output=str(task_output)[:5000], json_output=json_output)

        last_task_end_time = current_time

        # Append to the output file
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

    # ---- Create the Crew instance ----
    # Dynamically build the Crew from the tasks and Agents selected by intent
    all_tasks = required_tasks
    if design_task and intent.get('needs_design', False):
        # If design is needed, design_task was already added to required_tasks in Step 1
        all_tasks = required_tasks
    elif design_task:
        # The virtual context task is not added to the task list (it will not actually be executed)
        all_tasks = required_tasks

    ecomats_crew = Crew(
        agents=required_agents,      # Only include the Agents selected based on the intent
        tasks=all_tasks,             # Only include the tasks selected based on the intent
        process=Process.sequential,  # Sequential execution mode
        verbose=Config.VERBOSE,
        task_callback=task_callback
    )

    # ---- Execute the workflow ----
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
        # If Crew execution fails, fall back to tool-only mode
        return run_tool_only_summary(user_requirement)

