#!/usr/bin/env python3
"""
Synthesis Method Task
Designs the synthesis method and process flow for materials, including raw
material selection, reaction conditions, post-processing steps, etc.
"""

# Import the base class and task text loader from the base task module
from .base_task import BaseTask, load_task_text


class SynthesisMethodTask(BaseTask):
    """Synthesis method task class.

    Inherits from BaseTask and focuses on planning and optimizing material
    synthesis routes. Responsible for designing feasible synthesis schemes
    for the designed material formulations, covering process details such
    as raw material ratios, reaction temperature/pressure/time, equipment
    selection, purification steps, and quality control methods.
    The synthesis scheme must consider industrial feasibility and
    cost-effectiveness.
    """

    def __init__(self, agent, material_info=""):
        """Initialize the synthesis method task.

        Args:
            agent: The synthesis method Agent, an AI agent responsible for
                   process route design
            material_info: Text describing the material for which the
                           synthesis method is to be designed; if provided,
                           it is appended to the end of the task description
        """
        # Load the multilingual text config for the synthesis method task
        # from the locales directory
        task_text = load_task_text('synthesis_method_task')

        # Call the parent class constructor
        # material_info contains the material formulation information, based
        # on which the Agent designs the corresponding synthesis process
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '') + f"\n{material_info}" if material_info else task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """Create a synthesis method task instance.

        The synthesis method task depends on the output of the design task;
        it must know exactly which material to synthesize before planning
        the corresponding process flow.

        Args:
            agent: The Agent instance executing this task
            context_task: The preceding task (usually the design task) that
                          provides the material formulation information
            user_requirement: The user's original requirement, used to account
                              for real-world application scenarios during
                              process design

        Returns:
            Task: A configured CrewAI Task instance
        """
        # Load the task text template from the YAML file
        task_text = load_task_text('synthesis_method_task')

        # Extract the individual text fragments
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # Append the user requirement to the description
        # Processing goals in the user requirement affect the choice of
        # synthesis process (e.g., scale, purity requirements)
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
        # Synthesis method design requires the material formulation first
        # in order to determine the synthesis route
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
