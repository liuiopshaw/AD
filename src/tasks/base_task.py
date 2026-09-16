#!/usr/bin/env python3
"""
Base Task Class

This module defines the base class for all tasks and utility functions
for loading task text. All concrete tasks (such as design, evaluation,
validation, etc.) inherit from BaseTask and create CrewAI Task objects
through a unified interface.
"""

import os
import yaml
from crewai import Task


def get_language():
    """Get the current language setting.

    Reads the LANGUAGE field from the project configuration to determine
    which language the task prompt text should use. If the configuration
    is unavailable or reading fails, defaults to 'zh' (Chinese).

    Returns:
        str: Language code, 'zh' or 'en'
    """
    try:
        # Deferred import to avoid circular dependencies — the Config module
        # may be initialized at a higher level
        from src.config.config import Config
        return getattr(Config, 'LANGUAGE', 'zh')
    except Exception:
        # Fall back to Chinese on exception, ensuring the system does not
        # crash due to configuration issues
        return 'zh'


def is_english():
    """Check whether English mode is currently active.

    A convenience wrapper around get_language() that avoids repeating
    comparison logic in business code.

    Returns:
        bool: True for English mode, False for Chinese mode
    """
    return get_language() == 'en'


def load_task_text(task_name):
    """Load task text from a YAML file.

    Based on the current language setting, loads the task description file
    for the corresponding language from the locales directory. The task text
    includes fields such as description, expected_output, and
    user_requirement_prefix, which are used to dynamically build task prompts.

    Loading priority:
    1. The YAML file for the current language
    2. Fall back to the Chinese (zh) YAML file
    3. If neither exists, return an empty dictionary

    Args:
        task_name: Task name, e.g. 'design_task', 'evaluation_task'.
                   Should correspond to a filename (without extension) under
                   the locales/<lang>/tasks/ directory

    Returns:
        dict: A dictionary containing fields such as description,
              expected_output, and user_requirement_prefix. Returns an empty
              dictionary if the file does not exist or parsing fails
    """
    lang = get_language()
    # Get the absolute path of the current file's directory, used to build
    # the locales directory path
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Build the YAML file path for the current language
    # Path format: src/locales/<lang>/tasks/<task_name>.yaml
    yaml_path = os.path.join(current_dir, '..', 'locales', lang, 'tasks', f'{task_name}.yaml')

    # If the YAML file for the current language does not exist, fall back
    # to the Chinese version. This ensures tasks still work even if the
    # translation is incomplete
    if not os.path.exists(yaml_path):
        yaml_path = os.path.join(current_dir, '..', 'locales', 'zh', 'tasks', f'{task_name}.yaml')

    # If the Chinese version also does not exist (should not happen in
    # theory), return an empty dictionary. Callers must handle the empty
    # dictionary case
    if not os.path.exists(yaml_path):
        return {}

    try:
        # Open the file with UTF-8 encoding to ensure Chinese characters
        # are read correctly
        with open(yaml_path, 'r', encoding='utf-8') as f:
            # yaml.safe_load is safer than yaml.load — it does not execute
            # arbitrary Python code
            return yaml.safe_load(f)
    except Exception as e:
        # Print a warning on parse failure instead of raising — allows the
        # system to run in a degraded mode
        print(f"Warning: Failed to load task text from {yaml_path}: {e}")
        return {}


class BaseTask:
    """Base class for all tasks.

    Encapsulates the basic attributes of a CrewAI Task (agent,
    expected_output, description) and provides a create_task() method to
    create CrewAI Task instances. Subclasses can override create_task()
    to add extra logic (such as context dependencies, feedback, etc.).
    """

    def __init__(self, agent, expected_output, description):
        """Initialize the base task.

        Sets the three core elements of a task:
        - agent: the AI Agent that executes this task, determining the
          execution style and domain expertise
        - expected_output: a description of the expected output format
          and content
        - description: a detailed task description that guides the Agent

        Args:
            agent: The CrewAI Agent instance responsible for this task
            expected_output: Text describing the expected output format
            description: Task description text
        """
        self.agent = agent
        self.expected_output = expected_output
        self.description = description

    def create_task(self):
        """Create and return a CrewAI Task instance.

        Builds a Task object from the current object's attributes. The
        CrewAI framework schedules an Agent to execute the task based on
        this Task object. Subclasses typically override this method to
        support advanced features such as context_task and feedback.

        Returns:
            Task: A CrewAI framework Task instance
        """
        return Task(
            agent=self.agent,
            expected_output=self.expected_output,
            description=self.description
        )
