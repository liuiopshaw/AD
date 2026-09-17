#!/usr/bin/env python3
"""Delivery Efficiency Scoring Agent (formerly EPA) — target-tissue delivery evaluation."""

from .base_agent import BaseAgent
from src.tools import ToolFactory
from src.tools.enzyme_classifier import EnzymeClassifier


class EnzymeActivityAgent(BaseAgent):
    """Target-tissue delivery efficiency scoring agent.

    Assesses whether an AD therapeutic effectively reaches its site of action
    (barrier penetration & bioavailability, targeting & designability, exposure
    durability). Scoring follows the shared rubric anchors; no subjective bonus
    points. (Role renamed from enzyme-activity prediction; class name kept for
    backward compatibility.)
    """

    def __init__(self, llm):
        from src.config.config import Config
        super().__init__(
            llm=llm,
            role="delivery_efficiency_scoring_agent",
            goal="Score target-tissue delivery efficiency (delivery_efficiency) of AD therapeutics: "
                 "barrier penetration & bioavailability, targeting & designability, and exposure "
                 "durability, following the shared rubric anchors.",
            prompt_file="delivery_prompt.md",
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
