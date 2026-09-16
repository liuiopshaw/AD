#!/usr/bin/env python3
"""
End-to-end Nano-Bio Evaluator workflow.
Uses local Qwen3-VL-8B + 7 LoRA adapters via the API server.
Evaluates multiple nanomaterials: Cu_NC_CD, Ag_NP, ZnO_NP.
"""

import json, time, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_client

AGENTS = ["apa", "epa", "bsa", "mma", "ca"]
MATERIALS = ["Cu_NC_CD", "Ag_NP", "ZnO_NP"]


def query_agent(agent: str, prompt: str, temp: float = 0.3) -> str:
    """Call the LLM endpoint configured for the given agent (local LoRA
    adapter by default; cloud API if overridden in llm_endpoints.json)."""
    return llm_client.chat(agent, prompt, max_tokens=512, temperature=temp,
                           timeout=120, retries=1, retry_on_timeout=False)


def evaluate_material(name: str) -> dict:
    """Run all evaluation agents for one material."""
    print(f"\n{'='*50}")
    print(f"Evaluating: {name}")
    print(f"{'='*50}")

    results = {"material": name}

    # APA - Selective Antibacterial
    prompt = f"""Evaluate the selective antibacterial performance of {name} against gut microbiota.
Score on 4 dimensions (1-10 each):
1. Potency (40%): MIC against pathogens
2. Pathogen-Probiotic Selectivity (35%): MIC ratio
3. Spectrum (15%): G+/G- coverage
4. Resistance Risk (10%): evidence of resistance

Output as JSON with scores and brief reasoning."""
    print(f"  APA...")
    results["apa_response"] = query_agent("apa", prompt, 0.3)

    # EPA - Enzyme Activity
    prompt = f"""Classify enzyme-like activity of {name}.
Focus on: CAT-like, SOD-like, NADH oxidase-like.
Score: activity strength (65%, NADH-like gets bonus), substrate affinity (25%), condition window (10%).
Output JSON with enzyme types and confidence levels."""
    print(f"  EPA...")
    results["epa_response"] = query_agent("epa", prompt, 0.3)

    # BSA - Biosafety
    prompt = f"""Assess biosafety of {name}.
Score 5 dimensions (1-10):
1. Cytotoxicity (30%): IC50
2. Organ Damage (25%): liver/kidney/spleen/brain
3. In-vivo Toxicity (20%): hemolysis, inflammation
4. Environmental Risk (15%): PNEC
5. Structural Stability (10%): ion leaching
Output JSON with safety grade."""
    print(f"  BSA...")
    results["bsa_response"] = query_agent("bsa", prompt, 0.3)

    # MMA - Mechanism
    prompt = f"""Explain the selective antibacterial mechanism of {name}.
Why differential activity against pathogens vs probiotics?
Describe ROS pathway, gut-brain axis relevance for AD therapy."""
    print(f"  MMA...")
    results["mma_response"] = query_agent("mma", prompt, 0.3)

    return results


def compare_materials(results: list) -> str:
    """Run CA agent to compare all materials."""
    summary = ""
    for r in results:
        summary += f"\n{r['material']}:\n  APA: {r['apa_response'][:200]}\n  EPA: {r['epa_response'][:200]}\n  BSA: {r['bsa_response'][:200]}\n"

    prompt = f"""Compare these nanomaterials for selective antibacterial Alzheimer's therapy via gut-brain axis.
Use consistency coefficient Cj = 1 - (1/3)*sum((Wij-Wbar)^2) / Wbar.
Rank by comprehensive score Sj = Wbar * Cj.
Recommend the best candidate.

Evaluation data:
{summary}

Output: rankings, comparison matrix, radar data, final recommendation with AD therapeutic potential."""
    print(f"\n  CA - Comparing all materials...")
    return query_agent("ca", prompt, 0.1)


if __name__ == "__main__":
    print("=" * 60)
    print("Nano-Bio Evaluator — Multi-Material Comparison")
    print("=" * 60)

    all_results = []
    for mat in MATERIALS:
        r = evaluate_material(mat)
        all_results.append(r)
        time.sleep(0.5)

    print(f"\n{'='*60}")
    print("Cross-Material Comparison (CA)")
    print(f"{'='*60}")
    comparison = compare_materials(all_results)

    print(f"\n{'='*60}")
    print("FINAL REPORT")
    print(f"{'='*60}")
    print(comparison)

    # Save report
    with open(f"E:/ECOMATS/outputs/nano_bio_report_{int(time.time())}.txt", "w", encoding="utf-8") as f:
        f.write(f"Nano-Bio Evaluator Report\n{'='*60}\n\n")
        for r in all_results:
            f.write(f"\n## {r['material']}\n")
            f.write(f"APA: {r['apa_response']}\n")
            f.write(f"EPA: {r['epa_response']}\n")
            f.write(f"BSA: {r['bsa_response']}\n")
            f.write(f"MMA: {r['mma_response']}\n")
        f.write(f"\n## Comparison\n{comparison}\n")

    print(f"\nReport saved to outputs/")
