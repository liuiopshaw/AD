#!/usr/bin/env python3
"""
Tool Factory.
Create and manage various database query tools.
Provides the corresponding set of tools for each Agent
according to different business scenarios (e.g., operation guidance,
literature extraction, material design, material assessment, etc.).
"""

# ---- CrewAI tool wrapper layer imports ----
# Wrap low-level APIs such as Materials Project and PubChem as CrewAI
# tool objects, so that Agents in the CrewAI framework can call them directly.

# CrewAI wrapper tool for the Materials Project database
from src.tools.crewai_materials_project_tool import materials_project_tool
# CrewAI wrapper tool for the PubChem database
from src.tools.crewai_pubchem_tool import pubchem_tool
# CrewAI tool for PNEC (Predicted No-Effect Concentration) environmental risk assessment
from src.tools.crewai_pnec_tool import CrewAIPNECTool
# CrewAI tool for data format validation (purely local validation, no external API calls)
from src.tools.crewai_data_validator_tool import CrewAIDataValidatorTool
# Three CrewAI tools for the MolPort chemical supplier database
from src.tools.crewai_molport_tool import (
    molport_availability_tool,   # chemical commercial availability query
    molport_search_tool,         # chemical search
    molport_molecule_info_tool   # molecule information query
)


class ToolFactory:
    """
    Tool factory class — provides preset tool collections according to
    different workflow stages (Agent task requirements). Each static method
    returns a set of tool instances, embodying the "Less is More" design
    strategy: keep only core data sources and independent functional tools,
    and remove redundant tools that internally call MP/PubChem indirectly.
    """

    @staticmethod
    def create_operation_guidance_tools():
        """
        Create the operation guidance tool set — for use by Operation_Suggesting_agent.

        Matched to task requirements:
        - pubchem: chemical safety data
        - materials_project: material cost data
        - PNEC: environmental impact data

        Returns:
            list: list of operation guidance tool instances
        """
        tools = [
            pubchem_tool,                  # chemical safety data (meets task requirements)
            materials_project_tool,        # material cost data (meets task requirements)
            CrewAIPNECTool(),              # environmental impact assessment (meets task requirements)
        ]
        return tools

    @staticmethod
    def create_literature_extraction_tools():
        """
        Create the literature extraction tool set — for Extracting_agent to
        extract chemical information from the literature.

        Strategy (Less is More):
        - Remove Name2Properties/MaterialSearch (internally call MP, redundant)
        - Keep core query tools + local validation tool

        Returns:
            list: list of literature extraction tool instances
        """
        tools = [
            materials_project_tool,         # material structure query (core search for inorganic materials)
            pubchem_tool,                   # compound information query (core search for organic compounds)
            CrewAIDataValidatorTool()       # local data format validation (no external API calls, fast)
        ]
        return tools

    @staticmethod
    def create_material_design_tools():
        """
        Create the material design tool set.

        Strategy (Less is More):
        - Keep only the two core query tools, MP and PubChem
        - Remove MaterialIdentifier/StructureValidator/MaterialSearch
          (all internally call MP+PubChem, highly redundant)

        Returns:
            list: list of material design tool instances
        """
        tools = [
            materials_project_tool,   # material structure and property query (basis for inorganic material design)
            pubchem_tool,             # organic compound information (basis for organic component design)
        ]
        return tools

    @staticmethod
    def create_material_search_tools():
        """
        Create the material search tool set — for use by SynthesisGuidingAgent,
        the synthesis guidance Agent.

        Strategy (Less is More):
        - Remove MaterialSearch/StructureValidator (internally call MP, redundant)
        - Use the core tools directly

        Returns:
            list: list of material search tool instances
        """
        tools = [
            materials_project_tool,             # material structure and synthesis information
            pubchem_tool,                       # reagent safety data (reference for synthesis safety)
        ]
        return tools

    @staticmethod
    def create_mechanism_analysis_tools():
        """
        Create the mechanism analysis tool set — for use by MechanismMiningAgent,
        the mechanism mining Agent.

        Note: Prefer reusing analysis results from upstream Agents to reduce
        duplicate queries.

        Returns:
            list: list of mechanism analysis tool instances
        """
        tools = [
            materials_project_tool,          # material structure and electronic structure (for mechanism explanation)
            pubchem_tool,                    # chemical reactivity data (for reactions)
        ]
        return tools

    @staticmethod
    def create_unified_assessment_tools():
        """
        Create the unified ASA assessment tool set — shared by the three
        expert Agents Expert A/B/C.

        Strategy (Less is More):
        - Remove MaterialIdentifier/StructureValidator (call MP+PubChem, highly redundant)
        - Keep core data sources + independent functional tools

        Mapping between assessment dimensions and tools:
        - Catalytic performance (50%)      -> materials_project (material structure, electronic structure, stability)
        - Economic feasibility (10%)       -> molport (commercial availability)
        - Environmental friendliness (10%) -> PNEC (environmental risk assessment)
        - Technical feasibility (10%)      -> materials_project (material structure and synthesis feasibility)
        - Structural rationality (20%)     -> pubchem (chemical properties, toxicity, structure validation)

        Returns:
            list: list of unified assessment tool instances
        """
        tools = [
            materials_project_tool,          # material structure, electronic structure, stability (catalytic performance + technical feasibility)
            pubchem_tool,                    # chemical properties, toxicity, structure validation (structural rationality)
            CrewAIPNECTool(),                # environmental risk assessment (independent API, environmental friendliness)
            molport_availability_tool,       # commercial availability (independent API, economic feasibility)
        ]
        return tools
