#!/usr/bin/env python3
# Specify python3 as the interpreter, ensuring the correct Python version is used when executed directly on Unix-like systems

"""
Assessment Tool Executor.
Provides unified tool invocation logic to ensure all assessment agents use the same tool invocation process.

This module provides unified tool invocation logic, ensuring that all assessment agents
follow the same tool invocation process. It prevents different agents from redundantly
invoking the same tools and wasting API quota, and writes results into the global
context for reuse.
"""

import logging
# Import Python's built-in logging module for recording errors and warnings during tool invocation
import json
# Import the json module for parsing JSON string results returned by BaseTool._run
from typing import Dict, Any
# Import type hints from the typing module for dictionary type annotations in function signatures
from src.utils.tool_call_spec import ToolCallSpec
# Import the tool call specification class to validate the format and content of each tool's results
from src.utils.context_store import ContextStore
# Import the context store class to write tool invocation results into the global context for reuse by subsequent Agents and Tasks

# Delayed import to avoid circular import
# The following functions use a delayed import strategy: the actual import of each tool
# is performed only when the function is first called. The purpose is to avoid circular
# imports at module load time (since tool modules may also reference this module).

def get_material_identifier_tool():
    """
    Get the material identifier tool instance (delayed import).
    To avoid circular imports, this module does not import it at the top; instead, it is imported dynamically inside the function body.
    """
    from src.tools.material_identifier_tool import get_material_identifier_tool as _get_material_identifier_tool
    return _get_material_identifier_tool()

def get_structure_validator_tool():
    """
    Get the structure validator tool instance (delayed import).
    Used to verify whether a material structure actually exists in known crystallographic databases.
    """
    from src.tools.structure_validator_tool import get_structure_validator_tool as _get_structure_validator_tool
    return _get_structure_validator_tool()

def get_materials_project_tool():
    """
    Get the Materials Project database query tool instance (delayed import).
    Used to query crystal structures, thermodynamic stability, and physical properties of metals and inorganic materials.
    """
    from src.tools.materials_project_tool import get_materials_project_tool as _get_materials_project_tool
    return _get_materials_project_tool()

def get_pubchem_tool():
    """
    Get the PubChem database query tool instance (delayed import).
    Used to query chemical information, toxicity, and environmental data of organic compounds and pollutants.
    """
    from src.tools.pubchem_tool import get_pubchem_tool as _get_pubchem_tool
    return _get_pubchem_tool()

def get_pnec_tool():
    """
    Get the PNEC (Predicted No-Effect Concentration) tool instance (delayed import).
    Used to query environmental risk assessment data and ecotoxicity thresholds of chemicals.
    """
    from src.tools.pnec_tool import get_pnec_tool as _get_pnec_tool
    return _get_pnec_tool()

def get_data_validator_tool():
    """
    Get the data validator tool instance (delayed import).
    Used to verify the completeness and consistency of chemical data, such as molecular formula format and the validity of chemical valences.
    """
    from src.tools.data_validator_tool import get_data_validator_tool as _get_data_validator_tool
    return _get_data_validator_tool()

def get_material_search_tool():
    """
    Get the material search tool instance (delayed import).
    Used to perform comprehensive searches across multiple material databases and aggregate candidate material information.
    """
    from src.tools.material_search_tool import get_material_search_tool as _get_material_search_tool
    return _get_material_search_tool()


# Configure logging
logging.basicConfig(level=logging.WARNING)
# Set the logging level to WARNING so that only warnings and above are emitted, avoiding INFO/DEBUG log noise
logger = logging.getLogger(__name__)
# Get a logger named after the current module

