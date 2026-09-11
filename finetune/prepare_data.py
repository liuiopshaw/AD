#!/usr/bin/env python3
"""Training data preparation pipeline for nano-bio evaluator agents.

Converts literature-extracted and experimental data into instruction-tuning
JSONL format compatible with LLaMA-Factory.

Data sources (priority order):
1. Local experiment DB (highest priority)
2. Curated literature JSON (curated_nano_bio.json)
3. Public database queries (PubChem, DrugBank, Materials Project)

Output: data/training/{agent}_training_data.jsonl
"""

import json
import sqlite3
from pathlib import Path


AGENT_TEMPLATES = {
    "ea": {
        "instruction": "Extract structured information about the nanomaterial from the following text, including physicochemical properties, enzyme activity data, selective antibacterial data, and safety data.",
        "output_schema": ["material_name", "type", "size_nm", "coating", "core_elements",
                          "cat_like_activity", "sod_like_activity", "nadh_oxidase_like_activity",
                          "selective_antibacterial_ratio", "target_pathogens", "probiotic_effects",
                          "organ_damage_data"]
    },
    "apa": {
        "instruction": "Evaluate the selective antibacterial performance of this nanomaterial against gut microbiota. Score across 4 dimensions: potency (40%), selectivity (35%), spectrum (15%), resistance risk (10%).",
        "output_schema": ["potency_score", "selectivity_score", "spectrum_score",
                          "resistance_score", "selectivity_ratio", "in_vitro_verified",
                          "in_vivo_verified"]
    },
    "epa": {
        "instruction": "Classify the enzyme-like catalytic activity of this nanomaterial. Focus on CAT-like, SOD-like, and NADH oxidase-like activities. Score: activity strength (65%), substrate affinity (25%), condition window (10%). NADH oxidase-like receives bonus.",
        "output_schema": ["cat_like_level", "sod_like_level", "nadh_oxidase_like_level",
                          "activity_strength_score", "substrate_affinity_score",
                          "condition_window_score", "ad_therapeutic_relevance"]
    },
    "bsa": {
        "instruction": "Assess the biosafety of this nanomaterial. Score: cytotoxicity (30%), organ damage (25%), in-vivo toxicity (20%), environmental risk (15%), structural stability (10%). Predict damage to liver, kidney, spleen, and brain.",
        "output_schema": ["cytotoxicity_score", "organ_damage_score", "in_vivo_score",
                          "environmental_score", "stability_score", "safety_grade",
                          "liver_risk", "kidney_risk", "spleen_risk", "brain_risk"]
    },
    "mma": {
        "instruction": "Explain the selective antibacterial mechanism of this nanomaterial. Why does it show differential activity against pathogens vs probiotics? Describe the gut-brain axis pathway through which gut microbiota modulation may treat Alzheimer's disease.",
        "output_schema": ["selective_mechanism", "ros_pathway", "cell_wall_differential",
                          "gut_brain_axis_pathway", "scfa_modulation", "neuroinflammation_reduction"]
    },
    "toa": {
        "instruction": "Analyze the user's intent. Determine which agents need to be activated: material extraction, antibacterial evaluation, enzyme activity classification, biosafety assessment, mechanism analysis, or comparison.",
        "output_schema": ["needs_extraction", "needs_antibacterial", "needs_enzyme",
                          "needs_biosafety", "needs_mechanism", "needs_comparison",
                          "evaluation_mode", "material_provided"]
    },
    "ca": {
        "instruction": "Aggregate multi-dimensional scores for all candidate materials. Apply consistency coefficient Cj fusion: Cj = 1 − (1/3)Σ(Wij−W̄j)²/W̄j, Sj = W̄j×Cj. Rank materials and recommend the best candidate for selective antibacterial Alzheimer's therapy via gut microbiota modulation.",
        "output_schema": ["comparison_matrix", "rankings", "radar_chart_data",
                          "best_material", "recommendations", "selective_mechanism_report",
                          "ad_therapeutic_potential"]
    }
}


def prepare_training_data():
    output_dir = Path("data/training")
    output_dir.mkdir(parents=True, exist_ok=True)

    for agent_name, template in AGENT_TEMPLATES.items():
        entries = []
        # Priority 1: Local experiment DB
        db_entries = _extract_from_local_db(agent_name)
        entries.extend(db_entries)

        # Priority 2: Curated literature
        lit_entries = _extract_from_curated_literature(agent_name)
        entries.extend(lit_entries)

        if entries:
            output_path = output_dir / f"{agent_name}_training_data.jsonl"
            with open(output_path, "w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(f"{agent_name}: {len(entries)} training pairs → {output_path}")
        else:
            print(f"{agent_name}: No training data found (create manually)")


def _extract_from_local_db(agent_name: str) -> list:
    """Extract training pairs from local experiment database."""
    entries = []
    db_path = Path("data/local_experiments.db")
    if not db_path.exists():
        return entries

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name, type, core_element, coating, size_mean_nm, shape, notes FROM materials")
        rows = cursor.fetchall()
        for row in rows:
            material_desc = f"Material: {row[0]}, Type: {row[1]}, Core: {row[2]}, Coating: {row[3]}, Size: {row[4]}nm, Shape: {row[5]}. Notes: {row[6]}"
            entries.append({
                "instruction": AGENT_TEMPLATES[agent_name]["instruction"],
                "input": material_desc,
                "output": ""
            })
        conn.close()
    except Exception as e:
        print(f"  DB extraction failed for {agent_name}: {e}")
    return entries


def _extract_from_curated_literature(agent_name: str) -> list:
    """Extract training pairs from curated literature database."""
    entries = []
    lit_path = Path("data/literature/curated_nano_bio.json")
    if not lit_path.exists():
        return entries
    try:
        with open(lit_path, "r", encoding="utf-8") as f:
            articles = json.load(f)
        for article in articles:
            if article.get("training_pair"):
                pair = article["training_pair"]
                if agent_name in pair.get("applicable_agents", []):
                    entries.append({
                        "instruction": AGENT_TEMPLATES[agent_name]["instruction"],
                        "input": pair.get("input", ""),
                        "output": pair.get("output", "")
                    })
    except Exception as e:
        print(f"  Literature extraction failed for {agent_name}: {e}")
    return entries


if __name__ == "__main__":
    prepare_training_data()
