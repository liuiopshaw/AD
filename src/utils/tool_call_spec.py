#!/usr/bin/env python3
"""
Tool Call Specification Module
Defines the tool inventory and tool call validation logic required by each Agent.

Design goals:
- Centrally manage which tools each Agent needs to call
- Provide a unified result validation interface to ensure tool-returned data matches the expected format
- Support context cache reuse to avoid repeated external API calls
"""

# Logging module, used to output warning messages when validation fails
import logging
# The typing module is used for type annotations, improving code readability and IDE support
from typing import Dict, Any, List


# =============================================================================
# Lazily imported tool getter functions
# Uses the lazy import pattern to avoid circular import issues.
# Dependencies between modules are complex; importing inside functions breaks circular dependency chains.
# =============================================================================

def get_material_identifier_tool():
    """
    Get the material identifier tool instance (lazy import).

    Import inside the function to avoid module-level circular dependencies:
    tool_call_spec -> material_identifier_tool -> other modules -> tool_call_spec
    """
    from src.tools.material_identifier_tool import get_material_identifier_tool as _get_material_identifier_tool
    return _get_material_identifier_tool()

def get_structure_validator_tool():
    """
    Get the structure validator tool instance (lazy import).
    Lazy import avoids circular dependencies with the structure_validator_tool module.
    """
    from src.tools.structure_validator_tool import get_structure_validator_tool as _get_structure_validator_tool
    return _get_structure_validator_tool()

def get_materials_project_tool():
    """
    Get the Materials Project database query tool instance (lazy import).
    Materials Project is a materials science database for querying inorganic crystal structure data.
    """
    from src.tools.materials_project_tool import get_materials_project_tool as _get_materials_project_tool
    return _get_materials_project_tool()

def get_pubchem_tool():
    """
    Get the PubChem database query tool instance (lazy import).
    PubChem is the chemical molecule database of the US National Institutes of Health (NIH), used to query organic compound information.
    """
    from src.tools.pubchem_tool import get_pubchem_tool as _get_pubchem_tool
    return _get_pubchem_tool()

