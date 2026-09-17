#!/usr/bin/env python3
"""Delivery-efficiency evaluation task for the delivery scoring agent."""

from .base_task import BaseTask, load_task_text
from crewai import Task


class EnzymeActivityTask(BaseTask):
    def __init__(self, agent):
        task_text = load_task_text('enzyme_activity_task')
        super().__init__(agent=agent, expected_output=task_text.get('expected_output', ''),
                         description=task_text.get('description', ''))

    def create_task(self, agent, context_task=None, user_requirement=None):
        task_text = load_task_text('enzyme_activity_task')
        desc = task_text.get('description', '')
        if user_requirement:
            desc = f"{desc}\n{task_text.get('user_requirement_prefix', '')}{user_requirement}"
        task = Task(agent=agent, expected_output=task_text.get('expected_output', ''),
                    description=desc)
        if context_task:
            task.context = [context_task] if not isinstance(context_task, list) else context_task
        return task
