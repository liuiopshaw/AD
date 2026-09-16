"""
Task Callback Factory.
Creates callbacks for monitoring parallel task execution.

This module provides a factory function that creates CrewAI task callbacks
with special handling for parallel task timing. When multiple tasks execute
concurrently (e.g., evaluation agents A/B/C), the factory correctly assigns
shared start times to the parallel group instead of sequential timing.
"""

# time: used to record task execution timestamps and compute durations
import time


def create_task_callback_factory(monitor, task_start_times, current_agent_context, last_completed_agent):
    """
    Create the task callback factory function (with timing support for parallel tasks)

    The core design goal of this factory is to correctly handle the timing of
    parallel tasks: when the three evaluation experts A, B, and C run in
    parallel, they should share the same start time (the moment the design
    task completed) instead of each being timed independently.

    The factory returns a closure, create_task_callback, which returns a new
    task_callback instance each time it is called. This design allows
    non-interfering callbacks to be created for different Crew instances.

    Key design points:
    - Context such as task_completion_times must be passed in, because the
      same program may create multiple Crews
    - eval_start_key marks the shared start time of the evaluation group
    - last_completed_agent tracks interaction relationships between agents

    Args:
        monitor: WorkflowMonitor instance -- the monitor that receives execution reports
        task_start_times: dict -- records the start time of each task
        current_agent_context: threading.local instance -- thread-local storage for the current agent
        last_completed_agent: list -- records the role of the agent that last completed a task

    Returns:
        function: the factory function create_task_callback(task_completion_times, crew_start_time, task_counter, suffix="")
    """

    def create_task_callback(task_completion_times, crew_start_time, task_counter, suffix=""):
        """
        Create the task_callback function for a specific Crew instance

        Each Crew needs its own callback instance because they have independent:
        - task_completion_times: list of task completion times (used to compute
          the start time of subsequent tasks)
        - crew_start_time: Crew start time (wrapped in a list, used as the time
          baseline for the first task)
        - task_counter: task sequence counter (wrapped in a list)

        The suffix parameter allows creating keys in different namespaces for
        multiple Crews in the same program, preventing their timing information
        from overwriting each other.

        Args:
            task_completion_times: list of task completion timestamps
            crew_start_time: single-element list containing the Crew start time
            task_counter: single-element list holding the task sequence counter
            suffix: key suffix used to distinguish multiple Crews (e.g. "_2")

        Returns:
            function: the task_callback(task_output) callback function
        """
        # Shared start-time key for the evaluation group (suffix distinguishes Crews)
        eval_start_key = f'eval_start_time{suffix}'

        def task_callback(task_output):
            """
            Callback invoked when a task completes

            CrewAI automatically calls this callback after each task completes,
            passing in a TaskOutput object. The callback performs the following:
            1. Increment the task sequence number
            2. Extract agent information from the TaskOutput
            3. Handle timing logic for parallel tasks (evaluation group shares a start time)
            4. Notify the monitor to record execution information
            5. Record interaction relationships between agents (task handoff)

            Args:
                task_output: CrewAI TaskOutput object
            """
            # Increment the task counter (list-wrapped so it can be modified in the closure)
            task_counter[0] += 1
            task_id = task_counter[0]

            # Extract agent identity information from task_output
            # The agent attribute may be a string or an Agent object
            agent_str = getattr(task_output, 'agent', None) or 'Unknown'
            # Task name: prefer task_output.name, otherwise generate one automatically
            task_name = getattr(task_output, 'name', None) or f"{agent_str}_Task_{task_id}"
            # Task description (for the details section of the monitoring report)
            task_description = getattr(task_output, 'description', 'N/A')
            agent_name = agent_str
            agent_role = agent_str

            # Update the current agent role in thread-local storage
            # so functions like step_callback can read the current context
            current_agent_context.role = agent_role

            # Try to extract structured JSON output (e.g. evaluation scores, rankings)
            json_output = None
            if hasattr(task_output, 'json_dict') and task_output.json_dict:
                json_output = task_output.json_dict

            # Only perform detailed recording and timing when the monitor is available
            if monitor:
                current_time = time.time()

                # ---- Parallel task timing logic ----
                # Detect whether the current task is a parallel evaluation task
                # (an ASA expert whose role name ends in A/B/C)
                is_parallel_eval = 'Assessment_Screening_agent_' in agent_role and agent_role[-1] in 'ABC'

                if is_parallel_eval:
                    # Start-time handling for parallel evaluation tasks:
                    # the three experts (A/B/C) share the same start time.
                    # If eval_start_key has not been set yet (this is the first
                    # task of the evaluation group), use the previous task's
                    # completion time or the Crew start time as the start time
                    if eval_start_key not in task_start_times:
                        if task_completion_times:
                            # Use the completion time of the previous non-evaluation (design) task
                            task_start_times[eval_start_key] = task_completion_times[-1]
                        elif crew_start_time[0]:
                            # If no task has completed yet, use the Crew start time
                            task_start_times[eval_start_key] = crew_start_time[0]
                        else:
                            # Fallback: use the current time
                            task_start_times[eval_start_key] = current_time
                    # All evaluation tasks reuse the same start time
                    actual_start = task_start_times[eval_start_key]
                else:
                    # Start time for non-parallel tasks:
                    # for the first task use the Crew start time; otherwise use
                    # the previous task's completion time
                    if task_completion_times:
                        actual_start = task_completion_times[-1]
                    elif crew_start_time[0]:
                        actual_start = crew_start_time[0]
                    else:
                        actual_start = current_time

                # Record the completion time of the current task (used to compute
                # the start time of the next task)
                task_completion_times.append(current_time)

                # Use (agent_role, task_id) as the unique key for the task,
                # preventing parallel tasks of the same type from overwriting
                # each other's information
                unique_task_key = f"{agent_role}_{task_id}"
                if unique_task_key not in task_start_times:
                    # First time seeing this task key -- record it with the monitor
                    task_start_times[unique_task_key] = actual_start
                    monitor.start_agent_execution(agent_name, agent_role, task_name, task_description)
                    # If the monitor has a current execution record, set the start time
                    if monitor._current_execution:
                        monitor._current_execution.start_time = actual_start

                # End the agent execution record -- pass the output content for
                # the monitor to save
                monitor.end_agent_execution(output=str(task_output), json_output=json_output, agent_role=agent_role)

                # ---- Agent interaction recording ----
                # When the previously completed agent differs from the current
                # agent, record a "task_handoff" interaction.
                # This builds the information-passing graph between agents in
                # the workflow
                if last_completed_agent[0] and last_completed_agent[0] != agent_role:
                    monitor.record_interaction(
                        from_agent=last_completed_agent[0],
                        to_agent=agent_role,
                        interaction_type="task_handoff",  # interaction type: task handoff
                        content=f"Task completed: {task_name}"
                    )
                # Update the role of the last completed agent
                last_completed_agent[0] = agent_role

        # Return the configured callback function
        return task_callback

    # Return the factory function itself (return a function rather than calling it)
    return create_task_callback
