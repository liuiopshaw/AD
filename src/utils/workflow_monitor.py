#!/usr/bin/env python3
# Specify python3 as the interpreter, ensuring the correct Python version is used when executed directly on Unix-like systems

"""
Workflow Monitor Module.

Features:
1. Record overall process execution results
2. Track execution time of each Agent/Task
3. Save complete Agent interaction records
"""

import os
# Import the os module for creating output directories and file path operations
import json
# Import the json module to serialize monitoring data to JSON format and save it to files
import time
# Import the time module to record start and end timestamps of Agent execution
from datetime import datetime
# Import the datetime module to convert Unix timestamps into readable date-time strings
from typing import Dict, List, Any, Optional
# Import type hints to provide explicit type information for function signatures
from dataclasses import dataclass, field, asdict
# Import the dataclass decorator and helper functions to simplify data class definition and serialization


@dataclass
class AgentExecution:
    """
    Agent execution record.
    Data class recording all metadata of a single task execution by one Agent,
    including Agent identity, task information, timestamps, execution status, and output content.
    """
    agent_name: str              # Agent name (e.g. "Material Designer")
    agent_role: str              # Agent role identifier (e.g. "expert_a", "coordinator")
    task_name: str               # Name of the executed task
    task_description: str        # Detailed description of the task
    start_time: float = 0.0      # Task start time (Unix timestamp, seconds)
    end_time: float = 0.0        # Task end time (Unix timestamp, seconds)
    duration_seconds: float = 0.0 # Task execution duration (seconds)
    status: str = "pending"      # Task status: pending, running, completed, error
    output: str = ""             # Text output of the Agent execution
    json_output: Optional[Dict] = None  # JSON-format output of the Agent (if any), for structured result recording
    error_message: str = ""      # Error message (only set when status is "error")

    def to_dict(self) -> Dict:
        """
        Convert the Agent execution record to a dictionary for JSON serialization.
        Handles field format conversion: converts timestamps to readable date-time strings,
        rounds duration_seconds to two decimal places, and adds the duration_formatted field.
        """
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "task_name": self.task_name,
            "task_description": self.task_description,
            # Convert Unix timestamps to readable time strings in "YYYY-MM-DD HH:MM:SS" format
            # If start_time is 0 (not recorded), return an empty string
            "start_time": datetime.fromtimestamp(self.start_time).strftime("%Y-%m-%d %H:%M:%S") if self.start_time else "",
            "end_time": datetime.fromtimestamp(self.end_time).strftime("%Y-%m-%d %H:%M:%S") if self.end_time else "",
            "duration_seconds": round(self.duration_seconds, 2),  # Round to two decimal places
            "duration_formatted": self._format_duration(),  # Formatted duration string (e.g. "2m 30s")
            "status": self.status,
            "output": self.output,
            "json_output": self.json_output,
            "error_message": self.error_message
        }

    def _format_duration(self) -> str:
        """
        Format duration.
        Format the duration into a human-readable string.
        - Less than 60 seconds: display "X.XXs"
        - Less than 3600 seconds (1 hour): display "Xm Ys"
        - Greater than or equal to 3600 seconds: display "Xh Ym Zs"
        """
        if self.duration_seconds < 60:
            return f"{self.duration_seconds:.2f}s"
        elif self.duration_seconds < 3600:
            minutes = int(self.duration_seconds // 60)       # Number of minutes
            seconds = self.duration_seconds % 60              # Remaining seconds
            return f"{minutes}m {seconds:.2f}s"
        else:
            hours = int(self.duration_seconds // 3600)        # Number of hours
            minutes = int((self.duration_seconds % 3600) // 60) # Remaining minutes
            seconds = self.duration_seconds % 60              # Remaining seconds
            return f"{hours}h {minutes}m {seconds:.2f}s"


@dataclass
class InteractionRecord:
    """
    Agent interaction record.
    Data class recording a single interaction event between two Agents,
    used to trace information flow paths and collaboration patterns in the workflow.
    """
    timestamp: float           # Time when the interaction occurred (Unix timestamp)
    from_agent: str            # Source Agent initiating the interaction
    to_agent: str              # Target Agent receiving the interaction
    interaction_type: str      # Interaction type: task_handoff, context_sharing, result_passing
    content: str               # Description of the interaction content

    def to_dict(self) -> Dict:
        """
        Convert the interaction record to a dictionary for JSON serialization.
        The timestamp is converted to a readable format; content longer than 500 characters
        is truncated with an ellipsis appended.
        """
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "interaction_type": self.interaction_type,
            # Content truncation: keep only the first 500 characters and append "..." when exceeding 500 characters
            # Avoids oversized report files caused by overly long content
            "content": self.content[:500] + "..." if len(self.content) > 500 else self.content
        }


class WorkflowMonitor:
    """Workflow Monitor.

    Tracks and records the execution of the entire workflow, including:
    - Execution time of each Agent/Task
    - Interaction records between Agents
    - Overall workflow results and statistics
    """

    def __init__(self, workflow_id: str = None, output_dir: str = None):
        """Initialize monitor.
        Initialize the monitor: set the workflow ID, output directory, and various tracking data structures.

        Args:
            workflow_id: Unique workflow identifier, defaults to the current timestamp (format: YYYYMMDD_HHMMSS)
            output_dir: Output directory, defaults to the outputs folder under the project root
        """
        # Workflow ID: auto-generate a unique timestamp-format identifier if not specified
        self.workflow_id = workflow_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = time.time()    # Workflow start time
        self.end_time: float = 0.0       # Workflow end time (initially 0, set when finished)

        # Set output directory
        # If output_dir is specified, use it directly; otherwise auto-detect the outputs folder under the project root
        if output_dir:
            self.output_dir = output_dir
        else:
            # Auto-detect the project root: go two levels up from the current file path (src/utils -> src -> project root)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(current_dir))
            self.output_dir = os.path.join(project_root, "outputs")

        # Ensure the output directory exists; create it recursively if not
        os.makedirs(self.output_dir, exist_ok=True)

        # Workflow metadata
        # Workflow metadata: user requirement and workflow mode information
        self.user_requirement: str = ""   # Material design requirement entered by the user
        self.workflow_mode: str = ""      # Workflow mode (preset: preset workflow, autonomous: autonomous scheduling)
        self.is_async: bool = False       # Whether to execute asynchronously

        # Agent execution records
        # List of Agent execution records in chronological order
        self.agent_executions: List[AgentExecution] = []
        self._current_execution: Optional[AgentExecution] = None  # Record of the currently executing Agent
        self._execution_map: Dict[str, AgentExecution] = {}  # Mapping from Agent role to execution record, supporting parallel tasks

        # Interaction records
        # List of Agent interaction records
        self.interactions: List[InteractionRecord] = []

        # Final result
        # Final result and workflow status
        self.final_result: Any = None       # Final output result of the workflow
        self.workflow_status: str = "running"  # Workflow status: running, completed, error
        self.error_message: str = ""         # Error message (only set when an error occurs)

        # Task counter
        # Task counter: used to auto-assign numbers to unnamed tasks (Task_1, Task_2, ...)
        self._task_counter = 0

    def set_workflow_info(self, user_requirement: str, workflow_mode: str, is_async: bool = False):
        """Set basic workflow information.
        Called after monitoring starts to record the context of the current workflow.

        Args:
            user_requirement: Material design requirement text entered by the user
            workflow_mode: Workflow mode (preset workflow / autonomous agent scheduling)
            is_async: Whether to execute asynchronously
        """
        self.user_requirement = user_requirement
        self.workflow_mode = workflow_mode
        self.is_async = is_async

    def start_agent_execution(self, agent_name: str, agent_role: str,
                              task_name: str, task_description: str) -> None:
        """Start recording Agent execution.
        Create an AgentExecution object, record the start time and Agent information,
        and add it to the execution list.

        Args:
            agent_name: Agent display name
            agent_role: Agent role identifier (used for deduplication and lookup)
            task_name: Task name
            task_description: Detailed task description
        """
        # Increment the task counter
        self._task_counter += 1

        # Create an AgentExecution data class instance
        execution = AgentExecution(
            agent_name=agent_name,
            agent_role=agent_role,
            # If no task name is specified, use "Task_N" as the default name
            task_name=task_name or f"Task_{self._task_counter}",
            task_description=task_description,
            start_time=time.time(),  # Record the current time as the start time
            status="running"          # Initial status is running
        )

        # Support parallel tasks: use agent_role as key
        # Add the execution record to the map keyed by agent_role, supporting concurrent tracking of multiple parallel tasks
        self._execution_map[agent_role] = execution
        self._current_execution = execution
        # Append the execution record to the history list
        self.agent_executions.append(execution)

        # Silent mode: do not output monitoring info to console, only record to report
        # print(f"📊 [Monitor] Agent: {agent_role} - {task_name}")

    def end_agent_execution(self, output: str = "", json_output: Dict = None,
                           error: str = "", agent_role: str = None) -> None:
        """End specified or current Agent execution record.
        Compute the execution duration and save the output and error information.

        Args:
            output: Text output content of the Agent execution
            json_output: Structured output in JSON format (if any)
            error: Error message (if an error occurred)
            agent_role: Specified Agent role (used to precisely end a specific Agent in parallel task scenarios)
        """
        # Prioritize using specified agent_role, otherwise use _current_execution
        # Prefer the execution record specified by the agent_role parameter (for parallel tasks); otherwise use the current execution record
        if agent_role and agent_role in self._execution_map:
            execution = self._execution_map[agent_role]
        else:
            execution = self._current_execution

        if execution:
            # Record the end time
            execution.end_time = time.time()
            # Compute the execution duration (end time - start time)
            execution.duration_seconds = (
                execution.end_time - execution.start_time
            )
            # Save the output content (converted to string for compatibility)
            execution.output = str(output)
            execution.json_output = json_output

            # Determine the final status based on whether an error message exists
            if error:
                execution.status = "error"
                execution.error_message = error
            else:
                execution.status = "completed"

            # Remove completed execution from map
            # Remove the completed execution record from the map to avoid later confusion
            if agent_role and agent_role in self._execution_map:
                del self._execution_map[agent_role]

            # Silent mode
            # Silent mode comment (no log output to the console)
            # duration = execution._format_duration()
            # print(f"✅ [Monitor] Agent: {execution.agent_role} - : {duration}")

            # If the ended record is the current execution, clear the _current_execution pointer
            if execution == self._current_execution:
                self._current_execution = None

    def record_interaction(self, from_agent: str, to_agent: str,
                          interaction_type: str, content: str) -> None:
        """Record interaction between Agents.
        Record a single interaction event between Agents.

        Args:
            from_agent: Name of the source Agent initiating the interaction
            to_agent: Name of the target Agent receiving the interaction
            interaction_type: Interaction type (task_handoff / context_sharing / result_passing)
            content: Detailed description of the interaction content
        """
        # Create an InteractionRecord data class instance
        interaction = InteractionRecord(
            timestamp=time.time(),
            from_agent=from_agent,
            to_agent=to_agent,
            interaction_type=interaction_type,
            content=content
        )
        # Append the interaction record to the list
        self.interactions.append(interaction)

    def create_task_callback(self):
        """Create task callback function for CrewAI.
        The callback is invoked when each CrewAI Task completes,
        automatically recording task execution information and the handoff between Agents.

        Returns:
            Function usable for Crew task_callback parameter
        """
        def task_callback(task_output):
            """Callback function invoked when a CrewAI task is completed."""
            # Get task information
            # Try to extract name and description from task_output
            task_name = getattr(task_output, 'name', None) or f"Task_{self._task_counter + 1}"
            task_description = getattr(task_output, 'description', 'N/A')

            # Try to get Agent information
            # Try to get the Agent that executed this task from task_output
            agent = getattr(task_output, 'agent', None)
            agent_name = getattr(agent, 'name', 'Unknown') if agent else 'Unknown'
            agent_role = getattr(agent, 'role', 'Unknown') if agent else 'Unknown'

            # Get output
            # Get the task output content
            output_str = str(task_output)
            json_output = None
            # If task_output has a non-empty json_dict attribute, extract the JSON output
            if hasattr(task_output, 'json_dict') and task_output.json_dict:
                json_output = task_output.json_dict

            # If no current execution record, create one (for handling cases without explicit start)
            # If there is no active execution record (e.g. a task auto-scheduled by CrewAI), create a new one automatically
            if not self._current_execution:
                self.start_agent_execution(agent_name, agent_role, task_name, task_description)

            # End execution record
            # End the current execution record, recording the output and status
            self.end_agent_execution(output=output_str, json_output=json_output)

            # Record interaction (task completed -> next task)
            # If multiple execution records have completed, record the task handoff from the previous Agent to the current Agent
            if len(self.agent_executions) > 1:
                prev_agent = self.agent_executions[-2].agent_role  # The second-to-last (previous) Agent
                curr_agent = agent_role                              # The current Agent
                self.record_interaction(
                    from_agent=prev_agent,
                    to_agent=curr_agent,
                    interaction_type="task_handoff",  # Interaction type: task handoff
                    content=f"Task completed: {task_name}"
                )

        return task_callback

    def set_final_result(self, result: Any, status: str = "completed",
                        error: str = "") -> None:
        """Set final result.
        Record the end time, final output, and final status of the workflow.

        Args:
            result: Final output result of the workflow
            status: Final status (completed / error)
            error: Error message description
        """
        self.end_time = time.time()      # Record the overall workflow end time
        self.final_result = result       # Save the final result
        self.workflow_status = status    # Set the final status
        self.error_message = error       # Record the error message (if any)

    def get_summary(self) -> Dict:
        """Get workflow execution summary.
        Aggregate all monitoring data into a single dictionary.

        Returns:
            Dictionary containing workflow info, Agent statistics, execution records, interaction records, and the final result
        """
        # Compute the total workflow duration (use end_time if finished, otherwise the current time)
        total_duration = self.end_time - self.start_time if self.end_time else time.time() - self.start_time

        # Calculate total time for each Agent
        # Aggregate execution durations of all tasks by Agent role
        agent_durations = {}
        for execution in self.agent_executions:
            role = execution.agent_role
            if role not in agent_durations:
                agent_durations[role] = 0.0
            agent_durations[role] += execution.duration_seconds

        # Build and return the complete summary dictionary
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
                # Count the number of unique Agent roles involved
                "total_agents": len(set(e.agent_role for e in self.agent_executions)),
                # Count the total number of tasks
                "total_tasks": len(self.agent_executions),
                # Duration of each Agent (rounded to two decimal places)
                "agent_durations": {k: round(v, 2) for k, v in agent_durations.items()},
                # Agent role with the longest duration (for performance analysis and optimization)
                "slowest_agent": max(agent_durations.items(), key=lambda x: x[1])[0] if agent_durations else None,
                # Agent role with the shortest duration
                "fastest_agent": min(agent_durations.items(), key=lambda x: x[1])[0] if agent_durations else None
            },
            # Serialized list of all Agent execution records
            "agent_executions": [e.to_dict() for e in self.agent_executions],
            # Serialized list of all interaction records
            "interactions": [i.to_dict() for i in self.interactions],
            # Final result (converted to string to prevent serialization failures from complex objects)
            "final_result": str(self.final_result) if self.final_result else None
        }

    def _format_duration(self, seconds: float) -> str:
        """Format duration.
        Format the duration into a readable string (same logic as AgentExecution._format_duration,
        but kept as an instance method for convenient use during report generation).
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
        Save the monitoring report in JSON format to a file.

        Args:
            filename: Filename, auto-generated by default (format: monitor_report_{ID}_{mode}.json)

        Returns:
            Full path of the saved file
        """
        # If no filename is specified, auto-generate one containing the workflow ID and mode
        if not filename:
            mode_str = f"{self.workflow_mode}_{'async' if self.is_async else 'sync'}"
            filename = f"monitor_report_{self.workflow_id}_{mode_str}.json"

        # Join the full file path
        filepath = os.path.join(self.output_dir, filename)

        # Get the monitoring summary data
        summary = self.get_summary()

        # Write the JSON file with UTF-8 encoding
        # ensure_ascii=False keeps non-ASCII characters readable (they are not escaped)
        # indent=2 formats the JSON with indentation for human readability
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # Silent mode: no console output
        # print(f"📊 [Monitor] : {filepath}")
        return filepath

    def save_readable_report(self, filename: str = None) -> str:
        """Save readable text format monitoring report.
        Save a human-readable monitoring report in text format.
        Compared to the JSON format, this report includes visual elements such as formatted
        titles, separators, and progress bars, making it suitable for viewing directly in a text editor.

        Args:
            filename: Filename, auto-generated by default (format: monitor_report_{ID}_{mode}.txt)

        Returns:
            Full path of the saved file
        """
        # Auto-generate the filename if not specified
        if not filename:
            mode_str = f"{self.workflow_mode}_{'async' if self.is_async else 'sync'}"
            filename = f"monitor_report_{self.workflow_id}_{mode_str}.txt"

        filepath = os.path.join(self.output_dir, filename)
        summary = self.get_summary()

        with open(filepath, 'w', encoding='utf-8') as f:
            # Report header title
            f.write("=" * 80 + "\n")
            f.write("ECOMATS Workflow Monitor Report\n")
            f.write("=" * 80 + "\n\n")

            # 1. Workflow basic information
            # Part 1: workflow basic information
            f.write("📋 Workflow Info\n")
            f.write("-" * 40 + "\n")
            info = summary["workflow_info"]
            f.write(f"  Workflow ID: {info['workflow_id']}\n")
            # Truncate the user requirement when it is too long (over 100 characters) to keep the report concise
            f.write(f"  User Requirement: {info['user_requirement'][:100]}...\n" if len(info['user_requirement']) > 100 else f"  User Requirement: {info['user_requirement']}\n")
            f.write(f"  Workflow Mode: {info['workflow_mode']} ({'async' if info['is_async'] else 'sync'})\n")
            f.write(f"  Start Time: {info['start_time']}\n")
            f.write(f"  End Time: {info['end_time']}\n")
            f.write(f"  Total Duration: {info['total_duration_formatted']}\n")
            f.write(f"  Status: {info['status']}\n")
            # Only output the error message line when an error occurred
            if info['error_message']:
                f.write(f"  Error: {info['error_message']}\n")
            f.write("\n")

            # 2. Agent statistics
            # Part 2: Agent statistics overview
            f.write("📊 Agent Statistics\n")
            f.write("-" * 40 + "\n")
            stats = summary["agent_statistics"]
            f.write(f"  Total Agents: {stats['total_agents']}\n")
            f.write(f"  Total Tasks: {stats['total_tasks']}\n")
            f.write(f"  Slowest Agent: {stats['slowest_agent']}\n")
            f.write(f"  Fastest Agent: {stats['fastest_agent']}\n")
            f.write("\n")

            # 3. Detailed Agent durations
            # Part 3: per-Agent duration details (with visual progress bars)
            f.write("⏱️ Agent Duration Details\n")
            f.write("-" * 40 + "\n")
            if stats['agent_durations'] and max(stats['agent_durations'].values()) > 0:
                max_duration = max(stats['agent_durations'].values())  # Longest duration, used for normalization
                # Sort by duration in descending order
                for role, duration in sorted(stats['agent_durations'].items(), key=lambda x: x[1], reverse=True):
                    # Draw the progress bar: solid blocks represent the relative duration proportion, hollow blocks the remainder
                    bar_length = int(duration / max_duration * 30)
                    bar = "█" * bar_length + "░" * (30 - bar_length)
                    f.write(f"  {role[:30]:<30} | {bar} | {duration:.2f}s\n")
            else:
                f.write("  (No agent duration data)\n")
            f.write("\n")

            # 4. Task execution timeline
            # Part 4: task execution timeline (listed in execution order)
            f.write("📜 Task Execution Timeline\n")
            f.write("-" * 40 + "\n")
            for i, execution in enumerate(summary["agent_executions"], 1):
                # Use check mark and cross mark to indicate task completion status
                status_icon = "✅" if execution["status"] == "completed" else "❌"
                f.write(f"  {i}. [{status_icon}] {execution['agent_role']}\n")
                f.write(f"     Task: {execution['task_name']}\n")
                f.write(f"     Start: {execution['start_time']} | End: {execution['end_time']}\n")
                f.write(f"     Duration: {execution['duration_formatted']}\n")
                # Show the error message (if any)
                if execution["error_message"]:
                    f.write(f"     Error: {execution['error_message']}\n")
                f.write("\n")

            # 5. Agent interaction records
            # Part 5: Agent interaction records (showing the information flow paths)
            if summary["interactions"]:
                f.write("🔗 Agent Interactions\n")
                f.write("-" * 40 + "\n")
                for i, interaction in enumerate(summary["interactions"], 1):
                    f.write(f"  {i}. [{interaction['timestamp']}]\n")
                    # Show the interaction direction
                    f.write(f"     {interaction['from_agent']} → {interaction['to_agent']}\n")
                    f.write(f"     Type: {interaction['interaction_type']}\n")
                    # Truncate content when too long
                    f.write(f"     Content: {interaction['content'][:100]}...\n" if len(interaction['content']) > 100 else f"     Content: {interaction['content']}\n")
                    f.write("\n")

            # 6. Final result summary
            # Part 6: final result summary
            f.write("📝 Final Result Summary\n")
            f.write("-" * 40 + "\n")
            if summary["final_result"]:
                # Truncate the final result when it is too long
                result_preview = summary["final_result"][:1000] + "..." if len(summary["final_result"]) > 1000 else summary["final_result"]
                f.write(f"{result_preview}\n")
            else:
                f.write("  (No results)\n")

            # Report footer: separator line and generation time
            f.write("\n" + "=" * 80 + "\n")
            f.write("Report Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")

        # Silent mode
        # print(f"📊 [Monitor] : {filepath}")
        return filepath

    def print_summary(self) -> None:
        """Print execution summary in terminal.
        Print a brief execution summary in the terminal.
        This method outputs to the console for a quick overview of workflow execution; it does not write to a file.
        """
        summary = self.get_summary()

        print("\n" + "=" * 70)
        print("📊 Workflow Execution Summary")
        print("=" * 70)

        # Basic information
        # Basic execution information: total duration and status
        info = summary["workflow_info"]
        print(f"\n⏱️ Total Duration: {info['total_duration_formatted']}")
        print(f"📌 Status: {info['status']}")

        # Agent statistics
        # Agent statistics: total number of tasks and Agents
        stats = summary["agent_statistics"]
        print(f"\n📋 Executed {stats['total_tasks']} tasks with {stats['total_agents']} agents")

        # Duration ranking
        # Duration ranking: show each Agent's execution duration in descending order
        print("\n⏱️ Agent Duration Ranking:")
        for i, (role, duration) in enumerate(sorted(stats['agent_durations'].items(),
                                                      key=lambda x: x[1], reverse=True), 1):
            print(f"   {i}. {role}: {duration:.2f}s")

        print("\n" + "=" * 70)


# Global monitor instance (optional usage)
# Global monitor instance: an optional global singleton
# If the application only needs one monitor, it can be obtained via this variable, avoiding passing instances around
_global_monitor: Optional[WorkflowMonitor] = None

def get_monitor() -> Optional[WorkflowMonitor]:
    """Get global monitor instance.
    Return the currently configured global monitor, or None if it has not been created yet.
    """
    return _global_monitor

def create_monitor(workflow_id: str = None, output_dir: str = None) -> WorkflowMonitor:
    """Create and set global monitor.
    Also sets the global singleton so other modules can obtain it via get_monitor().

    Args:
        workflow_id: Unique workflow identifier
        output_dir: Output directory

    Returns:
        WorkflowMonitor: The newly created monitor instance
    """
    global _global_monitor  # Declare usage of the module-level global variable
    _global_monitor = WorkflowMonitor(workflow_id, output_dir)
    return _global_monitor
