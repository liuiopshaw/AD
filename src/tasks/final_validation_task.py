#!/usr/bin/env python3
"""
Final Validation Task — 最终验证任务
负责整合各领域专家的评估意见，给出最终的综合验证结论和改进建议
"""

# 从基础任务模块导入基类和任务文本加载函数
from .base_task import BaseTask, load_task_text


class FinalValidationTask(BaseTask):
    """最终验证任务类

    继承自 BaseTask，作为任务流水线的最后一个环节。
    负责汇总机制分析、合成方法、操作建议等多维度评估结果，
    进行综合判断，生成最终的验证报告和优化建议。
    这是整个材料设计流程的质量把关环节。
    """

    def __init__(self, agent, evaluation_results=""):
        """初始化最终验证任务

        Args:
            agent: 最终验证 Agent，负责综合判断的 AI 代理
            evaluation_results: 各领域专家的评估结果汇总文本
                                预留参数，当前实现中暂未直接使用
        """
        # 从 locales 目录加载最终验证任务的多语言文本配置
        task_text = load_task_text('final_validation_task')

        # 调用父类构造函数
        # evaluation_results 参数在当前实现中已声明但未拼接到 description 中
        # 实际的评估结果通过 context_task 机制传递给 Agent
        super().__init__(
            agent=agent,
            expected_output=task_text.get('expected_output', ''),
            description=task_text.get('description', '')
        )

    def create_task(self, agent, context_task=None, user_requirement=None):
        """创建最终验证任务实例

        接收多个上游任务的输出作为上下文，进行综合验证。
        通常 context_task 会包含机制分析任务、合成方法任务、
        操作建议任务的输出，验证 Agent 需要综合考虑所有维度。

        Args:
            agent: 执行该任务的 Agent 实例
            context_task: 上游各评估任务的输出列表，提供验证所需的全部信息
            user_requirement: 用户原始需求，用于最终验证时对比检查

        Returns:
            Task: 配置好的 CrewAI Task 实例
        """
        # 从 YAML 文件加载任务文本模板
        task_text = load_task_text('final_validation_task')

        # 提取各文本片段
        description = task_text.get('description', '')
        expected_output = task_text.get('expected_output', '')
        user_req_prefix = task_text.get('user_requirement_prefix', '\n\nUser Requirement: ')

        # 将用户需求注入描述，使验证 Agent 能对照原始需求进行最终判断
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
        # 最终验证需要等待所有评估任务完成后才能执行
        # context_task 通常是一个包含多个任务输出的列表
        if context_task:
            if isinstance(context_task, list):
                task.context = context_task
            else:
                task.context = [context_task]

        return task
