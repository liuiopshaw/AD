# Import the logging module for run-time logging, facilitating debugging and agent behavior tracing
import logging
# Import the BaseAgent base class from the base_agent module; all expert agents inherit from it
from src.agents.base_agent import BaseAgent
# Import ToolFactory from the tools module, used to uniformly create and manage the agent's toolset
from src.tools import ToolFactory

# Configure basic logging parameters: set the log level to WARNING to filter out redundant INFO/DEBUG messages
# This ensures only warnings and higher-level logs are output, avoiding excessive console noise
logging.basicConfig(level=logging.WARNING)
# Get the logger instance for the current module; all subsequent log output goes through this logger
logger = logging.getLogger(__name__)

# Assessment Screening Expert Agent B
# Inherits from BaseAgent and is dedicated to comprehensively evaluating material proposals
# from an Environmental, Health and Safety (EHS) perspective
class AssessmentScreeningAgentB(BaseAgent):
    """Assessment Screening Expert Agent B
    Responsible for comprehensively evaluating all aspects of material proposals,
    focusing on environmental impact and human health risk assessment
    """

    def __init__(self, llm):
        # Lazily import the Config class to avoid circular import issues, ensuring config is loaded only when needed
        from src.config.config import Config
        # Call the BaseAgent constructor, passing all core agent parameters
        super().__init__(
            llm=llm,
            # Role identifier: Assessment Screening Expert B, used to distinguish expert identities in multi-agent collaboration
            role="Assessment_Screening_agent_B",
            # Goal description: tells the agent that its core task is to comprehensively evaluate all aspects of material proposals
            goal="Comprehensively evaluate various aspects of material proposals",
            # Specifies the prompt template file (Markdown format) used by this agent; loaded and populated with parameters at runtime
            prompt_file="assessment_screening_agent_b_prompt.md",
            # Reads Expert B's dedicated temperature parameter from the config file, controlling the randomness of LLM output
            temperature=Config.EXPERT_B_TEMPERATURE,
            # Maximum iterations set to 2:
            # Following the "less is more" principle, greatly reduced from the original 15 to focus on the core evaluation logic
            max_iter=2,
            # Prompt parameters: replaces EXPERT_ID with "B" so the placeholder in the prompt template is correctly filled
            prompt_params={"EXPERT_ID": "B"}
        )

    def create_agent(self):
        # LLM selection (EAS / temperature-configured standard LLM / default LLM) has been unified in
        # BaseAgent._resolve_llm(), so it is not re-created here

        # Call the base class's create_agent method to complete the basic creation and configuration of the agent instance
        agent = super().create_agent()

        # Use the unified ASA (Assessment Screening Agent) assessment toolset
        # The ASA toolset is shared by the three experts A/B/C, providing chemical property queries, environmental assessment, etc.
        try:
            # Dynamically import the tools toggle check function to determine whether external tools are enabled
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # When tools are enabled: create the unified assessment toolset, including chemical database query capabilities
                agent.tools = ToolFactory.create_unified_assessment_tools()
            else:
                # When tools are not enabled: assign an empty list; the agent relies solely on its own knowledge for reasoning
                agent.tools = []
        except Exception:
            # If the tools_enabled check fails (e.g., missing config), enable the toolset by default
            # This is a fault-tolerant strategy of "rather use tools than miss information"
            agent.tools = ToolFactory.create_unified_assessment_tools()

        # Return the fully configured agent instance for use by the caller
        return agent
