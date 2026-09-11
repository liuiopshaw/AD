#!/usr/bin/env python3
"""Build CDA training data by querying PubChem + DrugBank + Materials Project APIs."""

import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env.example")

DATA_DIR = Path("E:/Cu-agent/data/training")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def query_pubchem():
    """Query PubChem for nanozyme-relevant compounds. Returns dict of element -> compound data."""
    print("[PubChem] Querying compounds...")
    try:
        from src.tools.pubchem_tool import get_pubchem_tool
        pc = get_pubchem_tool()
    except:
        print("  PubChem tool not available, skipping")
        return {}

    elements = {
        "Cu": ["CuO", "Cu2O", "CuCl2", "Cu(NO3)2"],
        "Fe": ["Fe3O4", "Fe2O3", "FeO", "FeCl3"],
        "Co": ["Co3O4", "CoO", "CoCl2", "Co(NO3)2"],
        "Mn": ["MnO2", "Mn3O4", "MnO", "MnCl2"],
        "Ce": ["CeO2", "CeCl3", "Ce(NO3)3"],
        "Ni": ["NiO", "NiCl2", "Ni(NO3)2"],
        "Pt": ["PtO2", "PtCl4"],
        "Au": ["HAuCl4", "AuCl3"],
        "Zn": ["ZnO", "ZnCl2", "Zn(NO3)2"],
        "Mo": ["MoS2", "MoO3", "Na2MoO4"],
        "V":  ["V2O5", "NH4VO3"],
        "Ru": ["RuO2", "RuCl3"],
        "Ti": ["TiO2"],
        "Ag": ["AgNO3", "Ag2O"],
    }
    results = {}
    for element, compounds in elements.items():
        element_data = []
        for compound in compounds[:2]:
            try:
                info = pc.get_compound_info(compound)
                if info and "CID" in str(info):
                    cid = info.get("Compound", {}).get("CID", "?")
                    mf = info.get("Compound", {}).get("MolecularFormula", "?")
                    mw = info.get("Compound", {}).get("MolecularWeight", "?")
                    element_data.append({"name": compound, "CID": cid, "formula": mf, "weight": mw})
            except:
                pass
        if element_data:
            results[element] = element_data
            print(f"  {element}: {len(element_data)} compounds")
    return results


def query_drugbank():
    """Query DrugBank for natural enzyme benchmarks."""
    print("[DrugBank] Querying enzymes...")
    try:
        from src.tools.drugbank_tool import DrugBankTool
        db = DrugBankTool()
    except:
        print("  DrugBank tool not available, skipping")
        return {}

    enzymes = [
        "NADH Dehydrogenase", "Catalase", "Superoxide Dismutase",
        "Cytochrome c Oxidase", "Peroxidase", "Glucose Oxidase",
        "NADPH Oxidase", "Xanthine Oxidase", "Laccase",
    ]
    results = {}
    for enzyme in enzymes:
        try:
            r = db.run(query=enzyme, query_type="enzyme_benchmark")
            results[enzyme] = r
            print(f"  {enzyme}: {'has data' if r.get('km_value') else 'structure only'}")
        except:
            pass
    return results


def format_api_data(pubchem: dict, drugbank: dict) -> str:
    """Format API results as readable text for training input."""
    lines = []
    lines.append("=== PUBCHEM COMPOUND DATA ===")
    for element, compounds in pubchem.items():
        for c in compounds:
            lines.append(f"  {c['name']} (CID:{c['CID']}, {c['formula']}, MW:{c['weight']}) [{element}]")

    lines.append("\n=== DRUGBANK ENZYME BENCHMARKS ===")
    for enzyme, data in drugbank.items():
        km = data.get("km_value", "?")
        kcat = data.get("kcat_value", "?")
        ph = data.get("optimal_pH", "?")
        cofactor = data.get("cofactor", "?")
        residues = ", ".join(data.get("active_site_residues", [])[:3])
        lines.append(f"  {enzyme}: Km={km}, kcat={kcat}, pH_opt={ph}, cofactor={cofactor}, active_site=[{residues}]")

    return "\n".join(lines)


def build_training_pairs(context: str) -> list:
    """Generate instruction-tuning pairs for CDA."""
    design_tasks = [
        "Design a Cu-based nanocluster (<3nm) with NADH oxidase-like activity. Propose 3 variants with different coatings (cyclodextrin, BSA, GSH). For each, predict NADH activity and explain based on Cu valence states.",
        "Design a Fe-based single-atom catalyst for NADH oxidation. Compare with Co, Mn, and Ni SAC variants. Which has the best predicted NADH activity and why?",
        "Design a bimetallic dual-atom catalyst (choose from Cu, Fe, Co, Mn) for enhanced NADH oxidase function. Explain the synergistic mechanism.",
        "Using the provided PubChem data, design 5 nanoparticle (5-20nm) candidates for NADH oxidase-like activity. For each: justify element choice and coating strategy.",
        "Design a CeO2 alternative for NADH oxidase that avoids rare earth elements. Use earth-abundant elements with similar mixed valence and band gap properties.",
        "Based on DrugBank NADH dehydrogenase data (active site structure, Km, cofactor), design a nanomaterial that mimics its active site geometry. What metal center and coordination would achieve comparable kinetics?",
        "Design a series of Cu-based materials across size scales: single-atom (0.2nm), nanocluster (2nm), nanoparticle (10nm). Compare predicted NADH activity — how does size affect performance?",
        "Design 3 nanomaterial candidates for Alzheimer's therapy via gut-brain axis. Each must have: NADH oxidase-like activity, selective antibacterial function, and biosafety. Justify all design choices.",
        "Design a V2O5-based nanocluster and a MoS2-based nanocluster. Compare predicted NADH activity based on band gap and mixed valence. Which is more promising?",
        "Propose 100 nanomaterial candidates covering all 4 size categories (single_atom, dual_atom, nanocluster, nanoparticle) for NADH oxidase-like activity. Use varied elements, coatings, and structures from the API data.",
    ]

    pairs = []
    for task in design_tasks:
        pairs.append({
            "instruction": task,
            "input": context[:4000],
            "output": ""  # Base model generates during training
        })
    print(f"  Generated {len(pairs)} base design scenarios")

    # Expand: repeat with element substitution to reach 300+
    expanded = list(pairs)
    elements = ["Cu", "Fe", "Co", "Mn", "Ce", "Ni", "Pt", "Au", "Zn", "Mo", "V", "Ru"]
    for i in range(len(pairs)):
        for el in elements[:6]:
            variant = json.loads(json.dumps(pairs[i]))
            variant["instruction"] = variant["instruction"].replace("Cu-based", f"{el}-based")
            variant["instruction"] += f" Focus on {el} compounds from the API data."
            expanded.append(variant)
            if len(expanded) >= 320:
                break
        if len(expanded) >= 320:
            break

    print(f"  Total training pairs: {len(expanded)}")
    return expanded


if __name__ == "__main__":
    print("=" * 50)
    print("Building CDA Training Data")
    print("=" * 50)

    pubchem = query_pubchem()
    drugbank = query_drugbank()

    print(f"\nPubChem: {len(pubchem)} elements, DrugBank: {len(drugbank)} enzymes")

    context = format_api_data(pubchem, drugbank)
    pairs = build_training_pairs(context)

    output = DATA_DIR / "cda_training_data.jsonl"
    with open(output, "w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    print(f"Saved {len(pairs)} training pairs to {output}")
