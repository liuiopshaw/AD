#!/usr/bin/env python3
# Line 1: Shebang declaration, specifying that this script is executed with the python3 interpreter
"""
LLM Configuration Tool.
Provides EAS model instance creation and CrewAI native LLM factory.
"""
# Lines 2-5: Module docstring, stating that this module handles LLM configuration and provides EAS model instance creation and the CrewAI native LLM factory function

import os
# Line 7: Import the os module for reading and setting environment variables
from dotenv import load_dotenv
# Line 8: Import load_dotenv for forcibly loading the .env file
from crewai import LLM as CrewLLM
# Line 9: Import the LLM class from the CrewAI framework, renamed to CrewLLM, used to create LLM instances compatible with the OpenAI interface
from ..config.config import Config
# Line 10: Import the Config configuration class from the parent config package to obtain default model parameters


def _ensure_openai_env():
    # Line 13: Internal function that ensures only DashScope-related environment variables are set
    # Purpose: avoid conflicts between OPENAI_* environment variables and the DashScope domestic endpoint
    """Disable bridging of OPENAI_* environment variables to avoid conflicts between domestic sites and OpenAI defaults."""
    # Line 14: Function docstring
    # Line 16: Only when QWEN_API_KEY exists and DASHSCOPE_API_KEY is not set, copy QWEN_API_KEY to DASHSCOPE_API_KEY
    if Config.QWEN_API_KEY and not os.getenv("DASHSCOPE_API_KEY"):
        os.environ["DASHSCOPE_API_KEY"] = Config.QWEN_API_KEY


def _resolve_base_url():
    # Line 20: Internal function that resolves the available base_url, strictly using QWEN_API_BASE
    # Read from environment variables first, then fall back to the Config class default value
    """Resolve available base_url (strictly use QWEN_API_BASE)."""
    return os.getenv("QWEN_API_BASE") or Config.QWEN_API_BASE


def _resolve_api_key():
    # Line 25: Internal function that resolves the available API key
    # Try in priority order: QWEN_API_KEY -> DASHSCOPE_API_KEY -> Config.QWEN_API_KEY
    """Resolve available api_key (strictly use QWEN_API_KEY or DASHSCOPE_API_KEY)."""
    return os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or Config.QWEN_API_KEY

def _force_load_env():
    # Line 29: Internal function that forcibly loads the .env file from the project root directory (override=True)
    # Resolves inconsistent environment variables between the IDE and the terminal
    try:
        # Line 31: Compute the project root path (this file is located in src/utils/, two levels up from the project root)
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        # Line 32: Build the full path of the .env file
        dotenv_path = os.path.join(project_root, '.env')
        # Line 33: Load the .env file in override mode, ensuring file values take precedence over current environment variables
        load_dotenv(dotenv_path, override=True)
    except Exception:
        # Lines 34-35: Silently ignore load failures (e.g., the .env file does not exist)
        pass

def create_llm(temperature=None, max_tokens=None, agent_name=None):
    # Line 37: Factory function that creates a CrewAI native LLM instance
    # Parameter temperature: model temperature (optional), controls output randomness
    # Parameter max_tokens: maximum number of output tokens (optional)
    # Parameter agent_name: LoRA adapter name (optional), only takes effect when LLAVA_API_BASE is explicitly configured,
    #   and must match the adapter names in scripts/llava_server.py (ea/apa/epa/bsa/mma/toa/ca/cda/base)
    # Returns: a configured CrewLLM instance
    """
    Create and configure language model instance (CrewAI native).

    Args:
        temperature (float, optional): Model temperature parameter, controlling output randomness
        max_tokens (int, optional): Maximum token limit
        agent_name (str, optional): LoRA adapter name; only used when LLAVA_API_BASE
            is explicitly set, passed to llava_server via the request body `agent` field

    Returns:
        CrewLLM: Configured language model instance
    """
    # Lines 48-49: First forcibly load the .env file to ensure environment variables are up to date
    _force_load_env()
    # Line 51: Set DashScope-specific environment variables to avoid OPENAI_* interference
    _ensure_openai_env()

    # ---- LoRA routing (optional, does not change existing behavior by default) ----
    # If and only if the environment variable LLAVA_API_BASE is explicitly set (non-empty),
    # route requests to the OpenAI-compatible endpoint provided by
    # scripts/llava_server.py (FastAPI + PEFT multi-adapter service),
    # using LLAVA_MODEL_NAME as the model name. Note that os.getenv is read directly
    # instead of the Config class attribute, because Config provides a non-empty default
    # value for LLAVA_API_BASE, and only explicit configuration should trigger routing.
    # The server switches the LoRA adapter based on the agent field in the request body:
    # the LLM class of CrewAI 1.7.0+ supports additional_params (merged as-is into the
    # chat.completions request body), so agent_name is passed to the server via
    # additional_params; if the current CrewAI version does not support
    # additional_params, only base_url/model are passed and the server uses its default adapter.
    llava_base = os.getenv("LLAVA_API_BASE")
    if llava_base:
        model_name = os.getenv("LLAVA_MODEL_NAME") or Config.LLAVA_MODEL_NAME
        llm_kwargs = dict(
            model=model_name,
            base_url=llava_base,
            # llava_server.py does not validate the key, but litellm requires a non-empty one,
            # so prefer reusing the configured key, otherwise use a placeholder value
            api_key=_resolve_api_key() or "EMPTY",
            temperature=temperature or Config.MODEL_TEMPERATURE,
            max_tokens=max_tokens or Config.MODEL_MAX_TOKENS,
        )
        if agent_name and "additional_params" in CrewLLM.model_fields:
            llm_kwargs["additional_params"] = {"agent": agent_name}
        elif agent_name:
            # The current CrewAI version does not support additional_params: the agent field cannot be passed,
            # and the server will use its default adapter (default "ea" in llava_server.py)
            pass
        return CrewLLM(**llm_kwargs)

    # Line 54: Get the model name, defaulting to "qwen-plus" (a stable commercial model)
    model_name = Config.QWEN_MODEL_NAME or "qwen-plus"
    # Lines 55-56: Safety check; raise an exception if the model name is empty
    if not model_name:
        raise ValueError("QWEN_MODEL_NAME not set in environment variables")
    # Line 58: Resolve the API key
    api_key = _resolve_api_key()
    # Lines 59-60: Safety check; raise an exception with configuration guidance if the key is empty
    if not api_key:
        raise ValueError("API key not detected, please set QWEN_API_KEY in .env or export OPENAI_API_KEY/DASHSCOPE_API_KEY")
    # Line 61: Resolve base_url, respecting user configuration without any endpoint rewriting
    base_url = _resolve_base_url()

    # Lines 68-74: Create an instance using the CrewAI native LLM class
    # Parameter description: model=model name, base_url=API endpoint, api_key=key,
    # temperature=temperature (prefer the passed-in value, otherwise use the Config default),
    # max_tokens=maximum token count (prefer the passed-in value, otherwise use the Config default)
    llm = CrewLLM(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature or Config.MODEL_TEMPERATURE,
        max_tokens=max_tokens or Config.MODEL_MAX_TOKENS,
    )

    # Line 76: Return the configured LLM instance
    return llm

