#!/usr/bin/env python3
"""
Mechanism Analysis Task
Analyzes the mechanism of action of materials from a physicochemical
perspective, including pollutant removal mechanisms, reaction pathways, etc.
"""

# Import the base class and the task text loading function from the base task module
from .base_task import BaseTask, load_task_text


class MechanismAnalysisTask(BaseTask):
    """Mechanism analysis task class.

    Inherits from BaseTask and focuses on in-depth analysis of material
    mechanisms of action. Explains how a material removes target pollutants
    at the molecular/atomic level, including adsorption mechanisms, catalytic
    mechanisms, redox reaction pathways, etc. The analysis results help
    validate the scientific soundness of the design and provide a theoretical
    basis for subsequent optimization.
    """

    def __init__(self, agent, material_info=""):
        """Initialize the mechanism analysis task.

        Args:
            agent: The mechanism analysis agent, an AI agent responsible for
                   scientific mechanism reasoning
            material_info: Text describing the material to be analyzed;
                           if provided, it is appended to the end of the
                           task description
        """
        # Load the multilingual text configuration for the mechanism analysis task from the locales directory
        task_text = load_task_text('mechanism_analysis_task')

        # Call the parent class constructor
        # material_info provides contextual information about the material
        # to be analyzed, such as composition, structural features, and
        # target pollutant types
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '') + f"\n{material_info}" if material_info else task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """Create a mechanism analysis task instance.

        The mechanism analysis task usually depends on the output of the
        design task, since the specific material formulation must be known
        before its mechanism of action can be analyzed.

        Args:
            agent: The Agent instance executing this task
            context_task: The preceding task (usually the design task) that
                          provides the material formulation information
            user_requirement: The user's original requirement, used to align
                              the analysis with the treatment goals

        Returns:
            Task: A configured CrewAI Task instance
        """
        # Load the task text template from the YAML file
        task_text = load_task_text('mechanism_analysis_task')

        # Extract the individual text fragments
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # Append the user requirement to the description so the analysis
        # stays aligned with the user's treatment goals
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
        # Mechanism analysis requires the material design proposal first
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
