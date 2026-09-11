#!/usr/bin/env python3
"""
Mechanism Analysis Task — 机理分析任务
负责从物理化学角度分析材料的作用机理，包括污染物去除机制、反应路径等
"""

# 从基础任务模块导入基类和任务文本加载函数
from .base_task import BaseTask, load_task_text


class MechanismAnalysisTask(BaseTask):
    """机理分析任务类

    继承自 BaseTask，专注于材料作用机理的深度分析。
    从分子/原子层面解释材料如何去除目标污染物，
    包括吸附机理、催化机理、氧化还原反应路径等。
    分析结果帮助验证设计的科学性，并为后续优化提供理论依据。
    """

    def __init__(self, agent, material_info=""):
        """初始化机理分析任务

        Args:
            agent: 机理分析 Agent，负责科学机理推理的 AI 代理
            material_info: 待分析的材料信息文本
                           如果提供，会拼接到任务描述的末尾
        """
        # 从 locales 目录加载机理分析任务的多语言文本配置
        task_text = load_task_text('mechanism_analysis_task')

        # 调用父类构造函数
        # material_info 用于提供待分析材料的上下文信息
        # 如材料成分、结构特征、目标污染物类型等
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '') + f"\n{material_info}" if material_info else task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """创建机理分析任务实例

        机理分析任务通常依赖于设计任务的输出，
        需要知道材料的具体配方才能分析其作用机理。

        Args:
            agent: 执行该任务的 Agent 实例
            context_task: 前置任务（通常是设计任务），提供材料配方信息
            user_requirement: 用户原始需求，用于在分析中对照处理目标

        Returns:
            Task: 配置好的 CrewAI Task 实例
        """
        # 从 YAML 文件加载任务文本模板
        task_text = load_task_text('mechanism_analysis_task')

        # 提取各文本片段
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # 将用户需求追加到描述中，使分析能紧扣用户的处理目标
        if user_requirement:
            description += f"{user_req_prefix}{user_requirement}"

        # 创建 CrewAI Task 实例
        from crewai import Task
        task = Task(
            agent=agent,
            expected_output=expected_output,
            description=description
        )

        # 设置任务上下文依赖
        # 机理分析需要先获取材料设计方案才能进行分析
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
