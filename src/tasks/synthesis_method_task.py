#!/usr/bin/env python3
"""
Synthesis Method Task — 合成方法任务
负责设计材料的合成方法和工艺流程，包括原料选择、反应条件、后处理步骤等
"""

# 从基础任务模块导入基类和任务文本加载函数
from .base_task import BaseTask, load_task_text


class SynthesisMethodTask(BaseTask):
    """合成方法任务类

    继承自 BaseTask，专注于材料合成路线的规划和优化。
    负责为设计出的材料配方设计可行的合成方案，
    包括原料配比、反应温度/压力/时间、设备选型、
    纯化步骤、质量控制方法等工艺细节。
    合成方案需要考虑工业化可行性和成本效益。
    """

    def __init__(self, agent, material_info=""):
        """初始化合成方法任务

        Args:
            agent: 合成方法 Agent，负责工艺路线设计的 AI 代理
            material_info: 待设计合成方法的材料信息文本
                           如果提供，会拼接到任务描述的末尾
        """
        # 从 locales 目录加载合成方法任务的多语言文本配置
        task_text = load_task_text('synthesis_method_task')

        # 调用父类构造函数
        # material_info 包含材料配方信息，Agent 据此设计对应的合成工艺
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '') + f"\n{material_info}" if material_info else task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """创建合成方法任务实例

        合成方法任务依赖于设计任务的输出，
        需要明确知道要合成什么材料才能规划相应的工艺流程。

        Args:
            agent: 执行该任务的 Agent 实例
            context_task: 前置任务（通常是设计任务），提供材料配方信息
            user_requirement: 用户原始需求，用于在工艺设计时考虑实际应用场景

        Returns:
            Task: 配置好的 CrewAI Task 实例
        """
        # 从 YAML 文件加载任务文本模板
        task_text = load_task_text('synthesis_method_task')

        # 提取各文本片段
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # 将用户需求追加到描述中
        # 用户需求中的处理目标会影响合成工艺的选择（如规模、纯度要求等）
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
        # 合成方法设计需要先获取材料配方才能确定合成路线
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
