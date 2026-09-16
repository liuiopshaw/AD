# Import the logging module for recording runtime log information of the agent
import logging
# Import the BaseAgent base class; AssessmentScreeningAgentA inherits from it to reuse common agent creation logic
from src.agents.base_agent import BaseAgent
# Import the ToolFactory class, used to create the toolset required for assessment and screening
from src.tools import ToolFactory

# Configure the global logging level of the logging module to WARNING,
# so that only warning- and error-level logs are output, avoiding INFO/DEBUG message flooding
logging.basicConfig(level=logging.WARNING)
# Get the logger instance for the current module; log output carries the module name for easy source tracing
logger = logging.getLogger(__name__)

# Assessment Screening Expert Agent A
# Expert A is an independent evaluator in the multi-expert assessment system,
# working in parallel with Experts B and C to evaluate material proposals from different dimensions
class AssessmentScreeningAgentA(BaseAgent):
    """Assessment Screening Agent A
       Responsible for comprehensively evaluating material design proposals from a specific perspective:
       - Works in parallel with other assessment experts (B, C)
       - Uses a unified assessment toolset
       - Distinguished from other experts' assessment perspectives via EXPERT_ID in prompt_params"""

    def __init__(self, llm):
        """Initialize Assessment Screening Agent A

        Args:
            llm: Language model instance, passed in externally (usually from Crew configuration or the main program)
        """
        # Lazily import the Config class to avoid circular import issues at module load time
        from src.config.config import Config
        # Call the constructor of the parent class BaseAgent, passing in the configuration specific to Assessment Agent A
        super().__init__(
            llm,  # Language model instance
            "Assessment_Screening_agent_A",  # Agent role name: Assessment Expert A
            "Comprehensively evaluate various aspects of material proposals",
            # Specify the prompt template file dedicated to Assessment Agent A
            "assessment_screening_agent_a_prompt.md",
            # Read the temperature parameter dedicated to Expert A from Config
            # A lower assessment temperature helps obtain more consistent and rational evaluation results
            temperature=Config.EXPERT_A_TEMPERATURE,
            # max_iter=2: performance optimization, drastically reduced from the original 15 iterations to 2
            # Design principle: Less is More — focus on core evaluation logic and avoid unnecessary repeated reasoning
            max_iter=2,
            # Parameterized substitution via prompt_params:
            # Replace the {EXPERT_ID} placeholder in the prompt template with "A"
            # This allows multiple experts (A/B/C) to share the same prompt template,
            # distinguishing their respective evaluation focuses only through different EXPERT_ID values
            prompt_params={"EXPERT_ID": "A"}
        )

    def create_agent(self):
        """Create and return the configured Agent instance for Assessment Expert A

        This method overrides the parent class's create_agent, adding:
        1. A creation attempt for the EAS (Elastic Algorithm Service) LLM
        2. Attachment of the unified assessment toolset

        Returns:
            Agent: The configured Agent instance for Assessment Expert A
        """
        # LLM selection (EAS / standard LLM with temperature / default LLM) has been
        # unified into BaseAgent._resolve_llm(); it is not created again here

        # Call the parent class BaseAgent's create_agent() to create the base Agent instance
        # The parent method handles backstory loading, parameter substitution (EXPERT_ID=A),
        # and appending of Memory-first guidance text
        agent = super().create_agent()
        # Attach the toolset: use the unified ASA assessment toolset (shared by Experts A/B/C)
        # The unified toolset ensures consistent tool capabilities across experts, making evaluation results more comparable
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # When tools are enabled: create the unified assessment toolset
                agent.tools = ToolFactory.create_unified_assessment_tools()
            else:
                # When tools are disabled: set to an empty list
                # The agent will rely entirely on LLM knowledge and the evaluation criteria in the backstory
                agent.tools = []
        except Exception:
            # On exception, enable tools by default (conservative strategy, prioritizing functional completeness)
            agent.tools = ToolFactory.create_unified_assessment_tools()

        return agent
