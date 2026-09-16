# =============================================================================
# Logging module: records program runtime information for debugging and troubleshooting
# =============================================================================
import logging
from src.agents.base_agent import BaseAgent
from src.tools import ToolFactory

# Configure log format and level: only logs at WARNING level and above are output,
# avoiding interference from excessive INFO/DEBUG messages
# Note: basicConfig only takes effect on the first call; subsequent calls do not affect existing configuration
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)  # Get the logger for the current module, making it easier to locate the log source


# Operation suggestion expert agent class
# This agent provides detailed operational guidance for material synthesis, production, and application
class OperationSuggestingAgent(BaseAgent):
    def __init__(self, llm):
        """Initialize the operation suggesting agent.

        Sets up the agent's role, target task, prompt template, and behavior parameters.
        This agent focuses on transforming upstream synthesis schemes into concrete, executable operation steps.

        Args:
            llm: Language model instance, serving as the agent's reasoning engine
        """
        # Lazily import Config to avoid circular dependency issues
        # Config contains agent-specific parameter configurations such as temperature
        from src.config.config import Config
        super().__init__(
            llm,
            "Operation_Suggesting_agent",  # Role name: operation suggestion expert, used for logging and identification
            "Provide detailed operational guidance for material synthesis, production and application",  # Goal description: guides the LLM to generate detailed operating procedures
            "operation_suggesting_agent_prompt.md",  # Prompt template file: contains the detailed system prompt for this role, defining its professional domain and behavioral norms
            temperature=Config.OPERATION_SUGGESTING_TEMPERATURE,  # Temperature parameter: read from the config file, controls the randomness of LLM output
            max_iter=2  # Maximum number of iterations: set to 2 (original value was 8), following the "less is more" principle
                        # Fewer iterations means: reusing upstream synthesis routes, focusing on refining operational details, and avoiding excessive repeated reasoning
        )

    def create_agent(self):
        """Create and configure the operation suggesting agent, attaching the required tools.

        The execution flow of this method:
        1. First try to create an EAS (Elastic Algorithm Service) LLM instance for better performance
        2. If EAS is unavailable, fall back to the default LLM passed in during initialization
        3. Decide whether to load the operation guidance toolset based on whether the endpoint supports tool calling

        Returns:
            The configured agent instance with chemical database query tools attached
        """
        # ---- Phase 1: LLM selection has been unified into BaseAgent._resolve_llm() ----
        # The decision between EAS / standard LLM with temperature / default LLM is made in the parent class, so it is not repeated here

        # ---- Phase 2: call the parent class to create the base agent ----
        # The parent class's create_agent method is responsible for loading the prompt and setting up the LangChain agent framework
        agent = super().create_agent()

        # ---- Phase 3: attach the operation guidance toolset ----
        # This toolset focuses on material parameter queries and reagent information retrieval,
        # helping the agent generate more precise operation suggestions (e.g., temperature, pressure, reagent dosage)
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # The endpoint supports tool calling: load the operation guidance toolset
                agent.tools = ToolFactory.create_operation_guidance_tools()
            else:
                # The endpoint does not support tool calling: clear the tool list to avoid runtime errors
                agent.tools = []
        except Exception:
            # If the import or call of tools_enabled fails, enable tools by default
            # This is a conservative fault-tolerance strategy: it is better to load extra tools than to leave the agent missing functionality
            agent.tools = ToolFactory.create_operation_guidance_tools()
        return agent
