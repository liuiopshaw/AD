# =============================================================================
# Logging module: records runtime information for debugging and troubleshooting
# =============================================================================
import logging
from src.agents.base_agent import BaseAgent
from src.tools import ToolFactory

# Configure logging format and level: only WARNING and above are emitted,
# to avoid noise from excessive INFO/DEBUG messages
# Note: basicConfig only takes effect on the first call; subsequent calls
# do not alter the existing configuration
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)  # Get the logger for the current module, so log sources can be located


class ExtractingAgent(BaseAgent):
    """Literature processing agent

    An agent responsible for processing and analyzing scientific literature,
    extracting information relevant to material evaluation.

    In the multi-agent collaboration workflow, this agent receives the user's
    material requirements, retrieves and analyzes relevant technical literature,
    and provides background knowledge to support subsequent synthesis design
    and operational recommendations.
    """

    def __init__(self, llm):
        """Initialize the literature extraction agent.

        Sets up the agent's role, goal, and prompt template.
        Note: this agent's output supports downstream agents' decisions,
        so the temperature parameter is managed centrally via Config to
        ensure consistent and reliable output.

        Args:
            llm: The language model instance used as the agent's reasoning engine
        """
        # Lazy-import Config to avoid circular dependency issues
        # Config holds per-agent parameter settings such as temperature
        from src.config.config import Config
        super().__init__(
            llm=llm,
            role="Extracting_agent",  # Role name: literature processing expert, used for logging and identification
            goal="Process and analyze relevant technical literature to provide background information for material evaluation",  # Goal description: guides the LLM to extract and organize key information from the literature
            prompt_file="extractor_prompt.md",  # Prompt template file: defines this role's literature analysis method and output format
            temperature=Config.LITERATURE_PROCESSOR_TEMPERATURE  # Temperature parameter: read from the config file, controls the randomness of LLM output
            # Note: this agent does not set the max_iter parameter and uses BaseAgent's default
            # This means the literature extraction task may need more iterations to ensure information completeness
        )

    def create_agent(self):
        """Create and configure the agent instance, attaching the literature extraction tools.

        Execution flow of this method:
        1. First try to create an EAS (Elastic Algorithm Service) LLM instance for better performance
        2. If EAS is unavailable, fall back to the default LLM passed in at initialization
        3. Directly load the literature extraction toolset (no conditional check needed,
           since literature processing tools are generally required)

        Differences from other agents:
        - Does not check the tools_enabled switch; tools are always loaded
          (because literature retrieval is a core capability and must not be missing)
        - Does not set max_iter (uses the default, allowing more iterations for in-depth literature analysis)

        Returns:
            The configured agent instance with the literature extraction toolset attached
        """
        # ---- Phase 1: LLM selection has been unified into BaseAgent._resolve_llm() ----
        # The decision between EAS / temperature-configured standard LLM / default LLM
        # is made in the parent class; it is not recreated here

        # ---- Phase 2: call the parent class to create the base agent ----
        # The parent class's create_agent method loads the prompt and sets up the LangChain agent framework
        agent = super().create_agent()

        # ---- Phase 3: attach the literature extraction toolset ----
        # Use the standardized literature extraction toolset to help the agent
        # retrieve and analyze scientific literature
        # Note: unlike the other two agents, the tools_enabled switch is not checked here
        # because literature retrieval tools are this agent's core capability and must always be available
        agent.tools = ToolFactory.create_literature_extraction_tools()
        return agent
