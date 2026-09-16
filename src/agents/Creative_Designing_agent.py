# Import the logging module for recording runtime log information of the agent
import logging
# Import the BaseAgent base class; CreativeDesigningAgent inherits from it to reuse common agent creation logic
from src.agents.base_agent import BaseAgent
# Import the ToolFactory class, used to create the toolset required for material design
from src.tools import ToolFactory

# Set the global logging level of the logging module to WARNING,
# so that only warning- and error-level logs are output, avoiding INFO/DEBUG flooding
logging.basicConfig(level=logging.WARNING)
# Get the logger instance for the current module; log output carries the module name for easier troubleshooting
logger = logging.getLogger(__name__)

# Material design expert agent class
# Responsible for creating and optimizing water treatment material solutions based on user requirements
class CreativeDesigningAgent(BaseAgent):
    """Creative Designing Agent
       Dedicated to water treatment material design tasks:
       - Generate material design solutions based on user requirements
       - Query material information from databases such as Materials Project
       - Output structured design results (chemical formula, crystal structure, physical properties, etc.)"""

    def __init__(self, llm):
        """Initialize the creative designing agent

        Args:
            llm: Language model instance, passed in externally (usually from the Crew configuration or main program)
        """
        # Lazily import the Config class to avoid circular import issues at module load time
        from src.config.config import Config
        # Call the constructor of the parent class BaseAgent, passing configuration parameters specific to the design agent
        super().__init__(
            llm=llm,
            role="Creative_Designing_agent",  # Agent role name: material design expert
            goal="Design and optimize water treatment material solutions, strictly following material type classification and structural description specifications",
            # Specify the prompt template file dedicated to the design agent
            prompt_file="creative_designing_agent_prompt.md",
            # Read the temperature parameter dedicated to material design from Config;
            # a higher temperature can increase the diversity/creativity of design solutions
            temperature=Config.MATERIAL_DESIGNER_TEMPERATURE,
            # max_iter=1: performance optimization, limited to only 1 iteration
            # The original value was 8; reducing the iteration count significantly lowers API call costs and speeds up responses
            max_iter=1
        )

    def create_agent(self):
        """Create and return a configured creative designing Agent instance

        This method overrides the parent class's create_agent, adding:
        1. An attempt to create an EAS (Elastic Algorithm Service) LLM
        2. Attachment of tools dedicated to material design
        3. Enhancement of the backstory (adding database query and tool usage guidance)

        Returns:
            Agent: The fully configured material design Agent instance
        """
        # LLM selection (EAS / standard LLM with temperature / default LLM) has been
        # unified into BaseAgent._resolve_llm(); it is no longer created repeatedly here

        # Call the parent class's create_agent() method to create the base Agent instance
        agent = super().create_agent()
        # Attach tools: decide whether to enable tool calls based on the environment
        # On DashScope-compatible endpoints, tool calls may return 500 errors, so a conditional check is needed
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # When tools are enabled: create the toolset dedicated to material design,
                # including Materials Project query, structure validation, and other tools
                agent.tools = ToolFactory.create_material_design_tools()
            else:
                # When tools are disabled: set to an empty list; the agent will rely entirely on LLM knowledge
                agent.tools = []
        except Exception:
            # On exception, enable tools by default (conservative strategy)
            agent.tools = ToolFactory.create_material_design_tools()

        # Enhance the backstory: append additional design output requirements and tool usage strategy after the original prompt
        agent.backstory += (
            "\n\nWhen outputting design results, include the following detailed information whenever possible:\n"
            "- Materials Project ID (mp-xxx) (if the material exists in the database)\n"
            "- Chemical formula and crystal structure description\n"
            "- Key physical properties (e.g., band gap, density)\n"
            "- Thermodynamic stability (height above convex hull)\n"
            "\nTool Usage Strategy (Rate Limiting & Reuse):\n"
            "- Prioritize reusing already-obtained structure validation or material identifier results; avoid duplicate database searches\n"
            "- Only call Materials Project search when essential information is missing, using minimal field sets\n"
            "- Limit result count for element combination queries to avoid large-scale data retrieval\n"
        )

        return agent
