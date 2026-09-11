#!/usr/bin/env python3
"""Enzyme Activity Prediction Agent (EPA) — CAT-like, SOD-like, NADH oxidase-like evaluation."""

from .base_agent import BaseAgent
from src.tools import ToolFactory
from src.tools.enzyme_classifier import EnzymeClassifier


class EnzymeActivityAgent(BaseAgent):
    """Enzyme-like activity prediction agent.

    Focuses on CAT-like, SOD-like, and NADH oxidase-like activities.
    NADH oxidase-like activity receives bonus scoring for AD therapeutic relevance.
    """

    def __init__(self, llm):
        from src.config.config import Config
        super().__init__(
            llm=llm,
            role="enzyme_activity_prediction_agent",
            goal="Classify enzyme-like catalytic activity (CAT-like, SOD-like, NADH oxidase-like) "
                 "of nanomaterials with activity strength levels and substrate affinity assessment. "
                 "NADH oxidase-like activity receives priority due to NAD+ replenishment value "
                 "for Alzheimer's therapy.",
            prompt_file="enzyme_activity_agent_prompt.md",
            temperature=Config.EPA_TEMPERATURE,
            max_iter=1
        )
        self.enzyme_classifier = EnzymeClassifier()

    def create_agent(self):
        agent = super().create_agent()
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                agent.tools = ToolFactory.create_unified_assessment_tools()
            else:
                agent.tools = []
        except Exception:
            agent.tools = ToolFactory.create_unified_assessment_tools()
        return agent

    def classify_structure(self, material_properties: dict) -> dict:
        """Use rule-based classifier for initial enzyme activity assessment."""
        return self.enzyme_classifier.run(material_properties)