class AssessmentToolExecutor:
    """Assessment Tool Executor Class - Provides unified tool invocation logic.
    This class encapsulates the unified invocation logic for all assessment-related tools.
    Every assessment agent should use this executor instead of calling tools directly,
    to ensure invocation consistency and result reusability."""

    def __init__(self):
        """Initialize assessment tool executor.
        Initializes the executor by pre-fetching instances of all available tools in the
        constructor, so they can be used directly in subsequent methods without repeated imports."""
        # Material identifier tool: identifies the material type (metal/organic/unknown)
        self.material_identifier_tool = get_material_identifier_tool()
        # Structure validator tool: verifies whether the material structure exists in real databases
        self.structure_validator_tool = get_structure_validator_tool()
        # Materials Project tool: queries the inorganic materials database (including band structure and thermodynamic data)
        self.materials_project_tool = get_materials_project_tool()
        # PubChem tool: queries the chemical database of organic compounds and pollutants
        self.pubchem_tool = get_pubchem_tool()
        # PNEC tool: queries environmental risk assessment data
        self.pnec_tool = get_pnec_tool()
        # Data validator tool: verifies the completeness and correctness of chemical data
        self.data_validator_tool = get_data_validator_tool()
        # Material search tool: performs comprehensive searches across multiple material databases
        self.material_search_tool = get_material_search_tool()

    def execute_mandatory_tool_calls(self, material_formula: str) -> Dict[str, Any]:
        """
        Execute mandatory tool invocation sequence for assessment agents.
        Invokes 7 tools in a fixed order, collects the results into a unified dictionary,
        and writes key results into the global context for subsequent reuse.

        Args:
            material_formula (str): Material chemical formula
            material_formula (str): Chemical formula of the material to be assessed, e.g. "TiO2", "Fe2O3"

        Returns:
            Dict[str, Any]: Results of all tool invocations
            Dict[str, Any]: Dictionary of all tool invocation results, containing each tool's return value and an error list
        """
        # Initialize the result dictionary: the value for each tool key starts as None
        # The errors list collects exception information from all tool invocations
        results = {
            "material_identifier": None,   # Material identifier result
            "structure_validator": None,   # Structure validation result
            "materials_project": None,     # Materials Project query result
            "pubchem": None,               # PubChem query result
            "pnec": None,                  # PNEC environmental risk query result
            "data_validator": None,        # Data validation result
            "material_search": None,       # Comprehensive material search result
            "errors": []                   # Error information collection list
        }

        try:
            # 1. Material identifier tool invocation
            # Step 1: Invoke the material identifier tool to identify the substance type (metal/organic/unknown) and validation information
            results["material_identifier"] = self.material_identifier_tool.identify_material(material_formula)

            # 2. Structure validator tool invocation
            # Step 2: Invoke the structure validator tool to verify whether the material structure corresponding to this formula exists in real databases
            results["structure_validator"] = self.structure_validator_tool.validate_structure_exists(material_formula)

            # 3. Invoke appropriate database tool based on material type (only when validation passes)
            # Step 3: Selectively invoke database tools based on the material type — query only when material identification passes validation
            # The material identifier result contains material_type (material type) and is_verified (whether validation passed)
            material_type = results["material_identifier"].get("material_type", "unknown")
            if results["material_identifier"].get("is_verified"):
                # If the material is verified as a metal type, invoke the Materials Project search
                if material_type == "metal":
                    results["materials_project"] = self.materials_project_tool.search_materials(
                        formula=material_formula,
                        limit=5,  # Limit to 5 results to avoid excessive API quota consumption
                        fields=["material_id", "formula_pretty"]  # Request only necessary fields to reduce data transfer
                    )
                # If the material is verified as an organic type, invoke the PubChem search
                elif material_type == "organic":
                    results["pubchem"] = self.pubchem_tool.search_compound(material_formula)

            # 4. Invoke PNEC tool (environmental risk assessment): only attempt when validated or valid name parsed
            # Step 4: Invoke the PNEC tool to obtain environmental risk assessment data (Predicted No-Effect Concentration)
            # Query only when the material has been validated; otherwise return a warning message
            try:
                if results["material_identifier"].get("is_verified"):
                    results["pnec"] = self.pnec_tool.get_pnec_by_name(material_formula)
                else:
                    # Material not validated; skip the PNEC query and record the reason
                    results["pnec"] = {"warning": "Material not validated, skipping PNEC query"}
            except Exception:
                # A PNEC query failure does not affect the overall flow; log the error and continue
                results["pnec"] = {"error": "PNEC query failed"}

            # 5. Invoke data validator tool
            # Step 5: Invoke the data validator tool to verify the completeness and consistency of chemical data
            # Build a data dictionary containing the molecular formula and material name as validation input
            material_data = {
                "molecular_formula": material_formula,  # Molecular formula
                "material_name": material_formula       # Material name (same as the molecular formula here)
            }
            results["data_validator"] = self.data_validator_tool.validate_chemical_data(material_data)

            # 6. Invoke material search tool: this tool is BaseTool, use its _run interface
            # Step 6: Invoke the comprehensive search interface of the material search tool
            # Note: this tool inherits from BaseTool, so use its _run method instead of a custom interface
            # _run returns a JSON string, which must be parsed into a dict to keep the result type consistent with other tools
            try:
                raw_search_result = self.material_search_tool._run(material_formula, limit=10)
                if isinstance(raw_search_result, str):
                    try:
                        results["material_search"] = json.loads(raw_search_result)
                    except (json.JSONDecodeError, ValueError):
                        # The returned content is not valid JSON; wrap it in an error dictionary to avoid polluting downstream processing
                        results["material_search"] = {"error": "Material search tool returned a non-JSON result"}
                else:
                    # If a dict is already returned, use it directly
                    results["material_search"] = raw_search_result
            except Exception:
                # A material search failure does not block the flow; record the error and continue
                results["material_search"] = {"error": "Material search tool invocation failed"}

            # Write to global context for reuse to avoid duplicate queries
            # Step 7: Write key tool results into the global context store for reuse by subsequent Agents and Tasks
            # This prevents different Agents from repeatedly issuing the same database queries, effectively saving API quota
            # The cache key carries the material chemical formula (material_formula), ensuring that:
            # - The A/B/C experts for the same material can reuse results (same key)
            # - Different materials do not contaminate each other's data (different keys)
            # Only successful results are cached: results containing "error" are not written, to avoid permanently caching error results
            try:
                # Write the material identifier result into the context for subsequent Agents to determine the material type
                material_identifier_result = results.get("material_identifier")
                if isinstance(material_identifier_result, dict) and "error" not in material_identifier_result:
                    ContextStore.set(f"material_identifier:{material_formula}", material_identifier_result)
                # Write the Materials Project search result into the context (if available)
                materials_project_result = results.get("materials_project")
                if isinstance(materials_project_result, dict) and "error" not in materials_project_result:
                    ContextStore.set(f"materials_project_search:{material_formula}", materials_project_result)
                # Write the structure validation result into the context to avoid repeated validation
                structure_validator_result = results.get("structure_validator")
                if isinstance(structure_validator_result, dict) and "error" not in structure_validator_result:
                    ContextStore.set(f"structure_validator:{material_formula}", structure_validator_result)
                # Write the comprehensive material search result into the context
                material_search_result = results.get("material_search")
                if isinstance(material_search_result, dict) and "error" not in material_search_result:
                    ContextStore.set(f"material_search:{material_formula}", material_search_result)
            except Exception:
                # A context write failure does not affect the main flow; silently skip it
                pass

        except Exception as e:
            # Catch all exceptions and collect error information instead of crashing
            results["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            # Log detailed error information for debugging
            logger.error(f"Assessment tool invocation failed: {e}")

        # Return the complete dictionary containing all tool invocation results (or error information)
        return results

    def validate_tool_results(self, tool_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate all tool invocation results.
        Verifies the completeness and validity of all tool invocation results.
        Checks the data format returned by each tool one by one against the validation standards defined in ToolCallSpec.

        Args:
            tool_results (Dict[str, Any]): Tool invocation results
            tool_results (Dict[str, Any]): Dictionary of tool invocation results (returned by execute_mandatory_tool_calls)

        Returns:
            Dict[str, Any]: Validation results
            Dict[str, Any]: Validation result dictionary, containing the overall pass flag and per-item validation details
        """
        # Initialize the validation result dictionary: all_valid defaults to True and is set to False when any item fails
        validation_result = {
            "all_valid": True,                # Overall validation flag: True means all tool results passed validation
            "validation_details": {},         # Per-tool validation details
            "errors": []                      # List of error messages for failed validations
        }

        # Validate material identifier results
        # Validate the material identifier result: check whether the returned dictionary contains the required fields and valid data
        if tool_results.get("material_identifier"):
            is_valid = ToolCallSpec.validate_material_identifier_result(tool_results["material_identifier"])
            validation_result["validation_details"]["material_identifier"] = is_valid
            if not is_valid:
                # Material identifier validation failed; mark overall validation as failed and record it
                validation_result["all_valid"] = False
                validation_result["errors"].append("Material identifier validation failed")

        # Validate structure validator results
        # Validate the structure validator result: check whether the structure information is complete and the database source is reliable
        if tool_results.get("structure_validator"):
            is_valid = ToolCallSpec.validate_structure_validator_result(tool_results["structure_validator"])
            validation_result["validation_details"]["structure_validator"] = is_valid
            if not is_valid:
                validation_result["all_valid"] = False
                validation_result["errors"].append("Structure validation failed")

        # Validate Materials Project results
        # Validate the Materials Project query result: ensure the returned data conforms to the API specification
        if tool_results.get("materials_project"):
            is_valid = ToolCallSpec.validate_materials_project_result(tool_results["materials_project"])
            validation_result["validation_details"]["materials_project"] = is_valid
            if not is_valid:
                validation_result["all_valid"] = False
                validation_result["errors"].append("Materials Project data validation failed")

        # Validate PubChem results
        # Validate the PubChem query result: ensure the compound data format is correct and fields are complete
        if tool_results.get("pubchem"):
            is_valid = ToolCallSpec.validate_pubchem_result(tool_results["pubchem"])
            validation_result["validation_details"]["pubchem"] = is_valid
            if not is_valid:
                validation_result["all_valid"] = False
                validation_result["errors"].append("PubChem data validation failed")

        # Return the validation result dictionary; the caller can use all_valid to decide whether score adjustment is needed
        return validation_result
