#!/usr/bin/env python3
"""Cross-material comparison task for CA agent."""

from crewai import Task


class ComparisonTask:
    def __init__(self, agent):
        self.agent = agent

    def create_task(self, agent, context_tasks=None, user_requirement=None):
        desc = (
            "Aggregate evaluation results from APA (antibacterial), EPA (enzyme activity), "
            "and BSA (biosafety) for all candidate materials. Apply consistency coefficient "
            "Cj fusion:\n"
            "  Cj = 1 − (1/3) × Σ(Wij − W̄j)² / W̄j\n"
            "  Sj = W̄j × Cj\n\n"
            "Rank materials by comprehensive score Sj. Produce comparison matrix, "
            "radar chart data, rankings, and top recommendation with:\n"
            "- Selective antibacterial mechanism explanation\n"
            "- Gut-brain axis pathway for Alzheimer's therapy potential\n"
            "- Organ-specific safety profile\n\n"
            "Sj ≥ 7.0 passes the threshold for strong recommendation."
        )

        task = Task(
            agent=agent,
            expected_output=(
                "JSON with comparison_matrix (rows per material), rankings (ordered list), "
                "radar_chart_data (dimensions + datasets), recommendations (list), "
                "best_material, selective_mechanism_report, ad_therapeutic_potential"
            ),
            description=desc
        )
        if context_tasks:
            task.context = context_tasks if isinstance(context_tasks, list) else [context_tasks]
        return task
