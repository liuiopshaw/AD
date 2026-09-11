#!/usr/bin/env python3
"""
Nano-Bio Evaluator — Selective Antibacterial Nanomaterial Screening Workflow

Entry point for the nano-bio evaluation pipeline.
Usage: python scripts/run_nano_bio.py
"""

import sys
import os
import asyncio

project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.abspath(project_root))

from dotenv import load_dotenv
load_dotenv()

_api_key = os.getenv('QWEN_API_KEY') or 'dummy'
_api_base = os.getenv('QWEN_API_BASE') or 'https://dashscope.aliyuncs.com/compatible-mode/v1'
os.environ['OPENAI_API_KEY'] = _api_key
os.environ['OPENAI_API_BASE'] = _api_base
os.environ['OPENAI_BASE_URL'] = _api_base

from src.config.config import Config
from src.utils.llm_config import create_llm
from src.utils.workflow_monitor import WorkflowMonitor, create_monitor


def create_nano_bio_agents(llm):
    """Create all 7 nano-bio evaluator agents."""
    from src.agents.task_organizing_agent import TaskOrganizingAgent
    from src.agents.Extracting_agent import ExtractingAgent
    from src.agents.antimicrobial_agent import AntimicrobialAgent
    from src.agents.enzyme_activity_agent import EnzymeActivityAgent
    from src.agents.biosafety_agent import BiosafetyAgent
    from src.agents.Mechanism_Mining_agent import MechanismMiningAgent
    from src.agents.comparison_agent import ComparisonAgent

    return {
        'coordinator': TaskOrganizingAgent(llm).create_agent(),
        'extractor': ExtractingAgent(llm).create_agent(),
        'apa': AntimicrobialAgent(llm).create_agent(),
        'epa': EnzymeActivityAgent(llm).create_agent(),
        'bsa': BiosafetyAgent(llm).create_agent(),
        'mma': MechanismMiningAgent(llm).create_agent(),
        'ca': ComparisonAgent(llm).create_agent()
    }


def get_user_input():
    """Get nanomaterial comparison requirements from user."""
    print("\n" + "=" * 70)
    print("Nano-Bio Evaluator — Selective Antibacterial Nanomaterial Screening")
    print("=" * 70)
    print("\nExample: Compare Cu_NC_CD, Ag_NP, ZnO_NP for selective antibacterial")
    print("activity against gut microbiota, enzyme-like activity (CAT/SOD/NADH),")
    print("and biosafety. Assess Alzheimer's therapeutic potential via gut-brain axis.")
    return input("\nEnter your material comparison query: ")


async def run_nano_bio_workflow(user_input: str, llm, monitor=None):
    """Execute nano-bio evaluation workflow with parallel agent execution."""
    from crewai import Crew, Process
    from src.tasks.antimicrobial_task import AntimicrobialTask
    from src.tasks.enzyme_activity_task import EnzymeActivityTask
    from src.tasks.biosafety_task import BiosafetyTask
    from src.tasks.mechanism_analysis_task import MechanismAnalysisTask
    from src.tasks.comparison_task import ComparisonTask

    agents = create_nano_bio_agents(llm)

    # Create tasks — evaluation agents run in parallel
    apa_task = AntimicrobialTask(agents['apa']).create_task(
        agents['apa'], user_requirement=user_input)
    apa_task.async_execution = True

    epa_task = EnzymeActivityTask(agents['epa']).create_task(
        agents['epa'], user_requirement=user_input)
    epa_task.async_execution = True

    bsa_task = BiosafetyTask(agents['bsa']).create_task(
        agents['bsa'], user_requirement=user_input)
    bsa_task.async_execution = True

    mma_task = MechanismAnalysisTask(agents['mma']).create_task(
        agents['mma'], user_requirement=user_input)
    mma_task.async_execution = True

    ca_task = ComparisonTask(agents['ca']).create_task(
        agents['ca'],
        context_tasks=[apa_task, epa_task, bsa_task, mma_task],
        user_requirement=user_input
    )

    crew = Crew(
        name="Nano-Bio-Evaluator",
        agents=[agents['apa'], agents['epa'], agents['bsa'],
                agents['mma'], agents['ca']],
        tasks=[apa_task, epa_task, bsa_task, mma_task, ca_task],
        process=Process.sequential,
        verbose=Config.VERBOSE,
        memory=False
    )

    print("\n⚡ Starting evaluation — APA/EPA/BSA/MMA running in parallel...")
    result = await crew.akickoff(inputs={'requirement': user_input})

    if monitor:
        monitor.set_final_result(result, "completed")
        monitor.save_report()

    return result


async def main():
    llm = create_llm()
    user_input = get_user_input()
    monitor = create_monitor()
    result = await run_nano_bio_workflow(user_input, llm, monitor)
    print("\n" + "=" * 70)
    print("Evaluation Complete!")
    print("=" * 70)
    print(str(result)[:2000])
    return result


if __name__ == "__main__":
    asyncio.run(main())
