#!/usr/bin/env python3
# Specify the Python interpreter, ensuring the script uses python3 when executed directly on Unix

"""
Material Identifier Processing Tool.
Unified handling of metal materials and organic compound identifiers (MP-ID and CAS numbers).
"""
# Module docstring: describes the tool's purpose — unified handling of metal material and organic compound identifiers (MP-ID and CAS numbers)

import logging
# Import the logging module for emitting warning and error logs

from typing import Dict, Any, Optional
# Import type annotations from typing: Dict (dictionary), Any (any type), Optional (optional type)

from src.tools.materials_project_tool import get_materials_project_tool
# Import the singleton accessor for the Materials Project tool, used to query MP-IDs for metal materials

from src.tools.pubchem_tool import get_pubchem_tool
# Import the singleton accessor for the PubChem tool, used to query CAS numbers for organic compounds

# Configure logging
logging.basicConfig(level=logging.WARNING)
# Configure basic logging settings: only emit logs at WARNING level and above

logger = logging.getLogger(__name__)
# Create a logger named after the current module, making it easier to locate the source of issues in logs

class MaterialIdentifierTool:
    """Material Identifier Processing Tool - Unified handling of metal and organic material identifiers.
    # Material identifier processing tool — unified handling of metal and organic material identifiers

    Supports identifier processing for multiple material types:
    1. Metal materials (get Materials Project ID)
    # Metal materials — obtain the Materials Project ID (MP-ID)
    2. Organic materials (get CAS number)
    # Organic materials — obtain the CAS registry number
    3. Composite materials (identify by element composition)
    # Composite materials — identified by element composition
    """

    def __init__(self):
        """Initialize material identifier processing tool."""
        # Initialize the material identifier processing tool instance
        try:
            # Try to obtain the Materials Project tool instance
            self.materials_project_tool = get_materials_project_tool()
        except Exception as e:
            # If the Materials Project tool is unavailable (e.g., API key not configured), log a warning and set the attribute to None
            logger.warning(f"Materials Project tool not available: {e}")
            self.materials_project_tool = None
        # Obtain the PubChem tool instance (usually requires no API key, so it should not fail)
        self.pubchem_tool = get_pubchem_tool()

    def identify_material(self, query: str) -> Dict[str, Any]:
        """
        Identify material type and get corresponding identifier.
        # Identify the material type and obtain the corresponding identifier

        Args:
            query (str): Material query string (formula, element combination, or material name)
            # Material query string (chemical formula, element combination, or material name)

        Returns:
            Dict[str, Any]: Dictionary containing material type and identifier information
            # Dictionary containing the material type and identifier information
        """
        try:
            # ==================== Initialize the result dictionary ====================
            # Build a unified result structure with default values preset for all fields
            result = {
                "query": query,
                # Original query string, kept for traceability of the result
                "material_type": "unknown",
                # Material type: metal, organic, or unknown
                "identifier": None,
                # Identifier value: MP-ID or CAS number
                "identifier_type": None,
                # Identifier type: MP-ID or CAS
                "additional_info": {},
                # Additional info dictionary storing extra fields returned by the databases
                "validation_status": "not_found",
                # Validation status: validated, not_found, or error
                "is_verified": False
                # Verification flag: True means the identifier was obtained from a reliable database
            }

            # ==================== Step 1: Determine the material type ====================
            # Determine whether the material is metal, organic, or unknown based on the element composition of the query string
            material_type = self._determine_material_type(query)
            result["material_type"] = material_type

            # ==================== Step 2: Get the identifier according to the material type ====================
            # --- Case A: metal material ---
            if material_type == "metal":
                # Use the Materials Project database to obtain the MP-ID for the metal material
                mp_result = self._get_mpid_for_metal(query)
                if mp_result and "material_id" in mp_result:
                    # Successfully obtained the MP-ID
                    result["identifier"] = mp_result["material_id"]
                    result["identifier_type"] = "MP-ID"
                    result["additional_info"] = mp_result
                    result["validation_status"] = "validated"
                    result["is_verified"] = True
                else:
                    # No matching material found in Materials Project
                    result["validation_status"] = "not_found"
                    result["is_verified"] = False
                    logger.info(f"Could not find material in Materials Project: {query}")

            # --- Case B: organic material ---
            elif material_type == "organic":
                # Use the PubChem database to obtain the CAS number for the organic compound
                cas_result = self._get_cas_for_organic(query)
                if cas_result and "CASNumbers" in cas_result:
                    cas_numbers = cas_result["CASNumbers"]
                    if cas_numbers:
                        # Successfully obtained a CAS number (use the first one in the list)
                        result["identifier"] = cas_numbers[0]
                        result["identifier_type"] = "CAS"
                        result["additional_info"] = cas_result
                        result["validation_status"] = "validated"
                        result["is_verified"] = True
                    else:
                        # PubChem returned data but no CAS number
                        result["validation_status"] = "not_found"
                        result["is_verified"] = False
                        logger.info(f"Could not find CAS number in PubChem: {query}")
                else:
                    # PubChem query failed
                    result["validation_status"] = "not_found"
                    result["is_verified"] = False
                    logger.info(f"Could not find compound info in PubChem: {query}")

            # --- Case C: unknown type (fallback strategy) ---
            else:
                # When the type is uncertain, try both the metal and organic databases in turn
                # Try Materials Project first
                mp_result = self._get_mpid_for_metal(query)
                if mp_result and "material_id" in mp_result:
                    result["identifier"] = mp_result["material_id"]
                    result["identifier_type"] = "MP-ID"
                    result["additional_info"] = mp_result
                    result["material_type"] = "metal"
                    # Backfill the correct material type
                    result["validation_status"] = "validated"
                    result["is_verified"] = True
                else:
                    # No result from Materials Project; try PubChem next
                    cas_result = self._get_cas_for_organic(query)
                    if cas_result and "CASNumbers" in cas_result:
                        cas_numbers = cas_result["CASNumbers"]
                        if cas_numbers:
                            result["identifier"] = cas_numbers[0]
                            result["identifier_type"] = "CAS"
                            result["additional_info"] = cas_result
                            result["material_type"] = "organic"
                            # Backfill the correct material type
                            result["validation_status"] = "validated"
                            result["is_verified"] = True
                        else:
                            result["validation_status"] = "not_found"
                            result["is_verified"] = False
                            logger.info(f"Could not find CAS number in PubChem: {query}")
                    else:
                        # No match found in either database
                        result["validation_status"] = "not_found"
                        result["is_verified"] = False
                        logger.info(f"Could not find material in any database: {query}")

            # ==================== Step 3: Add a safety warning ====================
            # If the identifier was not verified, attach a warning to the result reminding not to use unverified database identifiers
            if not result["is_verified"]:
                result["warning"] = f"Warning: Could not verify identifier for material '{query}'. Do not use unverified database identifiers."

            return result

        except Exception as e:
            # Catch all exceptions and return a result dictionary containing the error information, preventing exceptions from propagating to the caller
            logger.error(f"Error identifying material identifier: {e}")
            return {
                "success": False,
                "query": query,
                "error": f"Identification failed: {str(e)}",
                "validation_status": "error",
                # In the error state, the validation status is marked as error
                "is_verified": False,
                # In the error state, the identifier is naturally unverified
                "warning": f"Warning: Error occurred while verifying identifier for material '{query}'. Do not use unverified database identifiers."
            }

    def _determine_material_type(self, query: str) -> str:
        """
        Determine material type (metal, organic, or other).
        # Determine the material type based on the element composition of the query string

        Args:
            query (str): Query string

        Returns:
            str: Material type ("metal", "organic", "unknown")
            # Returns "metal", "organic", or "unknown"
        """
        # Step 1: Extract element symbols from the query string
        elements = self._extract_elements(query)

        # Step 2: Define the list of common metal elements (including alkali metals, alkaline earth metals, transition metals, rare earths, etc.)
        metal_elements = ['Li', 'Be', 'Na', 'Mg', 'Al', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn',
                         'Ga', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Cs', 'Ba',
                         'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf', 'Ta',
                         'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U',
                         'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr']

        # Step 3: Define the list of common non-metal elements (typically the backbone elements of organic compounds)
        non_metal_elements = ['H', 'C', 'N', 'O', 'F', 'P', 'S', 'Cl', 'Br', 'I']

        # Step 4: Compute the metal and non-metal element situation in the query
        has_metal = any(element in metal_elements for element in elements)
        # Check whether the query contains any metal element

        non_metal_count = sum(1 for element in elements if element in non_metal_elements)
        # Count the number of non-metal elements in the query

        total_elements = len(elements)
        # Total number of elements identified in the query

        # Step 5: Decision logic
        # If a metal element is present, classify as a metal material first
        if has_metal:
            return "metal"

        # If non-metal elements account for >= 50%, classify as an organic material
        if total_elements > 0 and non_metal_count / total_elements >= 0.5:
            return "organic"

        # If none of the above conditions are met, return unknown
        return "unknown"

    def _extract_elements(self, query: str) -> list:
        """
        Extract element symbols from query string.
        # Extract chemical element symbols from the query string

        Args:
            query (str): Query string

        Returns:
            list: List of element symbols
            # Deduplicated list of element symbols
        """
        import re
        # Import re inside the method so it is loaded only when needed, avoiding unnecessary module initialization

        # Use a regex to match an uppercase letter plus an optional lowercase letter (standard element symbol format)
        elements = re.findall(r'[A-Z][a-z]?', query)

        # Initialize the list of valid elements
        valid_elements = []

        # Define the list of common chemical elements (simplified version covering commonly used elements)
        common_elements = ['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar',
                          'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr',
                          'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
                          'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
                          'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn']

        # Filter: keep only symbols present in the known element list (excluding non-element strings such as uppercase abbreviations)
        for element in elements:
            if element in common_elements:
                valid_elements.append(element)

        # Deduplicate via set and return as a list
        # Note: on some Python versions it must be wrapped as list(set(...)) to ensure a mutable list is returned
        return list(set(valid_elements))

    def _get_mpid_for_metal(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Get MP-ID for metal material.
        # Obtain the Materials Project ID for a metal material

        Args:
            query (str): Query string

        Returns:
            Optional[Dict[str, Any]]: Materials Project data or None
            # Material data dictionary or None (meaning not found)
        """
        # If the Materials Project tool is unavailable, return None directly
        if not self.materials_project_tool:
            return None

        try:
            # ==================== Strategy 1: search by chemical formula ====================
            result = self.materials_project_tool.search_materials(
                formula=query,
                limit=5,
                fields=["material_id", "formula_pretty", "chemsys"]
                # Request only the necessary fields to improve query efficiency
            )
            if "error" not in result and "data" in result and result["data"]:
                # Iterate over the search results and verify them one by one
                for material in result["data"]:
                    material_formula = material.get("formula", "")
                    material_id = material.get("material_id", "")

                    # Verify that the MP-ID actually exists in the Materials Project database
                    if material_id and self.materials_project_tool.verify_material_id_exists(material_id):
                        # Check whether the chemical formula is strictly related to the query (to prevent returning irrelevant materials)
                        if self._is_formula_strictly_related(query, material_formula):
                            logger.info(f"Found related material: {material_formula} (ID: {material_id})")
                            return material
                            # Matching material found; return immediately
                        else:
                            logger.warning(f"Found material but formula mismatch: query '{query}' vs '{material_formula}'")
                    else:
                        logger.warning(f"Found invalid material ID: {material_id}")

            # ==================== Strategy 2: search by elements (fallback) ====================
            # If the formula search found nothing, extract element symbols from the query and search again
            elements = self._extract_elements(query)
            if elements:
                result = self.materials_project_tool.search_materials(
                    elements=elements[:3],
                    # Limit to the first 3 elements to avoid an overly broad search scope
                    limit=5,
                    fields=["material_id", "formula_pretty", "chemsys"]
                )
                if "error" not in result and "data" in result and result["data"]:
                    for material in result["data"]:
                        # Extract the elements contained in the material from the chemical system field
                        material_elements = material.get("chemsys", "").split("-")
                        material_id = material.get("material_id", "")

                        # Verify that the MP-ID actually exists
                        if material_id and self.materials_project_tool.verify_material_id_exists(material_id):
                            # Check whether the material elements strictly match the query elements
                            if self._are_elements_strictly_related(elements, material_elements):
                                logger.info(f"Found material with related elements: {material.get('formula', '')} (ID: {material_id})")
                                return material
                            else:
                                logger.warning(f"Found material but elements mismatch: query '{elements}' vs '{material_elements}'")
                        else:
                            logger.warning(f"Found invalid material ID: {material_id}")

            # When both strategies fail, return None (no fabricated data, ensuring data reliability)
            logger.info(f"No matching material found in Materials Project for {query}")
            return None
        except Exception as e:
            logger.warning(f"Error getting MP-ID for metal material: {e}")
            # Even on exception, return None instead of fabricating data
            return None

    def _is_formula_strictly_related(self, query: str, formula: str) -> bool:
        """
        Strictly check if query and formula are related.
        # Strictly check whether the query string and the chemical formula are related

        Args:
            query (str): Query string
            formula (str): Chemical formula

        Returns:
            bool: Whether related
            # True means related, False means not related
        """
        # Extract the element sets from the query and the formula
        query_elements = set(self._extract_elements(query))
        formula_elements = set(self._extract_elements(formula))

        # Define the list of main metal elements (used for special handling of organic-ligand composite scenarios)
        # For example, composites like (FeTCPP)Co(Melm) need to match the core metal elements
        main_metal_elements = ['Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Mn', 'Cr', 'V', 'Ti']
        query_metals = [e for e in query_elements if e in main_metal_elements]
        formula_metals = [e for e in formula_elements if e in main_metal_elements]

        # If the query and the formula contain the same main metal elements, consider them related
        # This handles metal complexes with complex organic ligands
        if query_metals and formula_metals and set(query_metals) == set(formula_metals):
            return True

        # General case: check the proportion of shared elements
        # If at least 50% of the query elements appear in the formula, consider them related
        if len(query_elements) > 0:
            common_elements = query_elements.intersection(formula_elements)
            return len(common_elements) / len(query_elements) >= 0.5

        return False

    def _are_elements_strictly_related(self, query_elements: list, material_elements: list) -> bool:
        """
        Strictly check if query elements and material elements are related.
        # Strictly check whether the query elements and the material elements are related

        Args:
            query_elements (list): Query element list
            material_elements (list): Material element list

        Returns:
            bool: Whether related
            # True means related, False means not related
        """
        query_set = set(query_elements)
        material_set = set(material_elements)

        # Check whether the proportion of shared elements reaches the 50% threshold
        if len(query_set) > 0:
            common_elements = query_set.intersection(material_set)
            return len(common_elements) / len(query_set) >= 0.5

        return False

    def _is_formula_related(self, query: str, formula: str) -> bool:
        """
        Check if query and formula are related.
        # (Lenient version) Check whether the query and the chemical formula are related — any shared element counts as related

        Args:
            query (str): Query string
            formula (str): Chemical formula

        Returns:
            bool: Whether related
        """
        # Extract the element sets from the query and the formula
        query_elements = set(self._extract_elements(query))
        formula_elements = set(self._extract_elements(formula))

        # As long as at least one common element exists, consider them related (more lenient than the strict version)
        return len(query_elements.intersection(formula_elements)) > 0

    def _are_elements_related(self, query_elements: list, material_elements: list) -> bool:
        """
        Check if query elements and material elements are related.
        # (Lenient version) Check whether the query elements and the material elements are related — any shared element counts as related

        Args:
            query_elements (list): Query element list
            material_elements (list): Material element list

        Returns:
            bool: Whether related
        """
        query_set = set(query_elements)
        material_set = set(material_elements)

        # As long as at least one common element exists, consider them related (more lenient than the strict version)
        return len(query_set.intersection(material_set)) > 0

    def _get_cas_for_organic(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Get CAS number for organic material.
        # Obtain the CAS registry number for an organic material

        Args:
            query (str): Query string

        Returns:
            Optional[Dict[str, Any]]: PubChem data (containing CAS number) or None
            # PubChem data dictionary (containing the CAS number) or None
        """
        try:
            # Query compound information (including the CAS registry number) via the PubChem tool
            result = self.pubchem_tool.get_compound_info_with_cas(query)
            # Check whether the query succeeded and returned compound data
            if "error" not in result and "Compound" in result:
                return result["Compound"]
                # Return the compound info dictionary; the caller extracts the CASNumbers field from it
            return None
        except Exception as e:
            logger.warning(f"Error getting CAS number for organic material: {e}")
            return None
            # On exception, return None without fabricating data

# ==================== Global singleton instance management ====================
# Use a module-level variable to implement the lazy-loading singleton pattern
_material_identifier_tool = None
# Initialized to None; the instance is created on the first call to get_material_identifier_tool()

def get_material_identifier_tool() -> MaterialIdentifierTool:
    """
    Get material identifier processing tool instance.
    # Get the singleton instance of the material identifier processing tool

    Returns:
        MaterialIdentifierTool: Material identifier processing tool instance
    """
    global _material_identifier_tool
    # Declare use of the module-level global variable

    if _material_identifier_tool is None:
        # Lazy loading: create the instance only on the first call
        _material_identifier_tool = MaterialIdentifierTool()
    return _material_identifier_tool
    # Return the singleton instance, ensuring only one tool instance exists globally to save resources
