#!/usr/bin/env python3
"""Antimicrobial Prediction Agent (APA) — Selective antibacterial performance evaluation."""

import logging
from .base_agent import BaseAgent
from src.tools import ToolFactory

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class AntimicrobialAgent(BaseAgent):
    """Selective antibacterial performance prediction agent.

    Evaluates nanomaterial antibacterial activity against gut microbiota
    with focus on pathogen-probiotic selectivity (in vitro + in vivo).
    """

    def __init__(self, llm):
        from src.config.config import Config
        super().__init__(
            llm=llm,
            role="antimicrobial_prediction_agent",
            goal="Predict selective antibacterial performance of nanomaterials — "
                 "strong inhibition against gut pathogens with minimal impact on probiotics. "
                 "Support in vitro and in vivo selectivity assessment for Alzheimer's "
                 "treatment via gut microbiota modulation.",
            prompt_file="antimicrobial_agent_prompt.md",
            temperature=Config.APA_TEMPERATURE,
            max_iter=1
        )

    def create_agent(self):
        # LLM selection (EAS / standard LLM with temperature / default LLM)
        # is centralized in BaseAgent._resolve_llm(); not recreated here
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
