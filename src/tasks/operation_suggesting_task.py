#!/usr/bin/env python3
"""
Operation Suggesting Task
Provides detailed operational guidelines and process parameter suggestions
for the synthesis, production, and application of materials.
"""

# Import the base class and task text loading function from the base task module
from .base_task import BaseTask, load_task_text


class OperationSuggestingTask(BaseTask):
    """Task class for operation suggestions.

    Inherits from BaseTask and focuses on generating hands-on guidance.
    Based on upstream results such as mechanism analysis and synthesis
    methods, it provides concrete guidelines for operators, including
    control ranges for key process parameters, safety precautions,
    troubleshooting plans for common issues, equipment operation points,
    and quality-control inspection frequency.
    The goal is to turn theoretical plans into executable operations.
    """

    def __init__(self, agent, material_info=""):
        """Initialize the operation suggesting task.

        Args:
            agent: The operation suggestion Agent, an AI agent responsible
                   for generating hands-on guidance.
            material_info: Contextual information text about the material.
                           Note: in the current implementation, material_info
                           is not concatenated into the description; the actual
                           material information is passed to the Agent via the
                           context_task mechanism.
        """
        # Load the multilingual text configuration for the operation
        # suggesting task from the locales directory
        task_text = load_task_text('operation_suggesting_task')

        # Call the parent class constructor
        # The material_info parameter is retained but unused in the current implementation
        # The description uses only the YAML template content; specific
        # information is passed through context tasks
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """Create an operation suggesting task instance.

        The operation suggesting task is one of the final stages of the
        pipeline. It must take into account all preceding analysis results
        (mechanism, synthesis methods, etc.) in order to provide complete
        and accurate operational guidance.

        Args:
            agent: The Agent instance that executes this task.
            context_task: List of upstream tasks, typically including the
                outputs of mechanism analysis and synthesis method tasks.
            user_requirement: The user's original requirement, used to
                generate operation suggestions tailored to the actual scenario.

        Returns:
            Task: A configured CrewAI Task instance.
        """
        # Load the task text template from the YAML file
        task_text = load_task_text('operation_suggesting_task')

        # Extract the individual text fragments
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # Append the user requirement to the description
        # Operation suggestions need to be tailored to the specific user
        # scenario (e.g., processing scale, site conditions, etc.)
        if user_requirement:
            description += f"{user_req_prefix}{user_requirement}"

        # Create the CrewAI Task instance
        from crewai import Task
        task = Task(
            agent=agent,
            expected_output=expected_output,
            description=description
        )

        # Set up task context dependencies
        # Operation suggestions need to integrate multiple sources of
        # information; context_task usually contains outputs of several
        # upstream tasks
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
