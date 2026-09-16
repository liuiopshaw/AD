# =============================================================================
# Logging module: records runtime information for debugging and issue tracking
# =============================================================================
import logging
from src.agents.base_agent import BaseAgent
from src.tools import ToolFactory

# Configure log format and level: only WARNING and above are emitted, avoiding
# interference from excessive INFO/DEBUG messages
# Note: basicConfig only takes effect on the first call; subsequent calls do not
# affect the existing configuration
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)  # Get the logger for the current module, making it easy to locate log sources


class SynthesisGuidingAgent(BaseAgent):
    """Synthesis Guiding Agent

    This agent is dedicated to designing material synthesis methods and process flows.
    It inherits from BaseAgent and extends its capabilities with chemistry database tools,
    enabling it to query substance properties, synthesis routes, and other specialized data.

    In the multi-agent collaboration workflow, this agent receives material design results
    from upstream agents and outputs feasible synthesis plans for the downstream
    operation-guidance agent to use.
    """

    def __init__(self, llm):
        """Initialize the Synthesis Guiding Agent.

        Sets up the agent's role definition, goal, prompt template, and behavior parameters.
        Uses the temperature parameter predefined in Config to control the creativity
        and consistency of the output.

        Args:
            llm: Language model instance serving as the agent's reasoning engine
        """
        # Lazily import Config to avoid circular dependency issues
        # Config contains temperature and other parameter settings specific to each agent
        from src.config.config import Config
        super().__init__(
            llm,
            "Synthesis_Guiding_agent",  # Role name: synthesis methods expert, used for logging and identification
            "Design material synthesis methods and process flows",  # Goal description: guides the LLM's task direction
            "synthesis_guiding_agent_prompt.md",  # Prompt template file: contains the detailed system prompt for this role
            temperature=Config.SYNTHESIS_EXPERT_TEMPERATURE,  # Temperature parameter: read from the config file, controls the randomness of LLM output
            max_iter=2  # Maximum iterations: set to 2 (original value was 8), following the "less is more" principle
                        # Fewer iterations means: reuse upstream design results, focus on synthesis route planning, and avoid excessive repeated reasoning
        )

    def create_agent(self):
        """Create and configure the agent instance.

        The execution flow of this method:
        1. Preferentially attempt to create an EAS (Elastic Algorithm Service) LLM instance, since EAS provides higher performance and stability
        2. If EAS is unavailable, fall back to the default LLM passed in during initialization, ensuring the system still runs in degraded mode
        3. Decide whether to load the chemistry database query tools based on whether the endpoint supports tool calling

        Returns:
            The fully configured agent instance with the required tools attached
        """
        # ---- Phase 1: LLM selection has been consolidated into BaseAgent._resolve_llm() ----
        # The decision among EAS / temperature-configured standard LLM / default LLM is made in the parent class; it is not recreated here

        # ---- Phase 2: Call the parent class to create the base agent ----
        # The parent class's create_agent method is responsible for loading the prompt and setting up the LangChain agent framework
        agent = super().create_agent()

        # ---- Phase 3: Attach the chemistry database query tools ----
        # The tool set provides material search capabilities (e.g., substance property queries, synthesis route retrieval)
        # Note: DashScope-compatible endpoints may not support native tool calling (function calling)
        # Therefore, the tools_enabled switch must be checked first
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # The endpoint supports tool calling: load the material search tool set
                agent.tools = ToolFactory.create_material_search_tools()
            else:
                # The endpoint does not support tool calling: clear the tool list to avoid runtime errors
                agent.tools = []
        except Exception:
            # If importing or calling tools_enabled fails (e.g., missing configuration), enable tools by default
            # This is a conservative fault-tolerance strategy: it is better to load extra tools than to leave the agent lacking functionality
            agent.tools = ToolFactory.create_material_search_tools()
        return agent
