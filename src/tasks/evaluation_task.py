#!/usr/bin/env python3
"""
Material Evaluation Task
Performs multi-dimensional evaluation of designed material candidates,
analyzing their performance, feasibility, cost, and other aspects.
"""

# Import the base class and the task text loader from the base task module
from .base_task import BaseTask, load_task_text


class EvaluationTask(BaseTask):
    """Material evaluation task class.

    Inherits from BaseTask and is dedicated to material candidate
    evaluation scenarios. It performs professional evaluation of the
    material candidates produced by the upstream design task, including
    performance metric analysis, feasibility verification, and cost
    estimation. The evaluation results serve as input to subsequent
    validation tasks.
    """

    def __init__(self, agent, material_info=""):
        """Initialize the material evaluation task.

        Injects the material information to be evaluated (material_info)
        into the task description, so that the Agent has the context of
        the evaluation subject at initialization time.

        Args:
            agent: The material evaluation Agent, the AI agent responsible
                for performing the evaluation analysis.
            material_info: Text describing the material to be evaluated;
                if empty, only the template description is used.
        """
        # Load the multilingual text configuration for the evaluation task
        # from the locales directory
        task_text = load_task_text('evaluation_task')

        # Call the parent class constructor
        # Note: if material_info is provided, it is appended to the end of
        # the description, so the Agent can directly see the specific
        # material information to be evaluated when receiving the task
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '') + f"\n{material_info}" if material_info else task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """Create a material evaluation task instance.

        Supports injecting the user requirement into the description and
        setting a context dependency task. The evaluation task usually
        depends on the output of the design task, so context_task is
        typically set to the design task instance.

        Args:
            agent: The Agent instance that executes this task.
            context_task: The preceding task (usually the design task);
                evaluation must wait for it to complete.
            user_requirement: The original user requirement text, used for
                cross-checking during evaluation.

        Returns:
            Task: A configured CrewAI Task instance.
        """
        # Load the task text template from the YAML file
        task_text = load_task_text('evaluation_task')

        # Extract each text fragment, falling back to defaults if undefined
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # Append the user requirement to the task description
        # The evaluation Agent needs to check the design candidate against
        # the original requirement to determine whether it meets the goals
        if user_requirement:
            description += f"{user_req_prefix}{user_requirement}"

        # Create the CrewAI Task instance
        from crewai import Task
        task = Task(
            agent=agent,
            expected_output=expected_output,
            description=description
        )

        # Set the task context dependency
        # The evaluation task must see the design candidate's output
        # before it can be evaluated
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