# Configure the logger for this module
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class ToolCallSpec:
    """
    Base class for tool call specifications.

    Provides tool result validation methods shared by all Agents.
    Each validation method checks whether the tool-returned result meets the expected format and content requirements.
    Subclasses can inherit these validation methods and add Agent-specific validation logic.
    """

    @staticmethod
    def validate_material_identifier_result(result: Dict[str, Any]) -> bool:
        """
        Validate the completeness and validity of the material identifier tool result.

        Validation steps:
        1. Confirm the result is a dict
        2. Check that all required fields exist
        3. Confirm the validation status passed (is_verified is True)

        Args:
            result: The result dictionary returned by the material identifier tool

        Returns:
            bool: Whether validation passed. True means the result format is correct and the content is valid
        """
        # Step 1: basic type check - the result must be a dict
        if not isinstance(result, dict):
            return False

        # Step 2: check that all required fields exist
        # query: original query string, material_type: material type (metal/organic)
        # identifier: material identifier (e.g. chemical formula), identifier_type: identifier type
        # validation_status: validation status, is_verified: whether verification passed
        required_fields = ["query", "material_type", "identifier", "identifier_type", "validation_status", "is_verified"]
        for field in required_fields:
            if field not in result:
                # Log a warning when a required field is missing, helping developers locate data issues
                logger.warning(f"Material identifier result missing required field: {field}")
                return False

        # Step 3: confirm the material identification passed validation
        # is_verified being True means the tool has confirmed the material identifier is valid
        # Use .get() to safely retrieve the value, defaulting to False to avoid KeyError
        if result.get("is_verified", False) is not True:
            logger.warning(f"Material identifier validation failed: {result.get('query', 'Unknown')}")
            return False

        return True

    @staticmethod
    def validate_structure_validator_result(result: Dict[str, Any]) -> bool:
        """
        Validate the completeness and validity of the structure validator tool result.

        Validation steps:
        1. Confirm the result is a dict
        2. Check that all required fields exist
        3. Confirm the structure is valid (valid is True)
        4. Confirm the validation confidence is "high" (high confidence)

        Args:
            result: The result dictionary returned by the structure validator tool

        Returns:
            bool: Whether validation passed
        """
        # Basic type check
        if not isinstance(result, dict):
            return False

        # Check required fields:
        # query: queried material chemical formula, valid: whether the structure is valid
        # type: material type, source: data source, reason: reason for the validation conclusion
        # validation_confidence: validation confidence (high/medium/low)
        required_fields = ["query", "valid", "type", "source", "reason", "validation_confidence"]
        for field in required_fields:
            if field not in result:
                logger.warning(f"Structure validation result missing required field: {field}")
                return False

        # Confirm the structure was judged valid
        if result.get("valid", False) is not True:
            logger.warning(f"Material structure validation failed: {result.get('query', 'Unknown')}")
            return False

        # Confirm the validation confidence is "high" (only high confidence is considered reliable)
        # If the confidence is "low" or "medium", the data source is not authoritative enough or uncertainty exists
        if result.get("validation_confidence", "low") != "high":
            logger.warning(f"Material structure validation confidence insufficient: {result.get('query', 'Unknown')}")
            return False

        return True

    @staticmethod
    def validate_materials_project_result(result: Dict[str, Any]) -> bool:
        """
        Validate the completeness and validity of the Materials Project tool result.

        Materials Project is dedicated to querying data such as electronic structure and
        thermodynamic properties of inorganic crystalline materials (e.g. metal alloys, ceramics).

        Validation steps:
        1. Confirm the result is a dict
        2. Check for an error field (i.e. the API returned an error)
        3. Confirm the data field exists and is non-empty

        Args:
            result: The result dictionary returned by the Materials Project tool

        Returns:
            bool: Whether validation passed
        """
        # Basic type check
        if not isinstance(result, dict):
            return False

        # Check whether the API returned an error
        # If result contains an "error" key, the external API call failed
        if "error" in result:
            logger.warning(f"Materials Project tool returned error: {result['error']}")
            return False

        # Confirm the returned result contains a data field
        # The data field is usually a list of dicts, each element representing a matched material entry
        if "data" not in result:
            logger.warning("Materials Project result missing data field")
            return False

        # Confirm the data field is non-empty (i.e. data was actually found)
        # Empty data means no matching material, which is also a validation failure
        if not result["data"]:
            logger.warning("Materials Project returned empty data")
            return False

        return True

    @staticmethod
    def validate_pubchem_result(result: Dict[str, Any]) -> bool:
        """
        Validate the completeness and validity of the PubChem tool result.

        PubChem is used to query organic compound information; the returned structure contains PropertyTable.Properties.

        Validation steps:
        1. Confirm the result is a dict
        2. Check for an error field
        3. Check the structural integrity of PropertyTable -> Properties level by level
        4. Confirm the Properties data is non-empty

        Args:
            result: The result dictionary returned by the PubChem tool

        Returns:
            bool: Whether validation passed
        """
        # Basic type check
        if not isinstance(result, dict):
            return False

        # Check whether the API returned an error
        if "error" in result:
            logger.warning(f"PubChem tool returned error: {result['error']}")
            return False

        # Check the top-level structure of the PubChem result: it must contain PropertyTable
        # PropertyTable is the standard response structure of the PubChem API
        if "PropertyTable" not in result:
            logger.warning("PubChem result missing PropertyTable field")
            return False

        # Check whether PropertyTable contains the Properties field
        # Properties is a list where each element is a dict of compound properties
        if "Properties" not in result["PropertyTable"]:
            logger.warning("PubChem result missing Properties field")
            return False

        # Confirm the Properties list is non-empty
        # Empty Properties means no compound data was found
        if not result["PropertyTable"]["Properties"]:
            logger.warning("PubChem returned empty Properties data")
            return False

        return True


