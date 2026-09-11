#!/usr/bin/env python3
"""Antimicrobial evaluation task for APA agent."""

from .base_task import BaseTask, load_task_text


class AntimicrobialTask(BaseTask):
    """Task for selective antibacterial performance evaluation."""

    def __init__(self, agent):
        task_text = load_task_text('antimicrobial_task')
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        task_text = load_task_text('antimicrobial_task')
        desc = task_text.get('description', '')
        if user_requirement:
            prefix = task_text.get('user_requirement_prefix', '')
            desc = f"{desc}\n{prefix}{user_requirement}"

        from crewai import Task
        task = Task(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=desc
        )
        if context_task:
            task.context = [context_task] if not isinstance(context_task, list) else context_task
        return task
