#!/usr/bin/env python3
"""Biosafety Assessment Agent (BSA) — Cytotoxicity, organ damage, in-vivo, environmental risk."""

from .base_agent import BaseAgent
from src.tools import ToolFactory


class BiosafetyAgent(BaseAgent):
    """Biosafety assessment agent.

    Evaluates nanomaterial safety across 5 dimensions including major organ damage
    (liver, kidney, spleen, brain) prediction.
    """

    def __init__(self, llm):
        from src.config.config import Config
        super().__init__(
            llm=llm,
            role="biosafety_assessment_agent",
            goal="Assess nanomaterial biosafety including cytotoxicity, major organ damage "
                 "(liver, kidney, spleen, brain), in-vivo toxicity, environmental risk, "
                 "and structural stability under physiological conditions.",
            prompt_file="biosafety_agent_prompt.md",
            temperature=Config.BSA_TEMPERATURE,
            max_iter=1
        )

    def create_agent(self):
        # LLM 的选择（EAS / 带温度标准 LLM / 默认 LLM）已统一收敛到
        # BaseAgent._resolve_llm()，此处不再重复创建
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
