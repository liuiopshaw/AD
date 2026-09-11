#!/usr/bin/env python3
"""
Agent-driven discovery pipeline. TOA orchestrates everything.
ALL agent outputs preserved RAW without modification.
"""

import sys, os, json, time, logging
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discover")

SERVER = "http://localhost:8000/v1/chat/completions"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from output_utils import run_dir

TIMESTAMP = int(time.time())
OUTPUT_DIR = run_dir(TIMESTAMP)  # per-run folder: outputs/run_<TS>/


def call_agent(agent: str, prompt: str, max_tokens: int = 10240, temperature: float = 0.2, retries: int = 3) -> str:
    # Wait for server to be ready (previous model fully unloaded)
    for attempt in range(retries):
        try:
            r = httpx.post(SERVER, json={
                "model": "nano-bio", "agent": agent,
                "messages": [{"role": "user", "content": prompt[:10000]}],
                "max_tokens": max_tokens, "temperature": temperature,
            }, timeout=1800)

            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            elif r.status_code in (502, 503):
                # Server still unloading previous model, wait and retry
                logger.warning(f"  {agent} got {r.status_code}, retrying in 10s... (attempt {attempt+1}/{retries})")
                time.sleep(10)
            else:
                return f"ERROR {r.status_code}: {r.text[:300]}"
        except httpx.ReadTimeout:
            logger.warning(f"  {agent} timeout, retrying... (attempt {attempt+1}/{retries})")
            time.sleep(5)
        except Exception as e:
            logger.warning(f"  {agent} connection error: {e}, retrying... (attempt {attempt+1}/{retries})")
            time.sleep(5)

    return f"ERROR: failed after {retries} retries"


def save_raw(filename: str, content: str):
    path = OUTPUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  -> {path}")


# ============================================================
# Step 0: Call actual API tools
# ============================================================
print("=" * 60)
print("STEP 0: External API tool calls (no agent involved)")
print("=" * 60)

api_data_parts = []

# PubChem
print("[PubChem]")
try:
    from src.tools.pubchem_tool import get_pubchem_tool
    pc = get_pubchem_tool()
    pc_text = []
    compounds = ["Fe3O4", "CeO2", "Co3O4", "MnO2", "CuO", "TiO2", "MoS2",
                 "V2O5", "ZnO", "Pr6O11", "Cu2O", "Fe2O3", "NiO", "Fe3O4 nanoparticle"]
    for name in compounds:
        try:
            info = pc.get_compound_info(name)
            if info:
                pc_text.append(f"Compound: {name}\n{json.dumps(info, ensure_ascii=False)[:1500]}")
        except Exception as e:
            pc_text.append(f"Compound: {name}\nERROR: {e}")
    api_data_parts.append("=== PUBCHEM ===\n" + "\n\n".join(pc_text))
except Exception as e:
    api_data_parts.append(f"=== PUBCHEM ===\n{e}")

# PubMed (NanoLitSearch)
print("[PubMed]")
try:
    from src.tools.nanolit_search_tool import NanoLitSearchTool
    nl = NanoLitSearchTool()
    nl_text = []
    for q in ["nanozyme NADH oxidase", "nanocluster enzyme-like", "single-atom catalyst oxidase"]:
        try:
            r = nl.run(query=q, query_type="comprehensive")
            nl_text.append(f"Query: {q}\n{json.dumps(r, ensure_ascii=False)[:2000]}")
        except Exception as e:
            nl_text.append(f"Query: {q}\nERROR: {e}")
    api_data_parts.append("=== PUBMED ===\n" + "\n\n".join(nl_text))
except Exception as e:
    api_data_parts.append(f"=== PUBMED ===\n{e}")

# Materials Project
print("[Materials Project]")
try:
    from src.tools.materials_project_tool import get_materials_project_tool
    mp = get_materials_project_tool()
    mp_text = []
    for f in ["Fe3O4", "CeO2", "Co3O4", "MnO2", "CuO", "TiO2", "MoS2"]:
        try:
            r = mp.search_materials(formula=f, limit=5)
            mp_text.append(f"Formula: {f}\n{json.dumps(r, ensure_ascii=False)[:1500]}")
        except Exception as e:
            mp_text.append(f"Formula: {f}\nERROR: {e}")
    api_data_parts.append("=== MATERIALS PROJECT ===\n" + "\n\n".join(mp_text))
except Exception as e:
    api_data_parts.append(f"=== MATERIALS PROJECT ===\n{e}")

# DrugBank
print("[DrugBank]")
try:
    from src.tools.drugbank_tool import DrugBankTool
    db = DrugBankTool()
    db_text = []
    for enz in ["Catalase", "Superoxide Dismutase", "NADH Dehydrogenase"]:
        try:
            r = db.run(query=enz, query_type="enzyme_benchmark")
            db_text.append(f"Enzyme: {enz}\n{json.dumps(r, ensure_ascii=False)[:1500]}")
        except Exception as e:
            db_text.append(f"Enzyme: {enz}\nERROR: {e}")
    api_data_parts.append("=== DRUGBANK ===\n" + "\n\n".join(db_text))
