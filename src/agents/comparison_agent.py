#!/usr/bin/env python3
"""Comparison Agent (CA) — Multi-material cross-comparison with Cj fusion."""

import logging
from .base_agent import BaseAgent
from src.tools.material_compare import MaterialCompare

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class ComparisonAgent(BaseAgent):
    """Cross-material comparison and ranking agent.

    Aggregates APA, EPA, BSA scores, applies consistency coefficient Cj fusion,
    and produces comparison matrix, radar chart data, rankings, and recommendations.
    """

    def __init__(self, llm):
        from src.config.config import Config
        super().__init__(
            llm=llm,
            role="comparison_agent",
            goal="Aggregate multi-dimensional evaluation scores, fuse with consistency "
                 "coefficient Cj, generate cross-material comparison matrix, radar chart "
                 "data, rankings, and AD therapeutic potential recommendations.",
            prompt_file="ranker_prompt.md",
            temperature=Config.CA_TEMPERATURE,
            max_iter=1
        )
        self.material_compare = MaterialCompare()

    def create_agent(self):
        agent = super().create_agent()
        agent.tools = []
        return agent

    def calculate_comprehensive_score(self, apa_score: float, epa_score: float,
                                       bsa_score: float) -> float:
        """S_j = W̄_j × C_j

        C_j = 1 − (1/3) × Σ(W_ij − W̄_j)² / W̄_j
        """
        scores = [apa_score, epa_score, bsa_score]
        avg = sum(scores) / 3
        variance = sum((s - avg) ** 2 for s in scores) / 3
        if avg > 0:
            c_j = 1 - variance / avg
            c_j = max(c_j, 0.5)  # floor at 0.5 to avoid over-penalization
        else:
            c_j = 0
        return round(avg * c_j, 2)

    def compare(self, evaluations: list) -> dict:
        """Run full comparison pipeline."""
        return self.material_compare.run(evaluations)
