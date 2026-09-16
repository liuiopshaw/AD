#!/usr/bin/env python3
"""
Structure Validator Tool - Material structure validation tool
Validates whether a material structure actually exists in known databases.
Validate if material structure actually exists.
"""

import logging
from typing import Dict, Any
# Import the Materials Project tool for querying the metal/inorganic materials database
from src.tools.materials_project_tool import get_materials_project_tool
# Import the PubChem tool for querying the organic compound database
from src.tools.pubchem_tool import get_pubchem_tool
# Import the material type identification tool to automatically determine whether a material is a metal or an organic
from src.tools.material_identifier_tool import get_material_identifier_tool

# Configure logging: set the default log level to WARNING to avoid excessive debug output
logging.basicConfig(level=logging.WARNING)
# Create a logger instance for the current module
logger = logging.getLogger(__name__)

class StructureValidatorTool:
    """Structure validation tool class - validates whether a material structure actually exists.

    Supports structure validation for multiple material types:
    1. Metal materials (validated using the Materials Project database)
    2. Organic materials (validated using the PubChem database)
    3. Composite materials (validated via elemental composition)
    """

    def __init__(self):
        """Initialize the structure validation tool.
        Loads all required sub-tools at initialization (Materials Project, PubChem, material identification tool).
        The Materials Project tool may fail to initialize if the API Key is not configured; in that case it is marked unavailable but does not block.
        """
        try:
            # Try to get the Materials Project tool instance (requires an API Key)
            self.materials_project_tool = get_materials_project_tool()
        except Exception as e:
            # If Materials Project is unavailable (e.g., missing API Key), log a warning and set to None
            logger.warning(f"Materials Project tool not available: {e}")
            self.materials_project_tool = None
        # The PubChem tool requires no API Key; get it directly
        self.pubchem_tool = get_pubchem_tool()
        # Material type identification tool, used to automatically determine whether the query is a metal or an organic
        self.identifier_tool = get_material_identifier_tool()

    def validate_structure_exists(self, material_formula: str) -> Dict[str, Any]:
        """
        Validate whether a material structure actually exists (core method).

        Validation workflow:
        1. First determine the material type via the identification tool (metal/organic/unknown)
        2. Select the corresponding database for querying based on the material type
        3. For unknown types, try both databases in sequence
        4. Return a complete result including validation confidence and a mandatory action flag

        Args:
            material_formula (str): Chemical formula or name of the material

        Returns:
            Dict[str, Any]: Validation result dictionary containing the following fields:
                - query: original query string
                - valid: whether validation passed
                - type: material type
                - data: retrieved data
                - source: data source
                - reason: explanation of the result
                - validation_confidence: validation confidence (low/high)
                - mandatory_action_required: whether a mandatory action is required
        """
        try:
            # Build the initial result dictionary with defaults set to "validation not passed"
            result = {
                "query": material_formula,
                "valid": False,              # Default: validation not passed
                "type": "unknown",           # Default: unknown type
                "data": None,                # Default: no data
                "source": None,              # Default: no source
                "reason": None,              # Default: no reason given
                "validation_confidence": "low"  # Default: low confidence
            }

            # Step 1: Determine the material type via the identification tool (metal/organic)
            if self.identifier_tool:
                # Call the material identification tool to determine the type
                identification = self.identifier_tool.identify_material(material_formula)
                material_type = identification.get("material_type", "unknown")
                result["type"] = material_type

                # Check whether the identification tool has already validated this material
                validation_status = identification.get("validation_status", "not_found")
                is_verified = identification.get("is_verified", False)
                if validation_status == "validated" and is_verified:
                    # If the identification tool has already validated it, set high confidence
                    result["validation_confidence"] = "high"
                    result["reason"] = f"Material type verified as {material_type} by identifier tool"
                    # Record the identifier information provided by the identification tool (e.g., CAS number)
                    result["identifier"] = identification.get("identifier")
                    result["identifier_type"] = identification.get("identifier_type")
                elif validation_status == "not_found":
                    # The identification tool found no matching material
                    result["reason"] = f"Identifier tool could not find matching {material_type} material"
                else:
                    # The identification tool encountered an error during verification
                    result["reason"] = f"Identifier tool verification failed: {identification.get('error', 'unknown error')}"
            else:
                # If the identification tool is unavailable, use a simple elemental analysis to determine the type
                material_type = self._simple_determine_material_type(material_formula)
                result["type"] = material_type
                result["reason"] = "Identifier tool not available, using simple judgment"

            # Step 2: Select the corresponding validation database based on the material type
            if material_type == "metal":
                # Metal materials: validate using the Materials Project database
                validation_result = self._validate_metal_structure(material_formula)
                result.update(validation_result)
                # Update the validation confidence
                if validation_result["valid"]:
                    result["validation_confidence"] = "high"
                else:
                    result["validation_confidence"] = "low"
            elif material_type == "organic":
                # Organic materials: validate using the PubChem database
                validation_result = self._validate_organic_structure(material_formula)
                result.update(validation_result)
                # Update the validation confidence
                if validation_result["valid"]:
                    result["validation_confidence"] = "high"
                else:
                    result["validation_confidence"] = "low"
            else:
                # Unknown type: try both databases in sequence; either one passing is sufficient
                metal_result = self._validate_metal_structure(material_formula)
                if metal_result["valid"]:
                    result.update(metal_result)
                    result["validation_confidence"] = "high"
                else:
                    organic_result = self._validate_organic_structure(material_formula)
                    result.update(organic_result)
                    if organic_result["valid"]:
                        result["validation_confidence"] = "high"
                    else:
                        result["validation_confidence"] = "low"

            # Step 3: Set the mandatory action flag
            # If validation failed, mark that a mandatory action is required (e.g., redesign or supplementary experimental data)
            if not result["valid"]:
                result["mandatory_action_required"] = True
                result["action_description"] = "Material structure failed validation, needs redesign or more experimental data support"
            else:
                result["mandatory_action_required"] = False

            return result

        except Exception as e:
            # Catch all exceptions and return an error result instead of raising
            logger.error(f"Error validating material structure: {e}")
            return {
                "query": material_formula,
                "valid": False,
                "type": "unknown",
                "data": None,
                "source": None,
                "reason": f"Error during validation: {str(e)}",
                "validation_confidence": "low",
                "mandatory_action_required": True,
                "action_description": f"Error occurred during validation: {str(e)}, manual check required"
            }

    def _validate_metal_structure(self, formula: str) -> Dict[str, Any]:
        """
        Validate a metal material structure via the Materials Project database.

        Validation strategy:
        1. First search exactly by chemical formula
        2. If the exact search fails, search for similar materials by constituent elements
        3. If both approaches fail, the material is deemed non-existent

        Args:
            formula (str): Chemical formula

        Returns:
            Dict[str, Any]: Validation result
        """
        # If the Materials Project tool is unavailable, return failure directly
        if not self.materials_project_tool:
            return {
                "valid": False,
                "type": "metal",
                "data": None,
                "source": None,
                "reason": "Materials Project tool not available"
            }

        try:
            # Strategy 1: exact search by chemical formula; limit=1 takes only the best match
            search_result = self.materials_project_tool.search_materials(formula=formula, limit=1)
            if "error" not in search_result and "data" in search_result and search_result["data"]:
                # Matching material found; return success
                material = search_result["data"][0]
                return {
                    "valid": True,
                    "type": "metal",
                    "data": material,
                    "source": "Materials Project",
                    "reason": "Found matching material structure in Materials Project"
                }

            # Strategy 2: formula search failed; try searching by constituent elements
            # Extract element symbols from the chemical formula (e.g., Fe2O3 -> [Fe, O])
            elements = self._extract_elements(formula)
            if elements:
                # Search using the first two elements (most materials consist of 2-3 elements; the first two give the broadest coverage)
                element_result = self.materials_project_tool.search_materials(elements=elements[:2], limit=1)
                if "error" not in element_result and "data" in element_result and element_result["data"]:
                    material = element_result["data"][0]
                    return {
                        "valid": True,
                        "type": "metal",
                        "data": material,
                        "source": "Materials Project",
                        "reason": "Found material structure with same elements in Materials Project"
                    }

            # Neither strategy found a match; return validation failure
            return {
                "valid": False,
                "type": "metal",
                "data": None,
                "source": None,
                "reason": f"No material with formula {formula} found in Materials Project or found material ID is invalid"
            }
        except Exception as e:
            # Catch exceptions during the query and return a failure result
            logger.warning(f"Error validating metal material structure: {e}")
            return {
                "valid": False,
                "type": "metal",
                "data": None,
                "source": None,
                "reason": f"Error validating metal material: {str(e)}"
            }

    def _validate_organic_structure(self, formula: str) -> Dict[str, Any]:
        """
        Validate an organic material structure via the PubChem database.

        For organic compounds, PubChem is the most authoritative public database.
        This method validates by calling the search functionality of the PubChem tool.

        Args:
            formula (str): Chemical formula or compound name

        Returns:
            Dict[str, Any]: Validation result
        """
        try:
            # Search for the compound using the PubChem tool
            compound_info = self.pubchem_tool.search_compound(formula)
            if "error" not in compound_info:
                # No error field in the returned result means the query succeeded
                return {
                    "valid": True,
                    "type": "organic",
                    "data": compound_info,
                    "source": "PubChem",
                    "reason": "Found matching compound structure in PubChem"
                }
            else:
                # PubChem returned an error, meaning no matching compound was found
                return {
                    "valid": False,
                    "type": "organic",
                    "data": None,
                    "source": None,
                    "reason": f"No compound with formula {formula} found in PubChem"
                }
        except Exception as e:
            # Catch query exceptions
            logger.warning(f"Error validating organic compound structure: {e}")
            return {
                "valid": False,
                "type": "organic",
                "data": None,
                "source": None,
                "reason": f"Error validating organic compound: {str(e)}"
            }

    def _simple_determine_material_type(self, query: str) -> str:
        """
        Simple material type determination method (fallback when the identification tool is unavailable).

        Determination logic:
        1. Extract all element symbols from the chemical formula
        2. If it contains metal elements -> metal material
        3. If it is mainly composed of non-metal elements -> organic material
        4. Otherwise -> unknown type

        Args:
            query (str): Query string (usually a chemical formula)

        Returns:
            str: Material type ("metal", "organic", "unknown")
        """
        # Extract all element symbols from the query string
        elements = self._extract_elements(query)

        # List of common metal elements (74 metal elements in total)
        metal_elements = ['Li', 'Be', 'Na', 'Mg', 'Al', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn',
                         'Ga', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Cs', 'Ba',
                         'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf', 'Ta',
                         'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U',
                         'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr']

        # List of common non-metal elements (elements that typically make up organic compounds)
        non_metal_elements = ['H', 'C', 'N', 'O', 'F', 'P', 'S', 'Cl', 'Br', 'I']

        # Check whether any metal element is present
        has_metal = any(element in metal_elements for element in elements)

        # Count the number of non-metal elements
        non_metal_count = sum(1 for element in elements if element in non_metal_elements)
        total_elements = len(elements)

        # Rule 1: if a metal element is present, treat it as a metal material
        if has_metal:
            return "metal"

        # Rule 2: if non-metal elements account for >= 50%, treat it as an organic material
        if total_elements > 0 and non_metal_count / total_elements >= 0.5:
            return "organic"

        # Rule 3: otherwise return unknown type
        return "unknown"

    def _extract_elements(self, query: str) -> list:
        """
        Extract element symbols from a query string.

        Uses a regular expression to match element symbols in a chemical formula.
        Element symbol rule: an uppercase first letter, optionally followed by one lowercase letter (e.g., Fe, Na, Cl).
        After extraction, filter against the list of known elements to remove falsely recognized strings.

        Args:
            query (str): Query string (e.g., "Fe2O3", "TiO2", "NaCl")

        Returns:
            list: Deduplicated list of valid element symbols
        """
        import re
        # Regex match: starts with an uppercase letter, optionally followed by one lowercase letter (matches all possible element symbol formats)
        elements = re.findall(r'[A-Z][a-z]?', query)
        # Filter out strings that are not in the known element list
        valid_elements = []
        # List of known element symbols (first 103 elements, simplified version)
        common_elements = ['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar',
                          'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr',
                          'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
                          'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
                          'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn']

        # Iterate over all matches and keep only those in the known element list
        for element in elements:
            if element in common_elements:
                valid_elements.append(element)

        # Deduplicate using set and return a list (the same element may appear multiple times, e.g., C in CaCO3)
        return list(set(valid_elements))  # Deduplicate

# Global singleton variable: ensures the structure validation tool is created only once in the application
_structure_validator_tool = None

def get_structure_validator_tool() -> StructureValidatorTool:
    """
    Get the singleton instance of the structure validation tool.

    Uses lazy loading: the instance is created on the first call, and subsequent calls return the same instance.
    This both saves resources (avoiding repeated initialization of connections) and ensures state consistency.

    Returns:
        StructureValidatorTool: The structure validation tool instance
    """
    global _structure_validator_tool
    if _structure_validator_tool is None:
        _structure_validator_tool = StructureValidatorTool()
    return _structure_validator_tool
