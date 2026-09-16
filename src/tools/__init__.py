"""
Tools module initialization file.
Centrally imports and exposes all tool classes, factory functions, and
instances as the public interface of the tools package.

Note: this module no longer imports src.utils.assessment_tool_executor /
assessment_scoring_logic in reverse (import assessment-related classes
directly from src.utils instead), in order to avoid circular dependencies
between tools <-> utils.
"""

# ===== Import functional tools (getter functions) =====
# These are low-level tool classes; instances are obtained via get_xxx factory functions
from .materials_project_tool import get_materials_project_tool    # Materials Project inorganic materials database query
from .pubchem_tool import get_pubchem_tool                        # PubChem organic compound database query
# EvaluationTool removed - not used in ECOMATS, only in BioCrew
from .name2cas_tool import get_name2cas_tool                      # Compound name to CAS number
from .name2properties_tool import get_name2properties_tool        # Query compound properties by name
from .cid2properties_tool import get_cid2properties_tool          # Query compound properties by CID
from .formula2properties_tool import get_formula2properties_tool  # Query compound properties by formula
from .material_search_tool import get_material_search_tool        # Comprehensive material search
from .pnec_tool import get_pnec_tool                              # PNEC (Predicted No-Effect Concentration) query
from .material_identifier_tool import get_material_identifier_tool # Material type identification
from .data_validator_tool import get_data_validator_tool          # Data validation
from .structure_validator_tool import get_structure_validator_tool # Material structure existence validation
from .molport_tool import get_molport_tool                        # MolPort chemical marketplace data query

# ===== Import CrewAI tool wrappers =====
# These are adapter classes/instances wrapping the low-level tools as CrewAI BaseTool
from .crewai_materials_project_tool import materials_project_tool      # CrewAI Materials Project tool instance
from .crewai_pubchem_tool import pubchem_tool                          # CrewAI PubChem tool instance
from .crewai_pnec_tool import CrewAIPNECTool                           # CrewAI PNEC query tool class
from .crewai_data_validator_tool import CrewAIDataValidatorTool        # CrewAI data validation tool class
from .crewai_molport_tool import (                                     # CrewAI MolPort tools (multiple entry points)
    molport_availability_tool,                                         # Chemical reagent availability query
    molport_search_tool,                                               # MolPort compound search
    molport_molecule_info_tool,                                        # MolPort molecule info query
    CrewAIMolPortAvailabilityTool,
    CrewAIMolPortSearchTool,
    CrewAIMolPortMoleculeInfoTool
)

# ===== Import tool factory =====
# ToolFactory is used to uniformly create and manage all tool instances
from .factory import ToolFactory

# ===== Nano-Bio Evaluator: Domain Tools =====
from .drugbank_tool import DrugBankTool
from .enzyme_classifier import EnzymeClassifier
from .material_compare import MaterialCompare

# ===== Define the public interface of this module =====
# The __all__ list controls what is exported by "from package import *"
# Only export classes and functions that are genuinely meant for external use
__all__ = [
    # Functional tool getters
    'get_materials_project_tool',
    'get_pubchem_tool',
    'get_name2cas_tool',
    'get_name2properties_tool',
    'get_cid2properties_tool',
    'get_formula2properties_tool',
    'get_material_search_tool',
    'get_pnec_tool',
    'get_material_identifier_tool',
    'get_data_validator_tool',
    'get_structure_validator_tool',
    'get_molport_tool',

    # CrewAI tool wrappers (instances)
    'materials_project_tool',
    'pubchem_tool',

    # CrewAI tool wrappers (classes)
    'CrewAIPNECTool',
    'CrewAIDataValidatorTool',
    'ToolFactory',

    # MolPort tools
    'molport_availability_tool',
    'molport_search_tool',
    'molport_molecule_info_tool',
    'CrewAIMolPortAvailabilityTool',
    'CrewAIMolPortSearchTool',
    'CrewAIMolPortMoleculeInfoTool',

    # Nano-Bio Evaluator: Domain Tools
    'DrugBankTool',
    'EnzymeClassifier',
    'MaterialCompare',
]
