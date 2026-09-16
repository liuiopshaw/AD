# Import the logging module for recording runtime logs, making it easier to debug and trace agent behavior
import logging
# Import the BaseAgent base class from the base_agent module of the current package (agents)
# Use a relative import (.), indicating that base_agent is in the same directory as this file
from .base_agent import BaseAgent
# Import ToolFactory from the tools module, used to uniformly create and manage the tool set used by the agent
from src.tools import ToolFactory

# Configure basic logging parameters: set the log level to WARNING, filtering out redundant INFO/DEBUG messages
# This way only warnings and higher-level logs are output, avoiding excessive unnecessary console output
logging.basicConfig(level=logging.WARNING)
# Get the logger instance for the current module; all subsequent log output goes through this logger
logger = logging.getLogger(__name__)

# Comprehensive assessment and screening expert class (final aggregation expert)
# Inherits from BaseAgent; it does not evaluate materials directly, but aggregates the evaluation results
# of the three experts (A/B/C), performs weighted calculations and consistency analysis, and generates
# the final comprehensive evaluation report
class AssessmentScreeningAgentOverall(BaseAgent):
    """Comprehensive assessment and screening expert agent
    Responsible for aggregating the evaluation results of each expert, performing weighted calculations,
    and generating the final material evaluation report and improvement suggestions
    """

    def __init__(self, llm):
        # Lazily import the Config configuration class to avoid circular import issues at module load time
        from src.config.config import Config
        # Call the constructor of the base class BaseAgent, passing in all core parameters of the agent
        super().__init__(
            llm=llm,
            # Role identifier: comprehensive assessment and screening expert (final validation expert)
            # This is the last step in the multi-agent collaboration workflow, responsible for integrating all experts' opinions
            role="Assessment_Screening_agent_Overall",
            # Goal description: clearly tells the agent that its task is to aggregate expert results, perform weighted
            # calculations, and generate the final report; it must also provide improvement suggestions so that the
            # output contains not only evaluation conclusions but also actionable guidance
            goal="Synthesize evaluation results from various experts, perform weighted calculations, and generate final material evaluation report, while providing improvement suggestions",
            # Specify the prompt template file (Markdown format) used by this agent
            prompt_file="assessment_screening_agent_overall_prompt.md",
            # Read the dedicated temperature parameter for the final validation expert from the config file,
            # controlling the randomness of LLM output
            temperature=Config.FINAL_VALIDATOR_TEMPERATURE,
            # Maximum number of iterations set to 1:
            # Following the "less is more" principle, reduced from the original 8 iterations to 1,
            # because this agent only aggregates existing results and does not need iterative reasoning
            max_iter=1
        )

    def create_agent(self):
        # LLM selection (EAS / standard LLM with temperature / default LLM) has been unified into
        # BaseAgent._resolve_llm(); it is no longer created repeatedly here

        # Call the base class's create_agent method to complete the basic creation and configuration of the agent instance
        agent = super().create_agent()

        # Special handling for the ASA final validation expert:
        # This agent does not need any external tools; its sole responsibility is to aggregate the output
        # of the three ASA experts A/B/C, perform weighted calculations and consistency analysis,
        # and generate the final report
        # Therefore the tool list is set to empty, avoiding unnecessary tool calls interfering with the aggregation logic
        agent.tools = []

        # Enhance the prompt to clearly state its aggregation role:
        # Append an explanation after the existing backstory so the LLM clearly knows that:
        # 1. Its core responsibility is to collect the evaluation results of AssessmentScreeningAgentA, B, and C
        # 2. It needs to perform weighted calculations and consistency analysis
        # 3. It does not need to re-evaluate the material itself, only synthesize existing opinions
        # This prevents the LLM from re-evaluating, avoiding information redundancy and resource waste
        agent.backstory += "\n\nYour core responsibility is to collect evaluation results from three experts (AssessmentScreeningAgentA, B, C), perform weighted calculations and consistency analysis, and generate the final report. You do not need to re-evaluate the material itself, but synthesize existing opinions."

        # Return the fully configured comprehensive assessment agent instance for use by upstream callers
        return agent