class MaterialDesignerToolSpec(ToolCallSpec):
    """
    Tool call specification for the Material Designer Expert.

    This Agent is responsible for retrieving and validating material properties
    based on the material chemical formula, and for designing synthesis schemes.
    It needs to call the material identifier, structure validator, Materials Project, and PubChem tools.
    """

    @staticmethod
    def validate_tool_usage(material_formula: str) -> Dict[str, Any]:
        """
        Validate the tool call workflow of the Material Designer Expert.

        Executes the full workflow:
        1. Call the material identifier tool to identify the material type (metal/organic)
        2. Call the structure validator tool to confirm the material structure is valid
        3. Call the corresponding database tool based on the material type (metal -> Materials Project, organic -> PubChem)

        Optimization strategies:
        - Prefer reading existing results from the global context cache (ContextStore) to avoid repeated API calls
        - When the structure validator tool returns data via Materials Project, reuse its result directly

        Args:
            material_formula: Material chemical formula, e.g. "SiO2", "TiO2"

        Returns:
            A dictionary containing validation results, structured as:
            {
                "material_formula": str,      # Input material chemical formula
                "validation_passed": bool,    # Whether overall validation passed
                "errors": List[str],          # List of error messages
                "tool_calls": Dict            # Results returned by each tool
            }
        """
        # Initialize the result dictionary with the default status set to passed
        result = {
            "material_formula": material_formula,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- Load existing results from the global context cache ----
            # If a previous Agent already called the same tools and stored results, reuse them directly
            # This avoids repeated external API calls and improves efficiency
            try:
                from src.utils.context_store import ContextStore
                cached_identifier = ContextStore.get(f"material_identifier:{material_formula}")
                cached_validator = ContextStore.get(f"structure_validator:{material_formula}")
                cached_mp = ContextStore.get(f"materials_project_search:{material_formula}")
            except Exception:
                # When ContextStore is unavailable (e.g. in a test environment), set all caches to None
                cached_identifier = None
                cached_validator = None
                cached_mp = None

            # ---- Step 1: call the material identifier tool ----
            identifier_tool = get_material_identifier_tool()
            # Prefer the cache; call the tool's identify_material method when the cache is unavailable
            identifier_result = cached_identifier or identifier_tool.identify_material(material_formula)
            # Record the tool call result
            result["tool_calls"]["material_identifier"] = identifier_result

            # Validate the completeness and validity of the material identifier result
            if not ToolCallSpec.validate_material_identifier_result(identifier_result):
                result["validation_passed"] = False
                result["errors"].append("Material identifier validation failed")

            # ---- Step 2: call the structure validator tool ----
            validator_tool = get_structure_validator_tool()
            # Prefer the cached structure validation result
            validator_result = cached_validator or validator_tool.validate_structure_exists(material_formula)
            result["tool_calls"]["structure_validator"] = validator_result

            # Validate the structure validation result
            if not ToolCallSpec.validate_structure_validator_result(validator_result):
                result["validation_passed"] = False
                result["errors"].append("Structure validation failed")

            # ---- Step 3: call the corresponding database tool based on the material type ----
            # Get the material type from the material identifier result, defaulting to "unknown"
            material_type = identifier_result.get("material_type", "unknown")

            if material_type == "metal":
                # Metal material -> use the Materials Project database
                mp_tool = get_materials_project_tool()

                # Prefer the cached Materials Project query result
                if cached_mp and isinstance(cached_mp, dict) and cached_mp.get("data"):
                    mp_result = cached_mp
                else:
                    # Query strategy when the cache is unavailable (in decreasing priority):

                    # Strategy 1: reuse the Materials Project data returned by the structure validator tool
                    # If the structure validator tool already fetched data from Materials Project and passed validation,
                    # use it directly as the Materials Project query result to avoid calling the same API twice
                    validator_data = result["tool_calls"].get("structure_validator", {})
                    if isinstance(validator_data, dict) and validator_data.get("valid") and validator_data.get("source") == "Materials Project" and validator_data.get("data"):
                        mp_result = {
                            "data": [validator_data["data"]],
                            "meta": {"total_count": 1, "limit": 1}
                        }
                    else:
                        # Strategy 2: use the material_id from the material identifier for an exact query
                        # material_id is the unique identifier in Materials Project; use it to fetch detailed data
                        add_info = identifier_result.get("additional_info") or {}
                        material_id = add_info.get("material_id")
                        if material_id and mp_tool.validate_material_id(material_id):
                            # After the material_id is validated, call get_material_by_id to fetch the material details
                            detail = mp_tool.get_material_by_id(material_id)
                            mp_result = {"data": [detail] if "error" not in detail else [], "meta": {"total_count": 1, "limit": 1}}
                        else:
                            # Strategy 3: keyword search by chemical formula (fallback strategy)
                            # Set the query limit to 5 entries, requesting only the material_id and formula_pretty fields
                            mp_result = mp_tool.search_materials(formula=material_formula, limit=5, fields=["material_id", "formula_pretty"])

                # Record the tool call result and validate it
                result["tool_calls"]["materials_project"] = mp_result
                if not ToolCallSpec.validate_materials_project_result(mp_result):
                    result["validation_passed"] = False
                    result["errors"].append("Materials Project data validation failed")

            elif material_type == "organic":
                # Organic material -> use the PubChem database
                pubchem_tool = get_pubchem_tool()
                # Call PubChem's search_compound method to query compound information
                pubchem_result = pubchem_tool.search_compound(material_formula)
                result["tool_calls"]["pubchem"] = pubchem_result

                # Validate the PubChem query result
                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append("PubChem data validation failed")

        except Exception as e:
            # Catch all exceptions during tool invocation
            # Log the error and mark validation as failed without interrupting the program (graceful degradation)
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Material designer expert tool call validation failed: {e}")

        return result


class AssessmentExpertToolSpec(ToolCallSpec):
    """
    Tool call specification for the Assessment Expert.

    The Assessment Expert evaluates and screens the material design results. Compared
    with the Material Designer Expert, it has two additional tools: PNEC Tool and
    Data Validator Tool. Its workflow is similar to the Material Designer Expert's,
    but additionally requires safety assessment and data validation.
    """

    @staticmethod
    def validate_tool_usage(material_formula: str) -> Dict[str, Any]:
        """
        Validate the tool call workflow of the Assessment Expert.

        The workflow is basically the same as MaterialDesignerToolSpec:
        1. Material identification -> 2. Structure validation -> 3. Database query

        The validation logic for the additional tools (PNEC, Data Validator) can be
        supplemented by subclasses or external logic.

        Args:
            material_formula: Material chemical formula

        Returns:
            A dictionary containing validation results
        """
        # Initialize the result
        result = {
            "material_formula": material_formula,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- Load existing results from the global context cache ----
            # Reuse data already queried by previous Agents to reduce API call overhead
            try:
                from src.utils.context_store import ContextStore
                cached_identifier = ContextStore.get(f"material_identifier:{material_formula}")
                cached_validator = ContextStore.get(f"structure_validator:{material_formula}")
                cached_mp = ContextStore.get(f"materials_project_search:{material_formula}")
            except Exception:
                cached_identifier = None
                cached_validator = None
                cached_mp = None

            # ---- Step 1: material identification ----
            identifier_tool = get_material_identifier_tool()
            identifier_result = cached_identifier or identifier_tool.identify_material(material_formula)
            result["tool_calls"]["material_identifier"] = identifier_result

            if not ToolCallSpec.validate_material_identifier_result(identifier_result):
                result["validation_passed"] = False
                result["errors"].append("Material identifier validation failed")

            # ---- Step 2: structure validation ----
            validator_tool = get_structure_validator_tool()
            validator_result = cached_validator or validator_tool.validate_structure_exists(material_formula)
            result["tool_calls"]["structure_validator"] = validator_result

            if not ToolCallSpec.validate_structure_validator_result(validator_result):
                result["validation_passed"] = False
                result["errors"].append("Structure validation failed")

            # ---- Step 3: database query (distinguished by material type) ----
            material_type = identifier_result.get("material_type", "unknown")
            if material_type == "metal":
                mp_tool = get_materials_project_tool()

                # Query strategy: cache > reuse from structure validation > exact query by material_id > formula search
                if cached_mp and isinstance(cached_mp, dict) and cached_mp.get("data"):
                    mp_result = cached_mp
                else:
                    validator_data = result["tool_calls"].get("structure_validator", {})
                    if isinstance(validator_data, dict) and validator_data.get("valid") and validator_data.get("source") == "Materials Project" and validator_data.get("data"):
                        mp_result = {
                            "data": [validator_data["data"]],
                            "meta": {"total_count": 1, "limit": 1}
                        }
                    else:
                        add_info = identifier_result.get("additional_info") or {}
                        material_id = add_info.get("material_id")
                        if material_id and mp_tool.validate_material_id(material_id):
                            detail = mp_tool.get_material_by_id(material_id)
                            mp_result = {"data": [detail] if "error" not in detail else [], "meta": {"total_count": 1, "limit": 1}}
                        else:
                            mp_result = mp_tool.search_materials(formula=material_formula, limit=5, fields=["material_id", "formula_pretty"])

                result["tool_calls"]["materials_project"] = mp_result
                if not ToolCallSpec.validate_materials_project_result(mp_result):
                    result["validation_passed"] = False
                    result["errors"].append("Materials Project data validation failed")

            elif material_type == "organic":
                # Call the PubChem tool to query organic compound data
                pubchem_tool = get_pubchem_tool()
                pubchem_result = pubchem_tool.search_compound(material_formula)
                result["tool_calls"]["pubchem"] = pubchem_result

                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append("PubChem data validation failed")

        except Exception as e:
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Assessment expert tool call validation failed: {e}")

        return result


class FinalValidatorToolSpec(ToolCallSpec):
    """
    Tool call specification for the Final Validator Expert.

    The Final Validator Expert is the last checkpoint of the workflow, responsible for
    comprehensively validating the results of all preceding steps.
    It has the most complete tool inventory, including additional property query tools
    and material search tools.

    Unlike the preceding Agents, FinalValidator does not use the context cache;
    instead, it independently re-calls all tools to ensure final data consistency.
    """

    @staticmethod
    def validate_tool_usage(material_formula: str) -> Dict[str, Any]:
        """
        Validate the tool call workflow of the Final Validator Expert.

        Unlike the MaterialDesigner and Assessment experts,
        the Final Validator Expert does not rely on caches and independently calls all
        tools every time to ensure data accuracy.
        This guarantees the credibility of the final output, even though it may incur
        additional API call costs.

        Args:
            material_formula: Material chemical formula

        Returns:
            A dictionary containing validation results
        """
        # Initialize the result
        result = {
            "material_formula": material_formula,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- Step 1: call the material identifier tool directly (no cache) ----
            # Reason for not using the cache: final validation requires the most authoritative and freshest data
            identifier_tool = get_material_identifier_tool()
            identifier_result = identifier_tool.identify_material(material_formula)
            result["tool_calls"]["material_identifier"] = identifier_result

            if not ToolCallSpec.validate_material_identifier_result(identifier_result):
                result["validation_passed"] = False
                result["errors"].append("Material identifier validation failed")

            # ---- Step 2: call the structure validator tool directly (no cache) ----
            validator_tool = get_structure_validator_tool()
            validator_result = validator_tool.validate_structure_exists(material_formula)
            result["tool_calls"]["structure_validator"] = validator_result

            if not ToolCallSpec.validate_structure_validator_result(validator_result):
                result["validation_passed"] = False
                result["errors"].append("Structure validation failed")

            # ---- Step 3: database query (distinguished by material type) ----
            # Note: FinalValidator does not use the ContextStore cache either
            material_type = identifier_result.get("material_type", "unknown")
            if material_type == "metal":
                mp_tool = get_materials_project_tool()

                # Query strategy (by priority):
                # 1. Reuse data from Materials Project returned by the structure validator tool
                # 2. Exact query by material_id
                # 3. Keyword search by chemical formula (fallback)
                validator_data = result["tool_calls"].get("structure_validator", {})
                if isinstance(validator_data, dict) and validator_data.get("valid") and validator_data.get("source") == "Materials Project" and validator_data.get("data"):
                    mp_result = {
                        "data": [validator_data["data"]],
                        "meta": {"total_count": 1, "limit": 1}
                    }
                else:
                    add_info = identifier_result.get("additional_info") or {}
                    material_id = add_info.get("material_id")
                    if material_id and mp_tool.validate_material_id(material_id):
                        detail = mp_tool.get_material_by_id(material_id)
                        mp_result = {"data": [detail] if "error" not in detail else [], "meta": {"total_count": 1, "limit": 1}}
                    else:
                        mp_result = mp_tool.search_materials(formula=material_formula, limit=5, fields=["material_id", "formula_pretty"])

                result["tool_calls"]["materials_project"] = mp_result
                if not ToolCallSpec.validate_materials_project_result(mp_result):
                    result["validation_passed"] = False
                    result["errors"].append("Materials Project data validation failed")

            elif material_type == "organic":
                pubchem_tool = get_pubchem_tool()
                pubchem_result = pubchem_tool.search_compound(material_formula)
                result["tool_calls"]["pubchem"] = pubchem_result

                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append("PubChem data validation failed")

        except Exception as e:
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Final validator expert tool call validation failed: {e}")

        return result


class MechanismExpertToolSpec(ToolCallSpec):
    """
    Tool call specification for the Mechanism Analysis Expert.

    The Mechanism Analysis Expert focuses on analyzing the physicochemical mechanisms
    of materials. It requires fewer tools, mainly relying on Materials Project and
    PubChem for data queries.
    Compared with the design/assessment experts, the Mechanism Analysis Expert does
    not need the structure validator tool.
    """

    @staticmethod
    def validate_tool_usage(material_formula: str) -> Dict[str, Any]:
        """
        Validate the tool call workflow of the Mechanism Analysis Expert.

        The workflow is simpler than that of the design/assessment experts:
        1. Determine the material type via material identification
        2. Call the corresponding database tool directly based on the type

        Note: the Mechanism Analysis Expert does not perform structure validation.

        Args:
            material_formula: Material chemical formula

        Returns:
            A dictionary containing validation results
        """
        # Initialize the result
        result = {
            "material_formula": material_formula,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- Load existing results from the context cache ----
            try:
                from src.utils.context_store import ContextStore
                cached_identifier = ContextStore.get(f"material_identifier:{material_formula}")
                cached_mp = ContextStore.get(f"materials_project_search:{material_formula}")
            except Exception:
                cached_identifier = None
                cached_mp = None

            # ---- Step 1: material identification ----
            identifier_tool = get_material_identifier_tool()
            identifier_result = cached_identifier or identifier_tool.identify_material(material_formula)
            result["tool_calls"]["material_identifier"] = identifier_result

            # ---- Step 2: call the database based on the material type (skip structure validation) ----
            material_type = identifier_result.get("material_type", "unknown")
            if material_type == "metal":
                mp_tool = get_materials_project_tool()

                # Query strategy: cache > exact query by material_id > formula search
                if cached_mp and isinstance(cached_mp, dict) and cached_mp.get("data"):
                    mp_result = cached_mp
                else:
                    # Extract material_id from the material identifier result for an exact query
                    validator_data = result["tool_calls"].get("material_identifier", {})
                    add_info = validator_data.get("additional_info") if isinstance(validator_data, dict) else {}
                    material_id = (add_info or {}).get("material_id")
                    if material_id and mp_tool.validate_material_id(material_id):
                        detail = mp_tool.get_material_by_id(material_id)
                        mp_result = {"data": [detail] if "error" not in detail else [], "meta": {"total_count": 1, "limit": 1}}
                    else:
                        mp_result = mp_tool.search_materials(formula=material_formula, limit=5, fields=["material_id", "formula_pretty"])

                result["tool_calls"]["materials_project"] = mp_result
                if not ToolCallSpec.validate_materials_project_result(mp_result):
                    result["validation_passed"] = False
                    result["errors"].append("Materials Project data validation failed")

            elif material_type == "organic":
                pubchem_tool = get_pubchem_tool()
                pubchem_result = pubchem_tool.search_compound(material_formula)
                result["tool_calls"]["pubchem"] = pubchem_result

                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append("PubChem data validation failed")

        except Exception as e:
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Mechanism analysis expert tool call validation failed: {e}")

        return result


class SynthesisExpertToolSpec(ToolCallSpec):
    """
    Tool call specification for the Synthesis Guidance Expert.

    The Synthesis Guidance Expert focuses on the design and validation of chemical
    synthesis routes.
    Unlike the other Agents, it queries PubChem data not for a single material
    chemical formula but for a set of chemical reagents.
    """

    @staticmethod
    def validate_tool_usage(chemical_reagents: List[str]) -> Dict[str, Any]:
        """
        Validate the tool call workflow of the Synthesis Guidance Expert.

        Key differences from the other Agents:
        - The input is not a single material chemical formula but a list of chemical reagents
        - PubChem is called independently for each reagent in the list
        - The data completeness of each reagent is validated one by one

        Args:
            chemical_reagents: List of chemical reagent names, e.g. ["H2O2", "NaOH", "HCl"]

        Returns:
            A dictionary containing validation results
        """
        # Initialize the result, using chemical_reagents instead of material_formula
        result = {
            "chemical_reagents": chemical_reagents,
            "validation_passed": True,
            "errors": [],
            "tool_calls": {}
        }

        try:
            # ---- Call the PubChem tool for each chemical reagent ----
            pubchem_results = []
            for reagent in chemical_reagents:
                # Create an independent PubChem query for each reagent
                pubchem_tool = get_pubchem_tool()
                pubchem_result = pubchem_tool.search_compound(reagent)
                # Store the reagent name and its query result together in the list for later correlation analysis
                pubchem_results.append({
                    "reagent": reagent,
                    "result": pubchem_result
                })

                # Validate the PubChem result of each reagent
                # If validation fails for any reagent, mark the overall validation as failed
                if not ToolCallSpec.validate_pubchem_result(pubchem_result):
                    result["validation_passed"] = False
                    result["errors"].append(f"PubChem data validation failed for reagent {reagent}")

            # Store the PubChem query results of all reagents in the tool call record
            result["tool_calls"]["pubchem"] = pubchem_results

            # If material information exists, the Materials Project tool can also be called for supplementary queries
            # Left empty here for future extension; real applications may need more complex logic
            # For example: decide whether Materials Project is needed based on properties such as molecular weight and density returned by PubChem

        except Exception as e:
            result["validation_passed"] = False
            result["errors"].append(f"Error occurred during tool invocation: {str(e)}")
            logger.error(f"Synthesis guidance expert tool call validation failed: {e}")

        return result
