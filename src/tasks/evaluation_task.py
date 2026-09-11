#!/usr/bin/env python3
"""
Material Evaluation Task — 材料评估任务
负责对设计出的材料方案进行多维度评估，分析其性能、可行性、成本等方面
"""

# 从基础任务模块导入基类和任务文本加载函数
from .base_task import BaseTask, load_task_text


class EvaluationTask(BaseTask):
    """材料评估任务类

    继承自 BaseTask，专门处理材料方案评估场景。
    负责对上游设计任务产出的材料方案进行专业评估，
    包括性能指标分析、可行性验证、成本估算等。
    评估结果将作为后续验证任务的输入。
    """

    def __init__(self, agent, material_info=""):
        """初始化材料评估任务

        将待评估的材料信息（material_info）注入到任务描述中，
        使 Agent 在初始化时就能获取评估对象的上下文。

        Args:
            agent: 材料评估 Agent，负责执行评估分析的 AI 代理
            material_info: 待评估的材料信息文本，如果为空则仅使用模板描述
        """
        # 从 locales 目录加载评估任务的多语言文本配置
        task_text = load_task_text('evaluation_task')

        # 调用父类构造函数
        # 注意：如果提供了 material_info，会将其拼接到 description 的末尾
        # 这样 Agent 在收到任务时就能直接看到待评估的具体材料信息
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '') + f"\n{material_info}" if material_info else task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """创建材料评估任务实例

        支持注入用户需求到描述中，以及设置上下文依赖任务。
        评估任务通常依赖于设计任务的输出，因此 context_task
        通常设置为设计任务实例。

        Args:
            agent: 执行该任务的 Agent 实例
            context_task: 前置任务（通常是设计任务），评估需等待其完成
            user_requirement: 用户原始需求文本，用于在评估时对照检查

        Returns:
            Task: 配置好的 CrewAI Task 实例
        """
        # 从 YAML 文件加载任务文本模板
        task_text = load_task_text('evaluation_task')

        # 提取各文本片段，未定义时使用默认值
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # 将用户需求追加到任务描述中
        # 评估 Agent 需要对照原始需求来判断设计方案是否达标
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
        # 评估任务需要先看到设计方案的输出才能进行评估
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
