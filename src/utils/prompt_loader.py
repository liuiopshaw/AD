# Logging module, used to output debug and error information during the loading process
import logging
# OS interface module, used to check whether a file exists (os.path.exists) and to read environment variables (os.getenv)
import os

# Configure the logger for this module, setting the log level to WARNING
# This filters out DEBUG/INFO level logs so that output only appears on warnings or errors
logging.basicConfig(level=logging.WARNING)
# Get the logger for the current module, used to output prompt file loading status and error information
logger = logging.getLogger(__name__)


def get_language():
    """
    Get the current application's language setting.

    Reads the LANGUAGE config option from the project's Config class first; if Config is unavailable, falls back to
    the LANGUAGE environment variable, and finally defaults to "zh" (Chinese).

    Returns:
        str: Language code, such as "zh" (Chinese) or "en" (English)
    """
    try:
        # Try to get the language setting from the project's Config class
        # This is the primary configuration source; users can control the interface language by modifying Config
        from src.config.config import Config
        return Config.LANGUAGE
    except Exception:
        # If Config is unavailable (e.g., during early stages before configuration is initialized, or in test environments),
        # read from the LANGUAGE environment variable of the operating system, defaulting to "zh"
        return os.getenv("LANGUAGE", "zh")


def load_prompt(file_path):
    """
    Load a Prompt file with multi-language support.

    Loading strategy:
    1. First, try to load the Prompt file for the current language from the `locales/{lang}/prompts/` directory.
    2. If the current language version does not exist and the current language is not English, fall back to
       `locales/en/prompts/` to load the English version, and log a WARNING (consistent with the en fallback
       strategy of the locales module).
    3. If the file is not found in either location, raise a FileNotFoundError, which is handled by the
       exception handling logic as a fallback.

    Args:
        file_path: Relative path of the Prompt file (relative to the prompts directory)

    Returns:
        str: The text content of the Prompt file; returns the default backstory text if the file is not found
    """
    try:
        # Get the current language setting to determine which language version of the Prompt to load
        lang = get_language()

        # Get the absolute directory path of the current file (prompt_loader.py)
        # This is the base point for building relative paths
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # Build the full path of the multi-language Prompt file
        # Path structure: src/locales/{language}/prompts/{filename}
        # For example, when lang="zh", the path is src/locales/zh/prompts/{file_path}
        locale_prompt_path = os.path.join(current_dir, "..", "locales", lang, "prompts", file_path)

        # Check whether the multi-language version of the Prompt file exists
        if os.path.exists(locale_prompt_path):
            # Open the file with UTF-8 encoding (ensures correct handling of Chinese characters)
            with open(locale_prompt_path, 'r', encoding='utf-8') as file:
                logger.debug(f"Loaded {lang} prompt: {file_path}")
                return file.read()  # Return the full file content as the Prompt text

        # When the current language version does not exist, fall back to the English Prompt directory
        # Fallback path: src/locales/en/prompts/{file_path}
        # Note: historically this fell back to the non-existent src/prompts/ directory; it has been corrected
        # to fall back to the en directory
        if lang != "en":
            en_prompt_path = os.path.join(current_dir, "..", "locales", "en", "prompts", file_path)

            # Check whether the English version of the Prompt file exists
            if os.path.exists(en_prompt_path):
                with open(en_prompt_path, 'r', encoding='utf-8') as file:
                    logger.warning(
                        f"Prompt file {file_path} not found for language '{lang}', "
                        f"falling back to English version"
                    )
                    return file.read()

        # The file was not found in either location; raise an exception
        raise FileNotFoundError(f"Prompt file not found: {file_path}")

    except FileNotFoundError:
        # Exception handling for file-not-found: log a warning and return the default Agent backstory
        # This ensures the system can continue running even if the Prompt file is missing (graceful degradation)
        logger.warning(f"Prompt file {file_path} not found, using default backstory")
        return get_default_backstory()
    except Exception as e:
        # Catch all other exceptions (such as encoding errors, permission errors, etc.),
        # log the error and return the default backstory, ensuring the system does not crash
        # due to a Prompt loading failure
        logger.error(f"Error occurred while loading Prompt file {file_path}: {str(e)}")
        return get_default_backstory()


def get_default_backstory():
    """
    Get the default backstory text for an Agent.

    When Prompt file loading fails, this function provides a fallback backstory so the Agent can still work
    normally. Currently the Chinese and English versions return the same text — a generic description of a
    professional project coordination expert role.

    Returns:
        str: The default Agent backstory text
    """
    # Get the current language setting so that different default texts can be returned for
    # different languages in the future
    lang = get_language()
    if lang == "en":
        # English default backstory
        return """You are a professional project coordination expert, familiar with all aspects of material design and evaluation.
You can intelligently select and coordinate relevant experts to participate in the work according to task requirements."""
    else:
        # Default backstory for Chinese and other languages (currently the same as English)
        return """You are a professional project coordination expert, familiar with all aspects of material design and evaluation.
You can intelligently select and coordinate relevant experts to participate in the work according to task requirements."""
