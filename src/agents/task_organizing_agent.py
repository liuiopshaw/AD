# Import the logging module to record runtime log information of the agent
import logging
# Import the json module to parse the JSON-formatted intent analysis results returned by the LLM
import json
# Import the re module (regular expressions) to strip possible Markdown code block markers from LLM responses
import re
# Import type hinting utilities to improve code readability and IDE support
from typing import List, Union, Dict, Any
# Import the Agent class from the crewai framework
from crewai import Agent
# Import the custom prompt loading utility to read prompts from external .md files
from src.utils.prompt_loader import load_prompt
# Import the BaseAgent base class; TaskOrganizingAgent inherits from it to reuse common agent creation logic
from src.agents.base_agent import BaseAgent

# Set the global log level of the logging module to WARNING,
# avoiding INFO/DEBUG log flooding and keeping the output clean
logging.basicConfig(level=logging.WARNING)
# Get the logger instance for the current module; log output carries the module name for easier source tracing
logger = logging.getLogger(__name__)

# Task organizing agent class, acting as the "brain" of the entire system:
# 1. Analyze user intent (intent recognition)
# 2. Map intents to concrete task types
# 3. Manage the agent registry
# 4. Delegate tasks to the appropriate expert agents
class TaskOrganizingAgent(BaseAgent):
    """Task Organizing Agent - responsible for intent recognition and agent scheduling
       It is the coordination center of the entire multi-agent system: it receives user
       requirements, analyzes intents, and assigns tasks to the correct expert agents"""

    # Mapping table from task type to agent class name (class-level constant)
    # Each key represents a task type, and the value is the corresponding agent class name
    # This mapping defines the task types supported by the system and the handler for each type
    TASK_AGENT_MAPPING = {
        "material_design": "CreativeDesigningAgent",           # Material design task -> creative designing agent
        "evaluation": "AssessmentScreeningAgent",              # Evaluation task -> assessment & screening agent
        "final_validation": "AssessmentScreeningAgentOverall", # Final validation -> overall assessment agent
        "mechanism_analysis": "MechanismMiningAgent",          # Mechanism analysis -> mechanism mining agent
        "synthesis_method": "SynthesisGuidingAgent",           # Synthesis method -> synthesis guiding agent
        "operation_suggestion": "OperationSuggestingAgent",     # Operation suggestion -> operation suggesting agent
        "literature_processing": "ExtractingAgent",            # Literature processing -> information extracting agent
        "coordinator": "TaskOrganizingAgent"                   # Coordination task -> itself
    }

    def __init__(self, llm):
        """Initialize the task organizing agent

        Args:
            llm: Language model instance, passed in externally (usually from the Crew configuration)
        """
        # Call the constructor of the parent class BaseAgent with the predefined role and goal
        # role and goal are used by the CrewAI framework to identify the agent's responsibilities
        super().__init__(
            llm=llm,
            role="Task_Organizing_agent",  # Agent role: task organizer
            goal="Organize and coordinate the work of various expert agents to ensure tasks are completed according to plan",
            # Specify the prompt template file used by this agent
            prompt_file="task_organizing_agent_prompt.md"
        )
        # Agent registry: a dictionary where the key is the agent type name (str)
        # and the value is the corresponding Agent instance or list of Agent instances
        # Dict type annotation is used to improve code readability
        self._agent_registry: Dict[str, Union[Agent, List[Agent]]] = {}

    def create_agent(self):
        """Create and return the CrewAI Agent instance of the task organizing agent

        Unlike the base class create_agent, this method overrides the parent implementation:
        - Uses the task_organizing_agent_prompt specified in the constructor as the backstory
        - allow_delegation=True allows this agent to delegate subtasks to other expert agents
        - This agent is the coordination center of the entire system and must have task delegation enabled

        Returns:
            Agent: The configured coordinator Agent instance
        """
        return Agent(
            role="Task_Organizing_agent",
            goal="Organize and coordinate experts' work to ensure efficient task completion",
            # Load the prompt template specified in the constructor (task_organizing_agent_prompt.md, available in both zh/en)
            backstory=load_prompt(self.prompt_file),
            verbose=False,           # Disable verbose output
            allow_delegation=True,   # Critical: the coordinator must allow delegation to dispatch subtasks to expert agents
            llm=self.llm
        )

    # ============================================================
    #  Agent Registry Functions
    #  Manage the registration and lookup of all available agents in the system
    # ============================================================

    def register_agent(self, agent_type: str, agent: Union[Agent, List[Agent]]):
        """Register a single agent into the registry

        Stores the agent instance in the self._agent_registry dictionary by type name,
        so it can later be looked up by type via get_agent_for_task.

        Args:
            agent_type: Agent type name (e.g. "CreativeDesigningAgent")
            agent: A single Agent instance or a list of Agent instances
                   (the list form is used for multiple instances of the same type, e.g. multiple evaluation experts)
        """
        self._agent_registry[agent_type] = agent
        # Record a DEBUG log to trace the registration process
        logger.debug(f"Registered agent: {agent_type}")

    def register_agents(self, agents_dict: Dict[str, Any]):
        """Register agents in batch

        Iterates over the given dictionary and calls register_agent for each entry,
        simplifying repetitive code when initializing multiple agents.

        Args:
            agents_dict: A dictionary in the form {type name: agent instance}
        """
        for agent_type, agent in agents_dict.items():
            self.register_agent(agent_type, agent)

    def get_agent_for_task(self, task_type: str) -> Union[Agent, None]:
        """Get the agent instance corresponding to a task type

        First looks up the agent class name for the task type via TASK_AGENT_MAPPING,
        then retrieves the agent instance from the registry.
        If a list is registered, returns the first agent in the list.

        Args:
            task_type: Task type string (e.g. "material_design", "evaluation", etc.)

        Returns:
            An Agent instance (when found) or None (when not found)
        """
        # Step 1: Look up the agent class name for the task type in the mapping table
        agent_type = self.TASK_AGENT_MAPPING.get(task_type)
        if not agent_type:
            # If the task type is not in the mapping table, log a warning
            logger.warning(f"No agent mapping for task type: {task_type}")
            return None

        # Step 2: Get the agent instance from the registry
        agent = self._agent_registry.get(agent_type)
        if agent is None:
            # Log a warning when the agent type is not registered
            logger.warning(f"Agent type '{agent_type}' not registered")
            return None

        # Step 3: Handle list-form agents (multiple instances of the same type)
        # If it is a list, return the first one; otherwise return it directly
        if isinstance(agent, list):
            return agent[0] if agent else None
        return agent

    def get_all_agents_for_task(self, task_type: str) -> List[Agent]:
        """Get all agent instances corresponding to a task type

        Difference from get_agent_for_task:
        - get_agent_for_task returns a single agent (the first of a list)
        - This method returns the complete agent list, for scenarios requiring all experts to evaluate simultaneously

        Args:
            task_type: Task type string

        Returns:
            A list of Agents (when found) or an empty list (when not found)
        """
        # Look up the agent class name in the mapping table
        agent_type = self.TASK_AGENT_MAPPING.get(task_type)
        if not agent_type:
            logger.warning(f"No agent mapping for task type: {task_type}")
            return []

        # Get the agent from the registry
        agent = self._agent_registry.get(agent_type)
        if agent is None:
            logger.warning(f"Agent type '{agent_type}' not registered")
            return []

        # Always return a list: wrap a single agent into a list, return a list as-is
        if isinstance(agent, list):
            return agent
        return [agent]

    # ============================================================
    #  Intent Recognition Functions
    #  Use the LLM to analyze the user's natural-language requirements and extract structured intent information
    # ============================================================

    def analyze_user_intent(self, user_requirement: str) -> dict:
        """Use the LLM to analyze user intent and determine the tasks to execute

        This method is the entry analysis point of the system:
        1. Load the prompt template dedicated to intent recognition
        2. Append the user requirement to the prompt
        3. Call the LLM to obtain a structured JSON analysis result
        4. Parse the JSON and return the intent dictionary

        Args:
            user_requirement: The user's natural-language requirement description

        Returns:
            Intent analysis result dictionary containing the following fields:
            {
                "needs_design": bool,          # Whether material design is needed
                "needs_evaluation": bool,      # Whether evaluation is needed
                "evaluation_mode": str | null, # Evaluation mode: "experts_only" | "with_summary"
                "needs_mechanism": bool,       # Whether mechanism analysis is needed
                "needs_synthesis": bool,       # Whether synthesis method suggestions are needed
                "needs_operation": bool,       # Whether operation guidance is needed
                "material_provided": str | null, # Whether the user provided a specific material name
                "reasoning": str               # The LLM's reasoning text
            }
        """
        try:
            # Load the prompt template dedicated to intent recognition (intent_recognition_prompt.md)
            intent_prompt = load_prompt("intent_recognition_prompt.md")

            # Build the full prompt: concatenate the prompt template with the user requirement
            # so the LLM can analyze the user requirement in the structured format required by the template
            full_prompt = f"{intent_prompt}\n\nUser requirement:\n{user_requirement}"

            # Call the LLM to analyze the intent, passing the user message
            # The LLM is expected to return a JSON-formatted analysis result
            response = self.llm.call([{"role": "user", "content": full_prompt}])
            # Strip leading/trailing whitespace from the response text
            response_text = response.strip()

            # Strip Markdown code block markers (```json and ```)
            # The LLM sometimes wraps JSON in Markdown formatting; remove it first to ensure JSON parsing succeeds
            response_text = re.sub(r'^```json\s*', '', response_text)  # Remove the leading ```json
            response_text = re.sub(r'\s*```$', '', response_text)       # Remove the trailing ```
            response_text = response_text.strip()                       # Strip whitespace again

            # Parse the cleaned text into a JSON dictionary
            intent = json.loads(response_text)

            # Log the LLM's reasoning at INFO level for debugging and auditing
            # Use .get to prevent a KeyError if the LLM's JSON lacks the reasoning key
            logger.info(f"TOA Intent Analysis: {intent.get('reasoning', '')}")
            return intent

        except json.JSONDecodeError as e:
            # JSON parsing failed: log the error details and the raw response text for troubleshooting
            logger.error(f"Failed to parse intent JSON: {e}")
            logger.error(f"Response text: {response_text}")
            # Use the default intent as a fallback to ensure the system does not crash on parse failure
            # Default to the most conservative plan: perform material design and evaluation (with summary)
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
            # Catch all other exceptions (e.g. LLM call failure, network errors, etc.)
            logger.error(f"Intent analysis failed: {e}")
            # Also use the default intent as a fallback
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