def create_eas_llm(temperature=None):
    # Line 78: Factory function that creates an EAS (Elastic Algorithm Service) self-deployed model instance
    # EAS is Alibaba Cloud's model hosting service, allowing users to deploy custom models
    # Parameter temperature: model temperature (optional)
    # Returns: a configured CrewLLM instance pointing to the self-deployed EAS endpoint
    """Create EAS model instance.

    Returns:
        CrewLLM: EAS model instance
    """
    # Lines 84-85: First forcibly load the .env file
    _force_load_env()
    # Lines 87-88: Check whether the required EAS configuration exists; raise an exception if any item is missing
    if not Config.EAS_ENDPOINT or not Config.EAS_TOKEN:
        raise ValueError("EAS config not set, please configure valid EAS_ENDPOINT and EAS_TOKEN in .env file")

    # Line 91: Get the EAS model name
    model_name = Config.EAS_MODEL_NAME
    # Lines 92-93: Safety check; the model name cannot be empty
    if not model_name:
        raise ValueError("EAS_MODEL_NAME not set in environment variables")

    # Line 96: Use the configured EAS endpoint as base_url (no extra path suffix appended)
    base_url = Config.EAS_ENDPOINT

    try:
        # Lines 101-108: Create the EAS model instance
        # Use Config.EAS_TOKEN as api_key; the remaining parameters are the same as in create_llm
        eas_llm = CrewLLM(
            model=model_name,
            base_url=base_url,
            api_key=Config.EAS_TOKEN,
            temperature=temperature or Config.MODEL_TEMPERATURE,
            max_tokens=Config.MODEL_MAX_TOKENS,
        )
        # Line 108: Return the EAS LLM instance
        return eas_llm
    except Exception as e:
        # Lines 109-111: Print the error message and re-raise the exception when creation fails
        print(f"Failed to create EAS model instance: {e}")
        raise

def tools_enabled() -> bool:
    # Line 113: Function that determines whether tool calling is enabled
    # Return value: True means tool calling is enabled, False means disabled
    # Logic:
    # 1. If the environment variable ENABLE_TOOLS is set, return its boolean value directly
    # 2. If using the DashScope compatible-mode endpoint, disable by default (because compatible mode does not support function calling)
    # 3. Otherwise enable by default
    """Determine whether to enable tool calls based on endpoint and environment variables.
    - If `ENABLE_TOOLS=false` is set, disable
    - If endpoint is DashScope compatible mode (contains `dashscope` and `compatible-mode`), disable by default
    - Otherwise enable by default.
    """
    # Line 119: Read the ENABLE_TOOLS environment variable
    env = os.getenv("ENABLE_TOOLS")
    # Lines 120-121: If this variable is set, return its boolean value ("true" -> True, anything else -> False)
    if env is not None:
        return env.lower() == "true"
    # Line 122: Get the currently used base_url
    base = _resolve_base_url() or ""
    # Lines 123-124: If the endpoint URL contains both "dashscope" and "compatible-mode", it is DashScope compatible mode
    # This mode does not support native function calling, so tool calling is disabled by default to avoid 500 errors
    if "dashscope" in base and "compatible-mode" in base:
        return False
    # Line 125: Other endpoints enable tool calling by default
    return True
