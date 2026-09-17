#!/usr/bin/env python3
"""
Schema v2 — single source of truth for the CDA output contract.

Phase 0 note: task_100_materials.py still EMITS the legacy 11-field v1 format
(FIELDS_V1); the 13-field v2 format (FIELDS_V2) is the target contract for the
small-molecule / biologic domain extension (Phase 4 switch). This module lets
consumers (rank_cda_outputs.py, rank_to_excel.py) parse both transparently.

Iron rule (CLAUDE.md): agent output is never rewritten. normalize_record only
relocates fields mechanically — legacy Material_Category moves into Modality
VERBATIM, and fields that do not exist in the old record are filled with "NA".
"""

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------

# v2 contract (13 columns). Material_Category is merged into Modality; fields
# that do not apply to a record's modality are filled with NA.
FIELDS_V2 = [
    "Material_Name",
    "Modality",
    "Chemical_Formula",
    "SMILES",
    "Target_UniProt",
    "Ligand",
    "Size_nm",
    "Core_Elements",
    "ASA_Score(1-10)",
    "Disease_Intervention",
    "Mechanism",
    "NADH_Activity(YES/NO)",
    "Key_Features",
]

# Legacy v1 contract (11 columns) — what task_100_materials.py emits today.
FIELDS_V1 = [
    "Material_Name",
    "Chemical_Formula",
    "Ligand",
    "Size_nm",
    "Core_Elements",
    "Material_Category",
    "ASA_Score(1-10)",
    "Disease_Intervention",
    "Mechanism",
    "NADH_Activity(YES/NO)",
    "Key_Features",
]

# Legacy runs before Ligand (10 cols) / before Chemical_Formula+Ligand (9 cols).
LEGACY_LENGTHS = (9, 10)

MODALITIES = (
    "nanocluster",
    "nanoparticle",
    "single_atom",
    "dual_atom",
    "small_molecule",
    "biologic",
)

DISEASE_INTERVENTIONS = (
    "direct_antibacterial",
    "probiotic_delivery",
    "ROS_inflammation_clearance",
    "immune_modulation",
    "other",
)

MECHANISMS = (
    "microbiome_remodeling",
    "gut_barrier_restoration",
    "metabolite_modulation",
    "gut_immune_regulation",
    "amyloid_tau_direct",
    "neuroinflammation",
    "other",
)

# Per-modality guidance: which fields are meaningful, which are NA.
_NANO_MODALITIES = ("nanocluster", "nanoparticle", "single_atom", "dual_atom")
MODALITY_FIELD_GUIDE = {
    "nanocluster":    "fill Chemical_Formula/Ligand/Size_nm/Core_Elements; SMILES and Target_UniProt = NA",
    "nanoparticle":   "fill Chemical_Formula/Ligand/Size_nm/Core_Elements; SMILES and Target_UniProt = NA",
    "single_atom":    "fill Chemical_Formula/Ligand/Size_nm/Core_Elements; SMILES and Target_UniProt = NA",
    "dual_atom":      "fill Chemical_Formula/Ligand/Size_nm/Core_Elements; SMILES and Target_UniProt = NA",
    "small_molecule": "fill Target_UniProt; SMILES only if completely certain (else NA — NEVER invent SMILES, a database lookup resolves them from the name later); Chemical_Formula optional; Ligand/Size_nm/Core_Elements = NA",
    "biologic":       "fill Target_UniProt; Chemical_Formula/SMILES/Ligand/Size_nm/Core_Elements = NA",
}


# ---------------------------------------------------------------------------
# Prompt generation
# ---------------------------------------------------------------------------

