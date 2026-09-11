#!/usr/bin/env python3
"""
Material Design Task — 材料设计任务
负责人工智能驱动的材料配方设计和优化，生成满足用户需求的水处理材料方案
"""

# 从基础任务模块导入基类和任务文本加载函数
from .base_task import BaseTask, load_task_text


class DesignTask(BaseTask):
    """材料设计任务类

    继承自 BaseTask，专门处理材料配方设计场景。
    负责根据用户需求（如处理目标、水质参数等）设计最优的材料组合方案。
    支持接收反馈进行迭代优化，以及接收上下文任务形成任务链。
    """

    def __init__(self, agent):
        """初始化材料设计任务

        在初始化时从 YAML 文件加载任务描述文本，
        然后调用父类构造函数设置 agent、expected_output 和 description。

        Args:
            agent: 材料设计 Agent，负责执行设计推理的 AI 代理
        """
        # 从 locales 目录加载设计任务的多语言文本配置
        # 包括任务描述、期望输出格式等
        task_text = load_task_text('design_task')

        # 调用父类构造函数初始化基础属性
        # expected_output 和 description 从 YAML 配置中获取，
        # 如果配置中不存在则使用空字符串作为默认值
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, feedback=None, user_requirement=None):
        """创建材料设计任务实例

        与父类相比，此方法增强了以下功能：
        1. 支持注入用户需求文本到任务描述中
        2. 支持注入反馈信息以实现迭代优化
        3. 支持设置上下文依赖任务（context_task），实现任务链

        Args:
            agent: 执行该任务的 Agent 实例
            context_task: 前置任务或任务列表，当前任务需要等待这些任务完成后才执行
            feedback: 上一次迭代的反馈文本，用于指导重新设计
            user_requirement: 用户的具体材料需求描述

        Returns:
            Task: 配置好的 CrewAI Task 实例
        """
        # 从 YAML 文件加载任务文本模板
        # 每次调用都重新加载，确保获取最新的配置
        task_text = load_task_text('design_task')

        # 提取各文本片段，如果 YAML 中未定义则使用空字符串作为默认值
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        # 用户需求前缀：在描述中标识用户需求部分的引导文字
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')
        # 反馈前缀：在描述中标识反馈信息部分的引导文字
        feedback_prefix = task_text.get('feedback_prefix', '\n\nFeedback:\n')

        # 如果传入了用户需求，将其追加到任务描述的末尾
        # 这样 Agent 在阅读任务描述时就能看到具体的用户需求
        if user_requirement:
            description += f"{user_req_prefix}{user_requirement}"

        # 如果传入了反馈信息，同样追加到描述末尾
        # 反馈用于告知 Agent 上一轮设计的不足之处，引导其改进
        if feedback:
            description += f"{feedback_prefix}{feedback}"

        # 创建 CrewAI Task 实例
        # 使用延迟导入避免模块级别的循环依赖
        from crewai import Task
        task = Task(
            agent=agent,
            expected_output=expected_output,
            description=description
        )

        # 设置任务上下文依赖
        # context_task 表示当前任务需要等待这些前置任务完成后才能执行
        # CrewAI 会根据 context 自动编排任务执行顺序
        if context_task:
            # 如果 context_task 已经是列表，直接赋值
            if isinstance(context_task, list):
                task.context = context_task
            else:
                # 如果是单个任务，包装成列表
                # CrewAI 期望 context 属性是一个任务列表
                task.context = [context_task]

        return task
