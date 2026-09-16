#!/usr/bin/env python3
"""
Material Design Task
Handles AI-driven material formulation design and optimization,
generating water treatment material solutions that meet user requirements.
"""

# Import the base class and task text loader from the base task module
from .base_task import BaseTask, load_task_text


class DesignTask(BaseTask):
    """Material design task class

    Inherits from BaseTask and specializes in material formulation design
    scenarios. Designs the optimal material combination based on user
    requirements (e.g., treatment targets, water quality parameters).
    Supports receiving feedback for iterative optimization, and receiving
    context tasks to form a task chain.
    """

    def __init__(self, agent):
        """Initialize the material design task

        Loads the task description text from a YAML file during
        initialization, then calls the parent constructor to set the
        agent, expected_output, and description.

        Args:
            agent: The material design agent, an AI agent responsible for
                performing the design reasoning
        """
        # Load the multilingual text configuration for the design task
        # from the locales directory, including the task description,
        # expected output format, etc.
        task_text = load_task_text('design_task')

        # Call the parent constructor to initialize the base attributes
        # expected_output and description are taken from the YAML config;
        # fall back to empty strings if they are not defined there
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, feedback=None, user_requirement=None):
        """Create a material design task instance

        Compared with the parent class, this method adds the following
        capabilities:
        1. Injecting user requirement text into the task description
        2. Injecting feedback information for iterative optimization
        3. Setting context dependency tasks (context_task) to form a task chain

        Args:
            agent: The Agent instance that executes this task
            context_task: A prerequisite task or list of tasks that must
                complete before this task runs
            feedback: Feedback text from the previous iteration, used to
                guide the redesign
            user_requirement: The user's specific material requirements

        Returns:
            Task: A configured CrewAI Task instance
        """
        # Load the task text templates from the YAML file
        # Reload on every call to ensure the latest configuration is used
        task_text = load_task_text('design_task')

        # Extract each text fragment; fall back to empty strings if not
        # defined in the YAML
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        # User requirement prefix: lead-in text marking the user
        # requirement section in the description
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')
        # Feedback prefix: lead-in text marking the feedback section in
        # the description
        feedback_prefix = task_text.get('feedback_prefix', '\n\nFeedback:\n')

        # If a user requirement was provided, append it to the end of the
        # task description so the Agent can see the specific requirements
        # when reading the description
        if user_requirement:
            description += f"{user_req_prefix}{user_requirement}"

        # If feedback was provided, append it to the description as well
        # The feedback tells the Agent about the shortcomings of the
        # previous design round, guiding it to improve
        if feedback:
            description += f"{feedback_prefix}{feedback}"

        # Create the CrewAI Task instance
        # Use a deferred import to avoid module-level circular dependencies
        from crewai import Task
        task = Task(
            agent=agent,
            expected_output=expected_output,
            description=description
        )

        # Set up task context dependencies
        # context_task means this task must wait for those prerequisite
        # tasks to finish before it can run; CrewAI automatically
        # orchestrates execution order based on context
        if context_task:
            # If context_task is already a list, assign it directly
            if isinstance(context_task, list):
                task.context = context_task
            else:
                # If it is a single task, wrap it in a list
                # CrewAI expects the context attribute to be a task list
                task.context = [context_task]

        return task