def cda_format_block(modality_focus: "str | None" = None) -> str:
    """Field-spec text block for CDA prompts (v2 contract).

    modality_focus: one of MODALITIES, or None for a mixed-modality batch.
    """
    if modality_focus is not None and modality_focus not in MODALITIES:
        raise ValueError(f"Unknown modality: {modality_focus!r}. Choices: {MODALITIES}")

    lines = [
        "For EACH candidate, output ONE line with ALL these fields, pipe-separated:",
        "",
        " | ".join(FIELDS_V2),
        "",
        f"Modality MUST be one of: {', '.join(MODALITIES)}",
        f"Disease_Intervention MUST be one of: {', '.join(DISEASE_INTERVENTIONS)}",
        f"Mechanism MUST be one of: {', '.join(MECHANISMS)}",
        "NADH_Activity: YES or NO",
        "",
        "Fields that do not apply to a candidate's modality MUST be filled with NA:",
    ]
    for m in MODALITIES:
        lines.append(f"- {m}: {MODALITY_FIELD_GUIDE[m]}")
    lines.append("")

    if modality_focus is None:
        lines.append(
            "This is a MIXED-modality batch: vary modalities across candidates."
        )
    else:
        lines.append(
            f"This batch focuses on modality: {modality_focus} — {MODALITY_FIELD_GUIDE[modality_focus]}."
        )

    lines += [
        "",
        "Chemical_Formula: formula of the INORGANIC active phase (e.g., Cu, CuO, Cu2O, CuFe2O4, Cu-N4, ZnMoO4)",
        "Ligand: the stabilizing ligand/coating as reported in literature. For nanoclusters and NPs <10nm an organic capping agent is REQUIRED (e.g., cyclodextrin, glutathione, BSA, PVP, PEG, citrate, tannic acid, chitosan). For SAC/DAC write the anchoring support (e.g., N-doped carbon, CeO2, ZIF-8, g-C3N4).",
        "SMILES: canonical SMILES of the small molecule (small_molecule modality only). Provide it ONLY if completely certain; otherwise write NA — NEVER invent, guess, or repeat SMILES strings (a database lookup resolves SMILES from the compound name later)",
        "Target_UniProt: UniProt accession of the primary protein target (small_molecule/biologic modalities)",
        "",
        "Vary sizes within the batch's structural family. Vary supports and ligands — avoid near-duplicate candidates. Output ONLY candidate lines, NO intro, NO summary.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Record normalization (v1 9/10/11-col and v2 13-col -> v2 dict)
# ---------------------------------------------------------------------------

def normalize_record(cells: "list[str]") -> "dict | None":
    """Normalize a pipe-split record (9/10/11/13 cells) into a FIELDS_V2 dict.

    Returns None for unrecognized column counts. Mechanical relocation only:
    legacy Material_Category moves into Modality verbatim; SMILES/Target_UniProt
    are filled with "NA" for legacy records.
    """
    cells = list(cells)
    n = len(cells)
    if n == 10:  # v1 without Ligand
        cells = cells[:2] + [""] + cells[2:]
    elif n == 9:  # v1 without Chemical_Formula/Ligand
        cells = [cells[0], "", ""] + cells[1:]
    elif n == 12 and cells[1] in MODALITIES:
        # v2 record with Ligand dropped (observed: models fold the ligand
        # into Material_Name, e.g. "Fe3O4@PVP", and skip the field).
        # cells[1] is Modality in v2 but Chemical_Formula in v1, so the
        # MODALITIES check discriminates safely. Empty Ligand, never invented.
        cells = cells[:5] + [""] + cells[5:]

    n = len(cells)
    if n == len(FIELDS_V2):  # 13 — already v2
        return dict(zip(FIELDS_V2, cells))

    if n == len(FIELDS_V1):  # 11 — legacy v1
        rec = dict(zip(FIELDS_V1, cells))
        return {
            "Material_Name": rec["Material_Name"],
            "Modality": rec["Material_Category"],  # verbatim relocation
            "Chemical_Formula": rec["Chemical_Formula"],
            "SMILES": "NA",
            "Target_UniProt": "NA",
            "Ligand": rec["Ligand"],
            "Size_nm": rec["Size_nm"],
            "Core_Elements": rec["Core_Elements"],
            "ASA_Score(1-10)": rec["ASA_Score(1-10)"],
            "Disease_Intervention": rec["Disease_Intervention"],
            "Mechanism": rec["Mechanism"],
            "NADH_Activity(YES/NO)": rec["NADH_Activity(YES/NO)"],
            "Key_Features": rec["Key_Features"],
        }

    return None


# ---------------------------------------------------------------------------
# Schema v3 — AD100 run contract (, user-specified 4-dimension
# classification; single-choice per dimension; English enums; NO Cu quota)
# ---------------------------------------------------------------------------

FIELDS_V3 = [
    "Material_Name",
    "Drug_Type",          # dim 1: drug type
    "Target_Category",    # dim 2: drug target category
    "Action_Mode",        # dim 3: drug action mode
    "AD_Mechanism",       # dim 4: AD therapeutic mechanism
    "Chemical_Formula",
    "SMILES",
    "Target_UniProt",
    "Ligand",
    "Size_nm",
    "Core_Elements",
    "ASA_Score(1-10)",
    "Key_Features",
]

DRUG_TYPES = (
    "nano_formulation",
    "biologic",
    "small_molecule",
    "other",
)

TARGET_CATEGORIES = (
    "gut_targeted_regulation",          # gut-targeted regulation
    "CNS_intervention_neurorepair",     # CNS intervention and neurorepair
    "signaling_pathway_modulation",     # signaling pathway modulation
    "peripheral_nerve_regulation",      # peripheral nerve regulation
    "epigenetic_regulation",            # epigenetic regulation
)

ACTION_MODES = (
    "microbiota_ratio_modulation",      # gut microbiota ratio modulation
    "immune_inflammation_modulation",   # immune/inflammation modulation
    "probiotic_prebiotic_supplementation",  # probiotic/prebiotic supplementation
    "metabolite_modulation",            # metabolite modulation
    "active_substance_delivery",        # active substance delivery
)

AD_MECHANISMS = (
    "gut_microbiome_axis",              # gut microbiome regulation (gut-brain axis)
    "amyloid_tau_targeting",            # targeting Aβ/Tau pathological proteins
    "neuroprotection",                  # neuroprotection
    "neuroinflammation_modulation",     # neuroinflammation modulation
    "synaptic_function_modulation",     # synaptic function modulation
)

DRUG_TYPE_FIELD_GUIDE = {
    "nano_formulation": "fill Chemical_Formula/Ligand/Size_nm/Core_Elements; it MAY carry ONE payload agent (small molecule or biologic) and remains nano_formulation — then fill the payload's SMILES/Target_UniProt if completely certain, else NA",
    "small_molecule":   "fill Target_UniProt; SMILES only if completely certain (else NA — NEVER invent SMILES, a database lookup resolves them from the name later); Chemical_Formula optional; Ligand/Size_nm/Core_Elements = NA",
    "biologic":         "fill Target_UniProt; Chemical_Formula/SMILES/Ligand/Size_nm/Core_Elements = NA",
    "other":            "fill whatever identifies the candidate (Chemical_Formula/Target_UniProt if applicable); the rest = NA",
}


def cda_format_block_v3() -> str:
    """Field-spec text block for CDA prompts (v3 / AD100 contract)."""
    lines = [
        "For EACH candidate, output ONE line with ALL these fields, pipe-separated:",
        "",
        " | ".join(FIELDS_V3),
        "",
        "Classification rules — EXACTLY ONE value per dimension, copied verbatim:",
        f"Drug_Type MUST be one of: {', '.join(DRUG_TYPES)}",
        f"Target_Category MUST be one of: {', '.join(TARGET_CATEGORIES)}",
        f"Action_Mode MUST be one of: {', '.join(ACTION_MODES)}",
        f"AD_Mechanism MUST be one of: {', '.join(AD_MECHANISMS)}",
        "",
        "Fields that do not apply to a candidate's Drug_Type MUST be filled with NA:",
    ]
    for t in DRUG_TYPES:
        lines.append(f"- {t}: {DRUG_TYPE_FIELD_GUIDE[t]}")
    lines += [
        "",
        "Chemical_Formula: formula of the INORGANIC active phase (nano_formulation only, e.g., Cu, CuO, Fe3O4, ZnMoO4). Only real, chemically valid formulas — if unsure, write NA",
        "Ligand: stabilizing ligand/coating for nano candidates (e.g., cyclodextrin, glutathione, BSA, PVP, PEG, citrate, chitosan); for SAC/DAC the anchoring support",
        "Target_UniProt: UniProt accession of the primary protein target (small_molecule/biologic; NA otherwise). Provide it ONLY if completely certain; otherwise write NA — NEVER invent or guess accessions (a database lookup verifies them later)",
        "",
        "CATEGORY RULES: (a) A nano formulation that carries a payload agent (small molecule or biologic) is STILL nano_formulation — there is no separate composite category (e.g., a Cu nanocluster carrying quercetin = nano_formulation). (b) TWO-AGENT LIMIT: never combine MORE THAN TWO therapeutic agents in one candidate — one carrier plus one payload at most (coatings/ligands like cyclodextrin, PEG, chitosan are NOT agents). NO triple combinations like 'nanocluster + EGCG + quercetin'.",
        "",
        "Material_Name is REQUIRED for EVERY candidate — a real, verifiable name, NEVER 'NA' or a placeholder. SMILES/Target_UniProt may be NA when uncertain, but the name may NOT.",
        "",
        "BASE THERAPEUTICS ONLY: every candidate must be a DISTINCT base therapeutic. Do NOT emit variants of the same parent — no size/dosage variants (e.g., 'X_2nm' vs 'X_5nm'), no core-composition variants of one formulation (e.g., 'X_Cu' vs 'X_CuO'), no salt/ester/form variants of one API. One parent = one entry.",
        "",
        "Avoid near-duplicate candidates. Output ONLY candidate lines, NO intro, NO summary.",
    ]
    return "\n".join(lines)


def parse_record_v3(cells: "list[str]") -> "dict | None":
    """Normalize a pipe-split v3 record into a FIELDS_V3 dict.

    Accepted shapes (discriminated from other schemas by cells[1] being a
    DRUG_TYPES value — v2 has Modality there, a disjoint enum):
      13 cells = current v3 (no NADH; user requirement)
      14 cells = legacy v3 run with NADH_Activity — NADH cell dropped
      12 cells = ligand folded into Material_Name, Ligand field dropped
    Empty fields are never invented.
    """
    cells = list(cells)
    n = len(cells)
    if len(cells) < 2:
        return None
    if cells[0].strip().upper() in ("NA", "N/A", ""):
        return None  # nameless record — rejected mechanically, never backfilled
    if cells and cells[1] not in DRUG_TYPES:
        # Fallback: off-enum Drug_Type (observed: model fills Action_Mode
        # vocabulary into the Drug_Type slot for probiotic/FMT candidates).
        # Accept when the NEIGHBORING enum fields are valid — the verbatim
        # off-enum value stays visible in ranking stats' off-enum row.
        if not (len(cells) >= 5
                and cells[2] in TARGET_CATEGORIES
                and cells[4] in AD_MECHANISMS):
            return None
    if n == len(FIELDS_V3) + 1:  # legacy with NADH at index 12
        cells = cells[:12] + cells[13:]
    elif n == len(FIELDS_V3) - 1:  # ligand dropped
        cells = cells[:8] + [""] + cells[8:]
    if len(cells) == len(FIELDS_V3):
        return dict(zip(FIELDS_V3, cells))
    return None
