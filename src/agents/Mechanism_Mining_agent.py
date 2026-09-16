# Import the logging module to record runtime logs for debugging and tracing agent behavior
import logging
# Import the BaseAgent base class from the base_agent module in the current package (agents)
# The relative import (.) indicates that base_agent resides in the same directory as this file
from .base_agent import BaseAgent
# Import ToolFactory from the tools module to uniformly create and manage the toolset used by the agent
from src.tools import ToolFactory

# Configure basic logging parameters: set the log level to WARNING to filter out
# redundant INFO/DEBUG messages, so only warnings and higher-severity logs are emitted,
# avoiding excessive unnecessary console output
logging.basicConfig(level=logging.WARNING)
# Get the logger instance for the current module; all subsequent log output goes through this logger
logger = logging.getLogger(__name__)

# Mechanism mining expert class
# Inherits from BaseAgent, specializing in mining and analyzing the reaction mechanisms
# and kinetic characteristics of pollutant degradation
class MechanismMiningAgent(BaseAgent):
    """Mechanism mining expert agent
    Responsible for mining the reaction mechanisms and kinetic characteristics of pollutant
    degradation, revealing degradation pathways and key intermediates by analyzing material
    structure and chemical properties.
    """

    def __init__(self, llm):
        # Lazily import the Config class to avoid circular import issues at module load time
        from src.config.config import Config
        # Call the constructor of the base class BaseAgent, passing in all core agent parameters
        super().__init__(
            llm=llm,
            # Role identifier: mechanism mining expert, responsible for the chemical mechanism
            # analysis stage in multi-agent collaboration
            role="Mechanism_Mining_agent",
            # Goal description: explicitly tells the agent its core task,
            # focusing on mining the reaction mechanisms and kinetic characteristics
            # of pollutant degradation
            goal="Mine reaction mechanisms and kinetic characteristics of pollutant degradation",
            # Specify the prompt template file (Markdown format) used by this agent;
            # it is loaded and populated with parameters at runtime
            prompt_file="mechanism_mining_agent_prompt.md",
            # Read the mechanism expert's dedicated temperature parameter from the config file;
            # usually set to a low value to ensure rigor and consistency of mechanism analysis
            temperature=Config.MECHANISM_EXPERT_TEMPERATURE,
            # Maximum iterations set to 2:
            # following the "less is more" principle, reduced from the original 8 to 2.
            # This agent mainly reuses upstream analysis results (e.g., material
            # characterization, evaluation and screening) and only needs to perform
            # mechanism analysis on top of them, so excessive iterations are unnecessary
            max_iter=2
        )

    def create_agent(self):
        # LLM selection (EAS / standard LLM with temperature / default LLM) has been
        # consolidated into BaseAgent._resolve_llm(); it is not recreated here

        # Call the base class's create_agent method to complete the basic creation
        # and configuration of the agent instance; this loads the prompt, sets role
        # information, initializes the CrewAI agent, etc.
        agent = super().create_agent()

        # Use the toolset dedicated to mechanism analysis.
        # Unlike the evaluation and screening expert, the mechanism mining expert needs
        # tools focused on chemical structure analysis and reaction pathway computation
        try:
            # Dynamically import the tool-toggle check function to determine whether the
            # current environment is configured to enable external tools
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # When tools are enabled: create the toolset dedicated to mechanism analysis.
                # These tools typically include reaction pathway analysis, transition-state
                # computation, structure-activity relationship queries, etc.
                agent.tools = ToolFactory.create_mechanism_analysis_tools()
            else:
                # When tools are not enabled: assign an empty list;
                # the agent will rely solely on the chemical knowledge in its training
                # data to infer mechanisms
                agent.tools = []
        except Exception:
            # If the tools_enabled check itself fails (e.g., the config module is broken),
            # enable the toolset by default — a fault-tolerant strategy of "rather use
            # more tools than miss critical information"
            agent.tools = ToolFactory.create_mechanism_analysis_tools()

        # Return the fully configured mechanism mining agent instance for the caller to use
        return agent
