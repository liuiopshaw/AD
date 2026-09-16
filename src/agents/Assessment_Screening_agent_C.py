# Import the logging module for runtime logging, to facilitate debugging and tracing agent behavior
import logging
# Import the BaseAgent base class from the base_agent module; all expert agents inherit from this base class
from src.agents.base_agent import BaseAgent
# Import ToolFactory from the tools module, used to uniformly create and manage the tool set used by agents
from src.tools import ToolFactory

# Configure basic logging parameters: set the log level to WARNING to filter out redundant INFO/DEBUG messages
# This way only warnings and higher-level logs are output, avoiding excessive unnecessary console output
logging.basicConfig(level=logging.WARNING)
# Get the logger instance for the current module; all subsequent log output goes through this logger
logger = logging.getLogger(__name__)

# Assessment Screening Expert C class
# Inherits from BaseAgent, specializing in comprehensive evaluation of material proposals from the perspective of technical feasibility and engineering implementation
class AssessmentScreeningAgentC(BaseAgent):
    """Assessment Screening Expert C Agent

    A specialized agent responsible for comprehensively evaluating material
    proposals across multiple dimensions (including environmental impact,
    safety, and feasibility).
    """

    def __init__(self, llm):
        """Initialize the Assessment Screening Expert C agent.

        Args:
            llm: The large language model instance this agent will use, injected by the upper-level caller

        """
        # Lazily import the Config configuration class to avoid circular import issues at module load time
        from src.config.config import Config
        # Call the constructor of the base class BaseAgent, passing in all core parameters of the agent
        # Passed as positional arguments for more concise and compact code
        super().__init__(llm,
                         # Role identifier: Assessment Screening Expert C, used to distinguish different expert identities in multi-agent collaboration
                         "Assessment_Screening_agent_C",
                         # Goal description: tells the agent that its core task is to comprehensively evaluate all aspects of material proposals
                         "Comprehensively evaluate various aspects of material proposals",
                         # Specify the prompt template file (Markdown format) used by this agent, which is loaded and populated with parameters at runtime
                         "assessment_screening_agent_c_prompt.md",
                         # Read Expert C's dedicated temperature parameter from the configuration file to control the randomness of LLM output
                         temperature=Config.EXPERT_C_TEMPERATURE,
                         # Maximum iterations set to 2:
                         # Following the "less is more" principle, drastically reduced from the original 15 to focus on the core evaluation logic
                         max_iter=2,
                         # Prompt parameter: replace EXPERT_ID with "C" so the placeholder in the prompt template is filled correctly
                         prompt_params={"EXPERT_ID": "C"})

    def create_agent(self):
        """Create and configure the assessment screening agent.

        This method first attempts to create an EAS (Expert Agent System) LLM instance,
        and falls back to the LLM passed to the constructor if EAS creation fails.
        It then adds chemical database query tools to the agent for comprehensive material evaluation.

        Returns:
            The fully configured agent instance, containing the necessary tools for material evaluation
        """
        # LLM selection (EAS / standard LLM with temperature / default LLM) has been unified into
        # BaseAgent._resolve_llm(); it is no longer created here

        # Call the base class's create_agent method to complete the basic creation and configuration of the agent instance
        # This method loads the prompt, sets role information, initializes the CrewAI agent, etc.
        agent = super().create_agent()

        # Use the unified ASA (Assessment Screening Agent) evaluation tool set
        # The three assessment experts A/B/C share the same set of tools to ensure consistent evaluation criteria
        try:
            # Dynamically import the tool-switch check function to determine whether the current environment is configured to enable external tools
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # When tools are enabled: create the unified evaluation tool set
                # These tools typically include chemical property queries, toxicity database retrieval, etc.
                agent.tools = ToolFactory.create_unified_assessment_tools()
            else:
                # When tools are not enabled: assign an empty list
                # The agent will reason solely based on knowledge from its own training data, without calling any external APIs
                agent.tools = []
        except Exception:
            # If the tools_enabled check itself fails (e.g., a configuration module exception), enable the tool set by default
            # This is a fault-tolerant strategy of "rather use more tools than miss critical information"
            agent.tools = ToolFactory.create_unified_assessment_tools()

        # Return the fully configured agent instance for use by upper-level callers (such as the Crew coordinator)
        return agent
