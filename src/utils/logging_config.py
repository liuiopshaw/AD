"""
Unified Logging Configuration Module (Unified Logging Configuration)
Provides centralized log management for the ECOMATS project.
This module allows unified control over the output level, format, and destination
of all logs, avoiding the chaos caused by each module configuring its own logging.
"""

# Import the logging module from the Python standard library for log recording
import logging
# Import the sys module to access the standard output stream (stdout)
import sys

# List of Agent loggers to suppress
# These Agents produce a large volume of debug/info logs at runtime, which are not
# needed during normal use, so they are managed centrally for one-click silencing
# to reduce console output noise
AGENT_LOGGERS = [
    'src.agents.Creative_Designing_agent',
    'src.agents.Assessment_Screening_agent_A',
    'src.agents.Assessment_Screening_agent_B',
    'src.agents.Assessment_Screening_agent_C',
    'src.agents.Assessment_Screening_agent_Overall',
    'src.agents.Mechanism_Mining_agent',
    'src.agents.Synthesis_Guiding_agent',
    'src.agents.Operation_Suggesting_agent',
    'src.agents.task_organizing_agent',
    'src.agents.Extracting_agent',
]

# List of third-party library loggers to suppress
# These third-party libraries (e.g., httpx, openai) generate a large number of
# low-level network request and debug logs; they are set to WARNING level by default
# to avoid interfering with the application's main log output
THIRD_PARTY_LOGGERS = [
    'httpx',          # HTTP client library; every request produces a large number of DEBUG logs
    'openai',         # OpenAI API client library
    'chromadb',       # Vector database client library
    'urllib3',        # HTTP connection pool library; low-level network logs
]


def setup_logging(level: int = logging.WARNING, suppress_agents: bool = True):
    """
    Configure the unified logging system for ECOMATS.

    This function should be called as early as possible at application startup
    to establish consistent logging behavior.

    Args:
        level: The log level of the root logger, defaulting to WARNING.
               This means that by default only logs at WARNING level and above
               (ERROR, CRITICAL) will be output.
        suppress_agents: Whether to suppress the log output of each Agent, defaulting to True.
                         When set to True, all Agent loggers are set to CRITICAL level
                         (essentially no output).
    """
    # Configure the basic settings of the root logger
    # basicConfig is the entry-point configuration of the entire logging system,
    # setting the log level, output format, and output destination
    # Format description: %(asctime)s = timestamp, %(name)s = logger name,
    #           %(levelname)s = log level name, %(message)s = log message
    logging.basicConfig(
        level=level,                                          # Set the level threshold of the root logger
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Unified log output format
        handlers=[logging.StreamHandler(sys.stdout)]           # Output logs to the standard output stream
    )

    if suppress_agents:
        # Raise the output level of all Agent loggers to CRITICAL
        # CRITICAL is the highest level; Agents normally do not emit CRITICAL logs,
        # so this effectively silences all Agent log output
        for logger_name in AGENT_LOGGERS:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL)

    # Set the level of third-party library loggers to WARNING
    # This way, logs are only output when a third-party library issues a warning
    # or error, while normal request/response logs (DEBUG/INFO level) are filtered out
    for logger_name in THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the specified name.

    This is the unified entry point for each module to obtain a logger. The recommended
    calling convention is get_logger(__name__), so that each module's logger name
    automatically maps to its module path.

    Args:
        name: The logger name, usually passing __name__ (the full path name of the current module)

    Returns:
        logging.Logger: A configured logger instance. If setup_logging() has been called
                        previously, it inherits the root logger's configuration.
    """
    # getLogger is idempotent: the same name returns the same Logger instance
    # This ensures consistent log settings within the same module
    return logging.getLogger(name)