except Exception as e:
    api_data_parts.append(f"=== DRUGBANK ===\n{e}")

api_data = "\n\n".join(api_data_parts)
save_raw(f"step0_tool_data_{TIMESTAMP}.txt", api_data)
print(f"  Total tool data: {len(api_data)} chars\n")

# ============================================================
# Step 1: TOA analyzes intent and decides task plan
# ============================================================
print("=" * 60)
print("STEP 1: TOA — Analyze user intent, decide task plan")
print("=" * 60)

user_requirement = """
Analyze 100 nanomaterials reported in literature and databases for their
NADH oxidase-like enzyme activity. Categorize by size:
- single_atom (<0.3nm)
- dual_atom (0.3-0.6nm)
- nanocluster (0.5-3nm)
- nanoparticle (>3nm)

Available data from: PubChem, PubMed, Materials Project, DrugBank APIs.
Available agents: EA (extraction), APA (antibacterial), EPA (enzyme),
BSA (biosafety), MMA (mechanism), CA (comparison).
"""

toa_prompt = f"""You are the Task Orchestration Agent (TOA). Analyze the user's requirement and decide which agents to activate, in what order.

User requirement:
{user_requirement}

Available API data has been collected from PubChem, PubMed, Materials Project, DrugBank (see below for a summary).

API data summary (first 3000 chars):
{api_data[:3000]}

Your job: Output a JSON task plan with:
1. intent: brief analysis of what the user wants
2. agents_needed: list of agent names (ea, apa, epa, bsa, mma, ca) to activate, in execution order
3. task_sequence: for each agent, describe what it should do
4. data_flow: how data moves between agents

Output ONLY valid JSON."""

toa_raw = call_agent("toa", toa_prompt, max_tokens=2048, temperature=0.1)
save_raw(f"toa_plan_{TIMESTAMP}.txt", toa_raw)
print(f"  TOA plan saved ({len(toa_raw)} chars)\n")
time.sleep(15)  # Let server fully unload TOA model before next agent

# ============================================================
# Step 1.5: CDA — Design nanomaterial candidates from API data
# ============================================================
print("=" * 60)
print("STEP 1.5: CDA — Design nanomaterial candidates from API data")
print("=" * 60)

cda_prompt = f"""You are a creative nanomaterial design agent. Use the API data below to DESIGN novel nanomaterial candidates for NADH oxidase-like enzyme activity.

For each design, provide:
- Material name (precise, with coating/ligand)
- Size (nm)
- Core elements
- Size category (single_atom, dual_atom, nanocluster, nanoparticle)
- Predicted NADH activity (YES/NO) with reasoning
- Design innovation: what makes this candidate novel

Cover ALL four size categories. Use varied element combinations and coatings from the API data.

API Data:
{api_data[:10000]}

Output ONE material per line in this format:
Material_Name | Size_nm | Core_Elements | Size_Category | NADH_Prediction | Design_Rationale

Design at least 100 candidates."""

try:
    cda_raw = call_agent("cda", cda_prompt, max_tokens=10240, temperature=0.7)
    save_raw(f"cda_designs_{TIMESTAMP}.txt", cda_raw)
    print(f"  CDA done ({len(cda_raw)} chars)")
    time.sleep(15)
except Exception as e:
    cda_raw = f"ERROR: {e}"
    save_raw(f"cda_designs_{TIMESTAMP}.txt", cda_raw)
    print(f"  CDA FAILED: {e}")
    cda_raw = ""

# ============================================================
# Step 2: EA extracts structured material list from API data
# ============================================================
print("=" * 60)
print("STEP 2: EA — Extract material list from API data (as TOA instructed)")
print("=" * 60)

