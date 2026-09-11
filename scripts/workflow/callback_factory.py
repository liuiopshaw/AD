"""
Task Callback Factory.
Creates callbacks for monitoring parallel task execution.

This module provides a factory function that creates CrewAI task callbacks
with special handling for parallel task timing. When multiple tasks execute
concurrently (e.g., evaluation agents A/B/C), the factory correctly assigns
shared start times to the parallel group instead of sequential timing.
"""

# time: 用于记录任务执行的时间戳和计算耗时
import time


def create_task_callback_factory(monitor, task_start_times, current_agent_context, last_completed_agent):
    """
    创建任务回调工厂函数（支持并行任务的时间跟踪）

    这个工厂函数的核心设计目标是正确处理并行任务的计时问题：
    当 A、B、C 三位评估专家并行执行时，它们应当共享同一个开始时间
    （设计任务完成的时间点），而不是各自独立计时。

    工厂返回一个闭包函数 create_task_callback，该函数每次被调用时
    返回一个新的 task_callback 实例。这种设计允许为不同的 Crew
    实例创建互不干扰的回调函数。

    关键设计：
    - 需要传入 task_completion_times 等上下文，因为同一程序可能创建多个 Crew
    - eval_start_key 用于标记评估组的共享起始时间
    - last_completed_agent 用于追踪 Agent 间的交互关系

    Args:
        monitor: WorkflowMonitor 实例——接收执行报告的监控器
        task_start_times: 字典——记录每个任务的开始时间
        current_agent_context: threading.local 实例——线程局部存储当前 Agent
        last_completed_agent: 列表——记录最后完成任务的 Agent 角色

    Returns:
        function: 工厂函数 create_task_callback(task_completion_times, crew_start_time, task_counter, suffix="")
    """

    def create_task_callback(task_completion_times, crew_start_time, task_counter, suffix=""):
        """
        创建具体 Crew 实例的 task_callback 函数

        每个 Crew 需要自己的回调实例，因为它们有独立的：
        - task_completion_times: 任务完成时间列表（用于计算后续任务的起始时间）
        - crew_start_time: Crew 启动时间（列表包装，用于第一个任务的时间基准）
        - task_counter: 任务序号计数器（列表包装）

        suffix 参数允许为同一程序中的多个 Crew 创建不同命名空间的键，
        避免它们的计时信息互相覆盖。

        Args:
            task_completion_times: 任务完成时间点列表
            crew_start_time: 包含 Crew 启动时间的单元素列表
            task_counter: 任务序号计数器的单元素列表
            suffix: 用于区分多个 Crew 的键后缀（如 "_2"）

        Returns:
            function: task_callback(task_output) 回调函数
        """
        # 评估组的共享起始时间键名（带后缀区分不同 Crew）
        eval_start_key = f'eval_start_time{suffix}'

        def task_callback(task_output):
            """
            任务完成时的回调函数

            CrewAI 在每个任务完成后自动调用此回调，传入 TaskOutput 对象。
            回调完成以下工作：
            1. 递增任务序号
            2. 从 TaskOutput 中提取 Agent 信息
            3. 处理并行任务的计时逻辑（评估组共享起始时间）
            4. 通知监控器记录执行信息
            5. 记录 Agent 之间的交互关系（任务传递）

            Args:
                task_output: CrewAI 的 TaskOutput 对象
            """
            # 递增任务序号计数器（使用列表包装以在闭包中修改）
            task_counter[0] += 1
            task_id = task_counter[0]

            # 从 task_output 中提取 Agent 标识信息
            # agent 属性可能是字符串或 Agent 对象
            agent_str = getattr(task_output, 'agent', None) or 'Unknown'
            # 任务名称：优先使用 task_output.name，否则自动生成
            task_name = getattr(task_output, 'name', None) or f"{agent_str}_Task_{task_id}"
            # 任务描述（用于监控报告的详情）
            task_description = getattr(task_output, 'description', 'N/A')
            agent_name = agent_str
            agent_role = agent_str

            # 更新线程局部存储中的当前 Agent 角色
            # 供 step_callback 等函数读取当前上下文
            current_agent_context.role = agent_role

            # 尝试提取 JSON 格式的结构化输出（如评估分数、排名等）
            json_output = None
            if hasattr(task_output, 'json_dict') and task_output.json_dict:
                json_output = task_output.json_dict

            # 仅在监控器可用时进行详细的记录和计时
            if monitor:
                current_time = time.time()

                # ---- 并行任务计时逻辑 ----
                # 检测当前任务是否为并行评估任务（角色名以 A/B/C 结尾的 ASA 专家）
                is_parallel_eval = 'Assessment_Screening_agent_' in agent_role and agent_role[-1] in 'ABC'

                if is_parallel_eval:
                    # 并行评估任务的起始时间处理：
                    # 三位专家 (A/B/C) 共享同一个开始时间
                    # 如果 eval_start_key 尚未设置（这是评估组的第一个任务），
                    # 使用上一个任务完成时间或 Crew 启动时间作为起始时间
                    if eval_start_key not in task_start_times:
                        if task_completion_times:
                            # 使用上一个非评估任务（设计任务）的完成时间
                            task_start_times[eval_start_key] = task_completion_times[-1]
                        elif crew_start_time[0]:
                            # 如果还没有任务完成记录，使用 Crew 启动时间
                            task_start_times[eval_start_key] = crew_start_time[0]
                        else:
                            # 兜底：使用当前时间
                            task_start_times[eval_start_key] = current_time
                    # 所有评估任务复用同一个起始时间
                    actual_start = task_start_times[eval_start_key]
                else:
                    # 非并行任务的起始时间：
                    # 如果是第一个任务，使用 Crew 启动时间；否则使用上一个任务完成时间
                    if task_completion_times:
                        actual_start = task_completion_times[-1]
                    elif crew_start_time[0]:
                        actual_start = crew_start_time[0]
                    else:
                        actual_start = current_time

                # 记录当前任务的完成时间（供下一个任务计算起始时间）
                task_completion_times.append(current_time)

                # 使用 (agent_role, task_id) 作为任务的唯一键
                # 避免同类型的并行任务互相覆盖信息
                unique_task_key = f"{agent_role}_{task_id}"
                if unique_task_key not in task_start_times:
                    # 首次遇到此任务键——记录到监控器
                    task_start_times[unique_task_key] = actual_start
                    monitor.start_agent_execution(agent_name, agent_role, task_name, task_description)
                    # 如果监控器有当前执行记录，设置开始时间
                    if monitor._current_execution:
                        monitor._current_execution.start_time = actual_start

                # 结束 Agent 执行记录——传递输出内容供监控器保存
                monitor.end_agent_execution(output=str(task_output), json_output=json_output, agent_role=agent_role)

                # ---- Agent 交互关系记录 ----
                # 当上一个完成的 Agent 与当前 Agent 不同时，
                # 记录一次 "task_handoff"（任务交接）类型的交互
                # 这构建了工作流中 Agent 之间的信息传递图谱
                if last_completed_agent[0] and last_completed_agent[0] != agent_role:
                    monitor.record_interaction(
                        from_agent=last_completed_agent[0],
                        to_agent=agent_role,
                        interaction_type="task_handoff",  # 交互类型：任务交接
                        content=f"Task completed: {task_name}"
                    )
                # 更新最后完成的 Agent 角色
                last_completed_agent[0] = agent_role

        # 返回配置好的回调函数
        return task_callback

    # 返回工厂函数本身（返回一个函数而不是立即调用）
    return create_task_callback
