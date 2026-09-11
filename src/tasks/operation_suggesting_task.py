#!/usr/bin/env python3
"""
Operation Suggesting Task — 操作建议任务
负责为材料的合成、生产和应用提供详细的操作指南和工艺参数建议
"""

# 从基础任务模块导入基类和任务文本加载函数
from .base_task import BaseTask, load_task_text


class OperationSuggestingTask(BaseTask):
    """操作建议任务类

    继承自 BaseTask，专注于生成实操层面的指导建议。
    基于上游的机理分析、合成方法等结果，提供面向操作人员的具体指南，
    包括关键工艺参数控制范围、安全注意事项、常见问题处理方案、
    设备操作要点、质量控制检测频率等实践性内容。
    目的是将理论方案转化为可执行的操作为止。
    """

    def __init__(self, agent, material_info=""):
        """初始化操作建议任务

        Args:
            agent: 操作建议 Agent，负责生成实操指导的 AI 代理
            material_info: 材料相关的上下文信息文本
                           注意：当前实现中 material_info 未被拼接到 description 中
                           实际材料信息通过 context_task 机制传递给 Agent
        """
        # 从 locales 目录加载操作建议任务的多语言文本配置
        task_text = load_task_text('operation_suggesting_task')

        # 调用父类构造函数
        # material_info 参数在当前实现中保留但未使用
        # 描述仅使用 YAML 模板内容，具体信息通过上下文任务传递
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """创建操作建议任务实例

        操作建议任务是流水线的最末端环节之一，
        需要综合考虑前述所有分析结果（机理、合成方法等），
        才能给出完整、准确的操作指导。

        Args:
            agent: 执行该任务的 Agent 实例
            context_task: 上游任务列表，通常包括机理分析和合成方法等任务的输出
            user_requirement: 用户原始需求，用于生成贴合实际场景的操作建议

        Returns:
            Task: 配置好的 CrewAI Task 实例
        """
        # 从 YAML 文件加载任务文本模板
        task_text = load_task_text('operation_suggesting_task')

        # 提取各文本片段
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # 将用户需求追加到描述中
        # 操作建议需要针对具体的用户场景定制（如处理规模、场地条件等）
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
        # 操作建议需要综合多方信息，context_task 通常包含多个上游任务的输出
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