ea_prompt = f"""You are a nanomaterial knowledge extraction agent. Extract ALL nanomaterials mentioned in the following API data.

CRITICAL: Extract materials from ALL sources:
- PubChem: structured compound data (CID, molecular formula)
- PubMed: paper TITLES contain rich material names (e.g., "Platinum nanoparticle-deposited multi-walled carbon nanotubes as a NADH oxidase mimic" → Pt_NP_MWCNT)
- Materials Project: crystal structure data
- DrugBank: natural enzyme benchmarks (for size/property reference)

For each material found, output ONE line in this exact format:
Material Name | Size (nm) | Core Elements | Size Category | Source

Rules:
- Material Name: precise, include coating/ligand if mentioned (e.g., Cu_NC_CD, Pt_NP_MWCNT, Fe-N-C_SAC)
- Size (nm): extract from text if available; if not, ESTIMATE based on material type:
  - single-atom: 0.15-0.25nm
  - dual-atom: 0.3-0.5nm
  - nanocluster: 1-3nm
  - nanoparticle: estimate from context, default 10-20nm
- Core Elements: chemical symbols, comma-separated (e.g., Fe,O or Pt,C or Cu,N,C)
- Size Category: EXACTLY one of: single_atom, dual_atom, nanocluster, nanoparticle
- Source: PUBCHEM, PUBMED, MATERIALS_PROJECT, or DRUGBANK

IMPORTANT: Extract materials from PubMed paper TITLES! Many papers describe specific nanomaterials.
For example:
- "Single-Atomic Iron Doped Carbon Dots" → Fe_Carbon_QD | 3 | Fe,C | nanocluster | PUBMED
- "Platinum nanoparticle-deposited multi-walled carbon nanotubes" → Pt_NP_MWCNT | 5 | Pt,C | nanoparticle | PUBMED
- "Ruthenium Single-Atom Catalyst" → Ru_SAC | 0.2 | Ru | single_atom | PUBMED
- "Nonmetallic N/C Nanozyme" → N_C_Nanozyme | 5 | N,C | nanocluster | PUBMED
- "Protein-protected metal nanoclusters" → Metal_NC_Protein | 2 | Au,Ag,Cu | nanocluster | PUBMED
- "Cu-N-C peroxidase mimics" → Cu-N-C_SAC | 0.2 | Cu,N,C | single_atom | PUBMED
- "Zn-Based Single-Atom Nanozyme" → Zn_SAC | 0.2 | Zn | single_atom | PUBMED
- "Fe-N-C Single-Atom Nanozymes" → Fe-N-C_SAC | 0.2 | Fe,N,C | single_atom | PUBMED
- "MOF-Based Single-Atom and Metal Cluster Catalysts" → MOF_SAC_Cluster | 0.3-2 | Fe,Cu,Zn | dual_atom | PUBMED

API Data:
{api_data[:15000]}

Output ONLY material lines. NO intro. NO summary. ONE material per line. Aim for 50+ materials."""

try:
    ea_raw = call_agent("ea", ea_prompt, max_tokens=10240, temperature=0.2)
    save_raw(f"ea_materials_{TIMESTAMP}.txt", ea_raw)
    print(f"  EA done ({len(ea_raw)} chars)")
    time.sleep(15)  # Let server fully unload before next agent
except Exception as e:
    ea_raw = f"ERROR: {e}"
    save_raw(f"ea_materials_{TIMESTAMP}.txt", ea_raw)
    print(f"  EA FAILED: {e}")
    ea_raw = ""

# ============================================================
# Step 3: EPA classifies NADH activity
# ============================================================
print("=" * 60)
print("STEP 3: EPA — NADH oxidase activity classification")
print("=" * 60)

epa_prompt = f"""Classify each material for NADH oxidase-like activity (YES/NO with reasoning).

NADH indicators: Cu/Fe/Mn/Co/Ni/Pt/Au core, size <10nm, organic coating, mixed valence, band gap 0.1-3.0eV.

Materials (from EA):
{ea_raw}

Output ONE LINE per material:
Name | Size | Category | NADH_YES/NO | Reasoning"""

try:
    epa_raw = call_agent("epa", epa_prompt, max_tokens=10240, temperature=0.2)
    save_raw(f"epa_nadh_{TIMESTAMP}.txt", epa_raw)
    print(f"  EPA done ({len(epa_raw)} chars)")
    time.sleep(15)
except Exception as e:
    epa_raw = f"ERROR: {e}"
    save_raw(f"epa_nadh_{TIMESTAMP}.txt", epa_raw)
    print(f"  EPA FAILED: {e}")
    epa_raw = ""

# ============================================================
# Step 4: CA summarizes
# ============================================================
print("=" * 60)
print("STEP 4: CA — Summary report")
print("=" * 60)

ca_prompt = f"""Generate summary report from the NADH classification below.

Report sections:
1. Total count, NADH+ count and rate
2. By size category: counts and NADH+ rates
3. Top NADH+ candidates
4. Key element/size/coating patterns predicting NADH activity

Classification data:
{epa_raw}"""

try:
    ca_raw = call_agent("ca", ca_prompt, max_tokens=4096, temperature=0.2)
    save_raw(f"ca_summary_{TIMESTAMP}.txt", ca_raw)
    print(f"  CA done ({len(ca_raw)} chars)")
except Exception as e:
    ca_raw = f"ERROR: {e}"
    save_raw(f"ca_summary_{TIMESTAMP}.txt", ca_raw)
    print(f"  CA FAILED: {e}")

# ============================================================
print(f"\n{'='*60}")
print("COMPLETE")
print(f"Outputs: {OUTPUT_DIR}/")
print(f"  step0_tool_data_{TIMESTAMP}.txt  — Raw API data (PubChem/PubMed/MP/DrugBank)")
print(f"  toa_plan_{TIMESTAMP}.txt        — TOA task plan")
print(f"  ea_materials_{TIMESTAMP}.txt    — EA extracted material list")
print(f"  epa_nadh_{TIMESTAMP}.txt        — EPA NADH classification")
print(f"  ca_summary_{TIMESTAMP}.txt      — CA summary report")
print(f"\nAll agent outputs are RAW and UNMODIFIED.")
