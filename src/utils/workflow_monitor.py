#!/usr/bin/env python3
# 指定解释器为 python3，确保在 Unix-like 系统上直接执行时使用正确的 Python 版本

"""
Workflow Monitor Module.

Features:
1. Record overall process execution results
2. Track execution time of each Agent/Task
3. Save complete Agent interaction records

工作流监控模块。

功能：
1. 记录整体流程的执行结果
2. 跟踪每个 Agent/Task 的执行耗时
3. 保存完整的 Agent 交互记录
"""

import os
# 导入 os 模块，用于创建输出目录和文件路径操作
import json
# 导入 json 模块，用于将监控数据序列化为 JSON 格式保存到文件
import time
# 导入 time 模块，用于记录 Agent 执行的开始和结束时间戳
from datetime import datetime
# 导入 datetime 模块，用于将 Unix 时间戳转换为可读的日期时间字符串
from typing import Dict, List, Any, Optional
# 导入类型提示，为函数签名提供明确的类型信息
from dataclasses import dataclass, field, asdict
# 导入 dataclass 装饰器和辅助函数，用于简化数据类的定义和序列化


@dataclass
class AgentExecution:
    """
    Agent execution record.
    Agent 执行记录数据类：记录单个 Agent 执行一次任务的所有元数据。
    包括 Agent 身份、任务信息、时间戳、执行状态和输出内容。
    """
    agent_name: str              # Agent 名称（如 "Material Designer"）
    agent_role: str              # Agent 角色标识（如 "expert_a"、"coordinator"）
    task_name: str               # 执行的任务名称
    task_description: str        # 任务的详细描述
    start_time: float = 0.0      # 任务开始时间（Unix 时间戳，秒）
    end_time: float = 0.0        # 任务结束时间（Unix 时间戳，秒）
    duration_seconds: float = 0.0 # 任务执行耗时（秒）
    status: str = "pending"      # 任务状态：pending（待执行）、running（执行中）、completed（已完成）、error（出错）
    output: str = ""             # Agent 执行的文本输出
    json_output: Optional[Dict] = None  # Agent 的 JSON 格式输出（如果有），用于结构化结果记录
    error_message: str = ""      # 错误信息（仅在 status 为 "error" 时有值）

    def to_dict(self) -> Dict:
        """
        将 Agent 执行记录转换为字典，用于 JSON 序列化。
        处理字段格式转换：将时间戳转换为可读的日期时间字符串，
        将 duration_seconds 保留两位小数，添加 duration_formatted 格式化字段。
        """
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "task_name": self.task_name,
            "task_description": self.task_description,
            # 将 Unix 时间戳转换为 "YYYY-MM-DD HH:MM:SS" 格式的可读时间字符串
            # 如果 start_time 为 0（未记录），则返回空字符串
            "start_time": datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S") if self.start_time else "",
            "end_time": datetime.fromtimestamp(self.end_time).strftime("%Y-%m-%d %H:%M:%S") if self.end_time else "",
            "duration_seconds": round(self.duration_seconds, 2),  # 保留两位小数
            "duration_formatted": self._format_duration(),  # 格式化耗时字符串（如 "2m 30s"）
            "status": self.status,
            "output": self.output,
            "json_output": self.json_output,
            "error_message": self.error_message
        }

    def _format_duration(self) -> str:
        """
        Format duration.
        格式化耗时为人类可读的字符串。
        - 小于 60 秒：显示 "X.XXs"
        - 小于 3600 秒（1小时）：显示 "Xm Ys"
        - 大于等于 3600 秒：显示 "Xh Ym Zs"
        """
        if self.duration_seconds < 60:
            return f"{self.duration_seconds:.2f}s"
        elif self.duration_seconds < 3600:
            minutes = int(self.duration_seconds // 60)       # 分钟数
            seconds = self.duration_seconds % 60              # 剩余秒数
            return f"{minutes}m {seconds:.2f}s"
        else:
            hours = int(self.duration_seconds // 3600)        # 小时数
            minutes = int((self.duration_seconds % 3600) // 60) # 剩余分钟数
            seconds = self.duration_seconds % 60              # 剩余秒数
            return f"{hours}h {minutes}m {seconds:.2f}s"


@dataclass
class InteractionRecord:
    """
    Agent interaction record.
    Agent 交互记录数据类：记录两个 Agent 之间的一次交互事件。
    用于追踪工作流中的信息传递路径和协作模式。
    """
    timestamp: float           # 交互发生时间（Unix 时间戳）
    from_agent: str            # 发起交互的源 Agent
    to_agent: str              # 接收交互的目标 Agent
    interaction_type: str      # 交互类型：task_handoff（任务交接）、context_sharing（上下文共享）、result_passing（结果传递）
    content: str               # 交互内容描述

    def to_dict(self) -> Dict:
        """
        将交互记录转换为字典，用于 JSON 序列化。
        时间戳转换为可读格式，内容超过 500 字符时截断并添加省略号。
        """
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "interaction_type": self.interaction_type,
            # 内容截断：超过 500 字符时只保留前 500 字符并追加 "..."
            # 避免超长内容导致报告文件过大
            "content": self.content[:500] + "..." if len(self.content) > 500 else self.content
        }


class WorkflowMonitor:
    """Workflow Monitor.
    工作流监控器类。

    用于跟踪和记录整个工作流的执行情况，包括：
    - 每个 Agent/Task 的执行时间
    - Agent 之间的交互记录
    - 整体工作流结果和统计信息
    """

    def __init__(self, workflow_id: str = None, output_dir: str = None):
        """Initialize monitor.
        初始化监控器：设置工作流 ID、输出目录和各类跟踪数据结构。

        Args:
            workflow_id: Unique workflow identifier, defaults to timestamp
            workflow_id: 唯一工作流标识符，默认使用当前时间戳（格式：YYYYMMDD_HHMMSS）
            output_dir: Output directory, defaults to outputs folder in project root
            output_dir: 输出目录，默认为项目根目录下的 outputs 文件夹
        """
        # 工作流 ID：如果不指定则自动生成时间戳格式的唯一标识
        self.workflow_id = workflow_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = time.time()    # 工作流开始时间
        self.end_time: float = 0.0       # 工作流结束时间（初始为 0，结束设置）

        # Set output directory
        # 设置输出目录：如果指定了 output_dir 则直接使用，否则自动检测项目根目录下的 outputs 文件夹
        if output_dir:
            self.output_dir = output_dir
        else:
            # 自动检测项目根目录：从当前文件路径向上两级（src/utils -> src -> 项目根）
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            self.output_dir = os.path.join(project_root, "outputs")

        # 确保输出目录存在，不存在则递归创建
        os.makedirs(self.output_dir, exist_ok=True)

        # Workflow metadata
        # 工作流元数据：用户需求和工作模式信息
        self.user_requirement: str = ""   # 用户输入的材料设计需求
        self.workflow_mode: str = ""      # 工作流模式（preset：预设流程，autonomous：自主调度）
        self.is_async: bool = False       # 是否异步执行

        # Agent execution records
        # Agent 执行记录列表：按时间顺序记录所有 Agent 的执行情况
        self.agent_executions: List[AgentExecution] = []
        self._current_execution: Optional[AgentExecution] = None  # 当前正在执行的 Agent 记录
        self._execution_map: Dict[str, AgentExecution] = {}  # Agent 角色到执行记录的映射，支持并行任务

        # Interaction records
        # Agent 交互记录列表
        self.interactions: List[InteractionRecord] = []

        # Final result
        # 最终结果和工作流状态
        self.final_result: Any = None       # 工作流最终输出结果
        self.workflow_status: str = "running"  # 工作流状态：running（运行中）、completed（已完成）、error（出错）
        self.error_message: str = ""         # 错误信息（仅在出错时有值）

        # Task counter
        # 任务计数器：用于为未命名的任务自动分配编号（Task_1, Task_2, ...）
        self._task_counter = 0

    def set_workflow_info(self, user_requirement: str, workflow_mode: str, is_async: bool = False):
        """Set basic workflow information.
        设置工作流基本信息：在监控开始后调用，记录当前工作流的上下文。

        Args:
            user_requirement: User requirement
            user_requirement: 用户输入的材料设计需求文本
            workflow_mode: Workflow mode (preset/autonomous)
            workflow_mode: 工作流模式（预设工作流 / 智能体自主调度）
            is_async: Whether to execute asynchronously
            is_async: 是否以异步方式执行
        """
        self.user_requirement = user_requirement
        self.workflow_mode = workflow_mode
        self.is_async = is_async

    def start_agent_execution(self, agent_name: str, agent_role: str,
                              task_name: str, task_description: str) -> None:
        """Start recording Agent execution.
        开始记录一个 Agent 的任务执行：创建 AgentExecution 对象，
        记录开始时间和 Agent 信息，加入执行列表。

        Args:
            agent_name: Agent name
            agent_name: Agent 显示名称
            agent_role: Agent role
            agent_role: Agent 角色标识（用于去重和查找）
            task_name: Task name
            task_name: 任务名称
            task_description: Task description
            task_description: 任务详细描述
        """
        # 递增任务计数器
        self._task_counter += 1

        # 创建 AgentExecution 数据类实例
        execution = AgentExecution(
            agent_name=agent_name,
            agent_role=agent_role,
            # 如果未指定任务名，使用 "Task_N" 作为默认名称
            task_name=task_name or f"Task_{self._task_counter}",
            task_description=task_description,
            start_time=time.time(),  # 记录当前时间为开始时间
            status="running"          # 初始状态为运行中
        )

        # Support parallel tasks: use agent_role as key
        # 将执行记录加入映射表：以 agent_role 为键，支持同时追踪多个并行任务
        self._execution_map[agent_role] = execution
        self._current_execution = execution
        # 将执行记录追加到历史列表中
        self.agent_executions.append(execution)

        # Silent mode: do not output monitoring info to console, only record to report
        # 静默模式：不在控制台打印监控信息，仅在最终报告中记录
        # print(f"📊 [Monitor] Agent: {agent_role} - {task_name}")

    def end_agent_execution(self, output: str = "", json_output: Dict = None,
                           error: str = "", agent_role: str = None) -> None:
        """End specified or current Agent execution record.
        结束指定或当前 Agent 的执行记录：计算执行耗时、保存输出和错误信息。

        Args:
            output: Execution output
            output: Agent 执行的文本输出内容
            json_output: JSON format output
            json_output: JSON 格式的结构化输出（如果有）
            error: Error message
            error: 错误信息（如果有错误发生）
            agent_role: Specified Agent role (for parallel tasks)
            agent_role: 指定的 Agent 角色（用于并行任务场景下精确结束某个 Agent）
        """
        # Prioritize using specified agent_role, otherwise use _current_execution
        # 优先使用 agent_role 参数指定的执行记录（用于并行任务），否则使用当前执行记录
        if agent_role and agent_role in self._execution_map:
            execution = self._execution_map[agent_role]
        else:
            execution = self._current_execution

        if execution:
            # 记录结束时间
            execution.end_time = time.time()
            # 计算执行耗时（结束时间 - 开始时间）
            execution.duration_seconds = (
                execution.end_time - execution.start_time
            )
            # 保存输出内容（转为字符串以确保兼容）
            execution.output = str(output)
            execution.json_output = json_output

            # 根据是否有错误信息判定最终状态
            if error:
                execution.status = "error"
                execution.error_message = error
            else:
                execution.status = "completed"

            # Remove completed execution from map
            # 从映射表中移除已完成的执行记录，避免后续混淆
            if agent_role and agent_role in self._execution_map:
                del self._execution_map[agent_role]

            # Silent mode
            # 静默模式注释（不输出日志到控制台）
            # duration = execution._format_duration()
            # print(f"✅ [Monitor] Agent: {execution.agent_role} - : {duration}")

            # 如果结束的是当前执行记录，清空 _current_execution 指针
            if execution == self._current_execution:
                self._current_execution = None

    def record_interaction(self, from_agent: str, to_agent: str,
                          interaction_type: str, content: str) -> None:
        """Record interaction between Agents.
        记录 Agent 之间的一次交互事件。

        Args:
            from_agent: Source Agent
            from_agent: 发起交互的源 Agent 名称
            to_agent: Target Agent
            to_agent: 接收交互的目标 Agent 名称
            interaction_type: Interaction type (task_handoff/context_sharing/result_passing)
            interaction_type: 交互类型（任务交接 / 上下文共享 / 结果传递）
            content: Interaction content
            content: 交互的具体内容描述
        """
        # 创建交互记录数据类实例
        interaction = InteractionRecord(
            timestamp=time.time(),
            from_agent=from_agent,
            to_agent=to_agent,
            interaction_type=interaction_type,
            content=content
        )
        # 将交互记录追加到列表中
        self.interactions.append(interaction)

    def create_task_callback(self):
        """Create task callback function for CrewAI.
        创建 CrewAI 任务回调函数。
        该回调在 CrewAI 每个 Task 完成时被调用，
        用于自动记录任务执行信息和 Agent 间的交接过程。

        Returns:
            Function usable for Crew task_callback parameter
            Function: 可用于 Crew task_callback 参数的回调函数
        """
        def task_callback(task_output):
            """Callback function when task is completed.
            当 CrewAI 任务完成时被调用的回调函数。"""
            # Get task information
            # 获取任务信息：尝试从 task_output 中提取 name 和 description
            task_name = getattr(task_output, 'name', None) or f"Task_{self._task_counter + 1}"
            task_description = getattr(task_output, 'description', 'N/A')

            # Try to get Agent information
            # 尝试从 task_output 中获取执行该任务的 Agent 信息
            agent = getattr(task_output, 'agent', None)
            agent_name = getattr(agent, 'name', 'Unknown') if agent else 'Unknown'
            agent_role = getattr(agent, 'role', 'Unknown') if agent else 'Unknown'

            # Get output
            # 获取任务输出内容
            output_str = str(task_output)
            json_output = None
            # 如果 task_output 有 json_dict 属性且非空，提取 JSON 输出
            if hasattr(task_output, 'json_dict') and task_output.json_dict:
                json_output = task_output.json_dict

            # If no current execution record, create one (for handling cases without explicit start)
            # 如果没有活跃的执行记录（例如 CrewAI 自动调度的任务），自动创建一条新的
            if not self._current_execution:
                self.start_agent_execution(agent_name, agent_role, task_name, task_description)

            # End execution record
            # 结束当前执行记录，记录输出和状态
            self.end_agent_execution(output=output_str, json_output=json_output)

            # Record interaction (task completed -> next task)
            # 如果已有多个执行记录完成，记录前一个 Agent 到当前 Agent 的任务交接
            if len(self.agent_executions) > 1:
                prev_agent = self.agent_executions[-2].agent_role  # 倒数第二个（前一个）Agent
                curr_agent = agent_role                              # 当前 Agent
                self.record_interaction(
                    from_agent=prev_agent,
                    to_agent=curr_agent,
                    interaction_type="task_handoff",  # 交互类型：任务交接
                    content=f"Task completed: {task_name}"
                )

        return task_callback

    def set_final_result(self, result: Any, status: str = "completed",
                        error: str = "") -> None:
        """Set final result.
        设置工作流的最终结果：记录结束时间、最终输出和最终状态。

        Args:
            result: Final result
            result: 工作流最终输出的结果
            status: Status (completed/error)
            status: 最终状态（completed 完成 / error 出错）
            error: Error message
            error: 错误信息描述
        """
        self.end_time = time.time()      # 记录工作流总结束时间
        self.final_result = result       # 保存最终结果
        self.workflow_status = status    # 设置最终状态
        self.error_message = error       # 记录错误信息（如果有）

    def get_summary(self) -> Dict:
        """Get workflow execution summary.
        获取工作流执行摘要：汇总所有监控数据到一个字典中。

        Returns:
            Dictionary containing all monitoring data
            Dict: 包含工作流信息、Agent 统计、执行记录、交互记录和最终结果的字典
        """
        # 计算工作流总耗时（如果已结束则用 end_time，否则用当前时间）
        total_duration = self.end_time - self.start_time if self.end_time else time.time() - self.start_time

        # Calculate total time for each Agent
        # 按 Agent 角色汇总所有任务的执行耗时
        agent_durations = {}
        for execution in self.agent_executions:
            role = execution.agent_role
            if role not in agent_durations:
                agent_durations[role] = 0.0
            agent_durations[role] += execution.duration_seconds

        # 构建并返回完整的摘要字典
        return {
            "workflow_info": {
                "workflow_id": self.workflow_id,
                "user_requirement": self.user_requirement,
                "workflow_mode": self.workflow_mode,
                "is_async": self.is_async,
                "start_time": datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": datetime.fromtimestamp(self.end_time).strftime("%Y-%m-%d %H:%M:%S") if self.end_time else "",
                "total_duration_seconds": round(total_duration, 2),
                "total_duration_formatted": self._format_duration(total_duration),
                "status": self.workflow_status,
                "error_message": self.error_message
            },
            "agent_statistics": {
                # 统计参与的唯一 Agent 角色数量
                "total_agents": len(set(e.agent_role for e in self.agent_executions)),
                # 统计总任务数量
                "total_tasks": len(self.agent_executions),
                # 各 Agent 的耗时（保留两位小数）
                "agent_durations": {k: round(v, 2) for k, v in agent_durations.items()},
                # 耗时最长的 Agent 角色（用于性能分析和优化）
                "slowest_agent": max(agent_durations.items(), key=lambda x: x[1])[0] if agent_durations else None,
                # 耗时最短的 Agent 角色
                "fastest_agent": min(agent_durations.items(), key=lambda x: x[1])[0] if agent_durations else None
            },
            # 所有 Agent 执行记录的序列化列表
            "agent_executions": [e.to_dict() for e in self.agent_executions],
            # 所有交互记录的序列化列表
            "interactions": [i.to_dict() for i in self.interactions],
            # 最终结果（转为字符串，防止复杂对象导致序列化失败）
            "final_result": str(self.final_result) if self.final_result else None
        }

    def _format_duration(self, seconds: float) -> str:
        """Format duration.
        格式化耗时为可读字符串（与 AgentExecution._format_duration 逻辑相同，
        但作为实例方法存在，方便在报告生成时直接使用）。
        """
        if seconds < 60:
            return f"{seconds:.2f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.2f}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = seconds % 60
            return f"{hours}h {minutes}m {secs:.2f}s"

    def save_report(self, filename: str = None) -> str:
        """Save monitoring report.
        保存 JSON 格式的监控报告到文件。

        Args:
            filename: Filename, defaults to auto-generated
            filename: 文件名，默认自动生成（格式：monitor_report_{ID}_{mode}.json）

        Returns:
            Path to saved file
            str: 保存的文件完整路径
        """
        # 如果未指定文件名，自动生成包含工作流 ID 和模式的名称
        if not filename:
            mode_str = f"{self.workflow_mode}_{'async' if self.is_async else 'sync'}"
            filename = f"monitor_report_{self.workflow_id}_{mode_str}.json"

        # 拼接完整文件路径
        filepath = os.path.join(self.output_dir, filename)

        # 获取监控摘要数据
        summary = self.get_summary()

        # 以 UTF-8 编码写入 JSON 文件
        # ensure_ascii=False 保证中文字符正常显示（非 ASCII 字符不被转义）
        # indent=2 使 JSON 格式化缩进，便于人工阅读
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # 静默模式：不在控制台输出
        # print(f"📊 [Monitor] : {filepath}")
        return filepath

    def save_readable_report(self, filename: str = None) -> str:
        """Save readable text format monitoring report.
        保存人类可读的文本格式监控报告。
        相比 JSON 格式，此报告包含格式化标题、分隔线和进度条等视觉元素，
        适合直接在文本编辑器中查看。

        Args:
            filename: Filename, defaults to auto-generated
            filename: 文件名，默认自动生成（格式：monitor_report_{ID}_{mode}.txt）

        Returns:
            Path to saved file
            str: 保存的文件完整路径
        """
        # 如果未指定文件名，自动生成
        if not filename:
            mode_str = f"{self.workflow_mode}_{'async' if self.is_async else 'sync'}"
            filename = f"monitor_report_{self.workflow_id}_{mode_str}.txt"

        filepath = os.path.join(self.output_dir, filename)
        summary = self.get_summary()

        with open(filepath, 'w', encoding='utf-8') as f:
            # 报告头部标题
            f.write("=" * 80 + "\n")
            f.write("ECOMATS Workflow Monitor Report\n")
            f.write("=" * 80 + "\n\n")

            # 1. Workflow basic information
            # 第一部分：工作流基本信息
            f.write("📋 Workflow Info\n")
            f.write("-" * 40 + "\n")
            info = summary["workflow_info"]
            f.write(f"  Workflow ID: {info['workflow_id']}\n")
            # 用户需求过长（超过 100 字符）时截断显示，避免报告过于冗长
            f.write(f"  User Requirement: {info['user_requirement'][:100]}...\n" if len(info['user_requirement']) > 100 else f"  User Requirement: {info['user_requirement']}\n")
            f.write(f"  Workflow Mode: {info['workflow_mode']} ({'async' if info['is_async'] else 'sync'})\n")
            f.write(f"  Start Time: {info['start_time']}\n")
            f.write(f"  End Time: {info['end_time']}\n")
            f.write(f"  Total Duration: {info['total_duration_formatted']}\n")
            f.write(f"  Status: {info['status']}\n")
            # 仅在发生错误时才输出错误信息行
            if info['error_message']:
                f.write(f"  Error: {info['error_message']}\n")
            f.write("\n")

            # 2. Agent statistics
            # 第二部分：Agent 统计概览
            f.write("📊 Agent Statistics\n")
            f.write("-" * 40 + "\n")
            stats = summary["agent_statistics"]
            f.write(f"  Total Agents: {stats['total_agents']}\n")
            f.write(f"  Total Tasks: {stats['total_tasks']}\n")
            f.write(f"  Slowest Agent: {stats['slowest_agent']}\n")
            f.write(f"  Fastest Agent: {stats['fastest_agent']}\n")
            f.write("\n")

            # 3. Detailed Agent durations
            # 第三部分：各 Agent 耗时详情（含可视化进度条）
            f.write("⏱️ Agent Duration Details\n")
            f.write("-" * 40 + "\n")
            if stats['agent_durations'] and max(stats['agent_durations'].values()) > 0:
                max_duration = max(stats['agent_durations'].values())  # 最长耗时，用于归一化
                # 按耗时降序排列
                for role, duration in sorted(stats['agent_durations'].items(), key=lambda x: x[1], reverse=True):
                    # 绘制进度条：实心块表示相对耗时比例，空心块表示剩余
                    bar_length = int(duration / max_duration * 30)
                    bar = "█" * bar_length + "░" * (30 - bar_length)
                    f.write(f"  {role[:30]:<30} | {bar} | {duration:.2f}s\n")
            else:
                f.write("  (No agent duration data)\n")
            f.write("\n")

            # 4. Task execution timeline
            # 第四部分：任务执行时间线（按执行顺序逐条列出）
            f.write("📜 Task Execution Timeline\n")
            f.write("-" * 40 + "\n")
            for i, execution in enumerate(summary["agent_executions"], 1):
                # 用勾号和叉号标识任务完成状态
                status_icon = "✅" if execution["status"] == "completed" else "❌"
                f.write(f"  {i}. [{status_icon}] {execution['agent_role']}\n")
                f.write(f"     Task: {execution['task_name']}\n")
                f.write(f"     Start: {execution['start_time']} | End: {execution['end_time']}\n")
                f.write(f"     Duration: {execution['duration_formatted']}\n")
                # 显示错误信息（如果有）
                if execution["error_message"]:
                    f.write(f"     Error: {execution['error_message']}\n")
                f.write("\n")

            # 5. Agent interaction records
            # 第五部分：Agent 交互记录（展示信息流的传递路径）
            if summary["interactions"]:
                f.write("🔗 Agent Interactions\n")
                f.write("-" * 40 + "\n")
                for i, interaction in enumerate(summary["interactions"], 1):
                    f.write(f"  {i}. [{interaction['timestamp']}]\n")
                    # 显示交互方向
                    f.write(f"     {interaction['from_agent']} → {interaction['to_agent']}\n")
                    f.write(f"     Type: {interaction['interaction_type']}\n")
                    # 内容过长时截断
                    f.write(f"     Content: {interaction['content'][:100]}...\n" if len(interaction['content']) > 100 else f"     Content: {interaction['content']}\n")
                    f.write("\n")

            # 6. Final result summary
            # 第六部分：最终结果摘要
            f.write("📝 Final Result Summary\n")
            f.write("-" * 40 + "\n")
            if summary["final_result"]:
                # 最终结果过长时截断展示
                result_preview = summary["final_result"][:1000] + "..." if len(summary["final_result"]) > 1000 else summary["final_result"]
                f.write(f"{result_preview}\n")
            else:
                f.write("  (No results)\n")

            # 报告尾部：分隔线和生成时间
            f.write("\n" + "=" * 80 + "\n")
            f.write("Report Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")

        # 静默模式
        # print(f"📊 [Monitor] : {filepath}")
        return filepath

    def print_summary(self) -> None:
        """Print execution summary in terminal.
        在终端打印简要的执行摘要。
        此方法在控制台输出，用于快速查看工作流执行概况，不写入文件。
        """
        summary = self.get_summary()

        print("\n" + "=" * 70)
        print("📊 Workflow Execution Summary")
        print("=" * 70)

        # Basic information
        # 基本执行信息：总耗时和状态
        info = summary["workflow_info"]
        print(f"\n⏱️ Total Duration: {info['total_duration_formatted']}")
        print(f"📌 Status: {info['status']}")

        # Agent statistics
        # Agent 统计：任务总数和 Agent 数
        stats = summary["agent_statistics"]
        print(f"\n📋 Executed {stats['total_tasks']} tasks with {stats['total_agents']} agents")

        # Duration ranking
        # 耗时排名：按降序展示各 Agent 的执行耗时
        print("\n⏱️ Agent Duration Ranking:")
        for i, (role, duration) in enumerate(sorted(stats['agent_durations'].items(),
                                                      key=lambda x: x[1], reverse=True), 1):
            print(f"   {i}. {role}: {duration:.2f}s")

        print("\n" + "=" * 70)


# Global monitor instance (optional usage)
# 全局监控器实例：可选使用的全局单例
# 如果应用中只需要一个监控器，可通过此变量获取，避免传递实例
_global_monitor: Optional[WorkflowMonitor] = None

def get_monitor() -> Optional[WorkflowMonitor]:
    """Get global monitor instance.
    获取全局监控器实例。
    返回当前配置的全局监控器，如果尚未创建则返回 None。
    """
    return _global_monitor

def create_monitor(workflow_id: str = None, output_dir: str = None) -> WorkflowMonitor:
    """Create and set global monitor.
    创建并设置全局监控器实例。
    同时设置全局单例，供其他模块通过 get_monitor() 获取。

    Args:
        workflow_id: 工作流唯一标识符
        output_dir: 输出目录

    Returns:
        WorkflowMonitor: 新创建的监控器实例
    """
    global _global_monitor  # 声明使用模块级全局变量
    _global_monitor = WorkflowMonitor(workflow_id, output_dir)
    return _global_monitor
