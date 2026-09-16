#!/usr/bin/env python3
"""
Final Validation Task — Final validation task
Integrates the evaluation opinions of domain experts and produces the final
comprehensive validation conclusion and improvement suggestions
"""

# Import the base class and the task text loading function from the base task module
from .base_task import BaseTask, load_task_text


class FinalValidationTask(BaseTask):
    """Final validation task class

    Inherits from BaseTask and serves as the last stage of the task pipeline.
    It aggregates multi-dimensional evaluation results such as mechanism analysis,
    synthesis methods, and operational recommendations, makes a comprehensive
    judgment, and generates the final validation report and optimization
    suggestions. This is the quality-control gate of the entire material design
    workflow.
    """

    def __init__(self, agent, evaluation_results=""):
        """Initialize the final validation task

        Args:
            agent: The final validation Agent, an AI agent responsible for
                   comprehensive judgment
            evaluation_results: Aggregated text of evaluation results from
                                domain experts; a reserved parameter that is
                                not directly used in the current implementation
        """
        # Load the multilingual text configuration for the final validation
        # task from the locales directory
        task_text = load_task_text('final_validation_task')

        # Call the parent class constructor
        # The evaluation_results parameter is declared in the current
        # implementation but is not concatenated into the description
        # The actual evaluation results are passed to the Agent via the
        # context_task mechanism
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """Create an instance of the final validation task

        Receives the outputs of multiple upstream tasks as context and
        performs a comprehensive validation. Typically, context_task contains
        the outputs of the mechanism analysis task, the synthesis method task,
        and the operational recommendation task; the validation Agent must
        consider all dimensions together.

        Args:
            agent: The Agent instance that executes this task
            context_task: List of outputs from upstream evaluation tasks,
                          providing all the information needed for validation
            user_requirement: The original user requirement, used for
                              comparison and checking during final validation

        Returns:
            Task: A configured CrewAI Task instance
        """
        # Load the task text template from the YAML file
        task_text = load_task_text('final_validation_task')

        # Extract the individual text fragments
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # Inject the user requirement into the description so that the
        # validation Agent can make the final judgment against the original
        # requirement
        if user_requirement:
            description += f"{user_req_prefix}{user_requirement}"

        # Create the CrewAI Task instance
        from crewai import Task
        task = Task(
            agent=agent,
            expected_output=expected_output,
            description=description
        )

        # Set the task context dependencies
        # The final validation can only run after all evaluation tasks
        # have completed
        # context_task is typically a list containing the outputs of
        # multiple tasks
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
