#!/usr/bin/env python3
# Specify the Python interpreter, ensuring the script uses python3 when executed directly in a Unix environment

"""
Data Validator Tool.
Used to validate the authenticity and validity of chemical and material data.
"""
# Module docstring: describes the purpose of this tool - validating the authenticity and validity of chemical and material data

import logging
# Import the logging module to record warning messages during validation

import re
# Import the re module (regular expressions) for format validation of CAS numbers and molecular formulas

import time
# Import the time module to add timestamps to validation results

from typing import Dict, Any, List, Union
# Import type annotations: Dict (dictionary), Any (any type), List (list), Union (union type)

# Configure logging
logging.basicConfig(level=logging.WARNING)
# Configure basic logging settings: only output logs at WARNING level and above

logger = logging.getLogger(__name__)
# Create a logger named after the current module, making it easier to locate the cause of validation failures in logs

class DataValidatorTool:
    """Data Validator Tool Class."""
    # Data validator tool class, providing format and validity validation methods for various chemical and material data

    def __init__(self):
        """Initialize data validator tool."""
        # Initialize the validator tool, preloading the lists of valid values required for validation

        # ==================== List of Valid Chemical Element Symbols ====================
        # Contains all known elements in the periodic table (most of the commonly used ones among the 118 elements)
        # Used to verify whether element symbols extracted from molecular formulas are real elements
        self.valid_elements = [
            'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar',
            'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr',
            'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
            'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
            'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn'
        ]

        # ==================== List of Valid GHS Hazard Statement Codes ====================
        # GHS (Globally Harmonized System of Classification and Labelling of Chemicals) H codes cover physical, health, and environmental hazards
        # Used to verify whether hazard statement codes conform to the GHS standard
        self.valid_h_statements = [
            "H200", "H201", "H202", "H203", "H204", "H205",
            # Physical hazards - Explosives (H200 series)
            "H220", "H221", "H222", "H223", "H224", "H225", "H226",
            # Physical hazards - Flammable gases/liquids (H220 series)
            "H228",
            # Physical hazards - Flammable solids (H228)
            "H240", "H241", "H242",
            # Physical hazards - Self-reactive substances (H240 series)
            "H250", "H251", "H252",
            # Physical hazards - Pyrophoric substances (H250 series)
            "H260", "H261",
            # Physical hazards - Substances which emit flammable gases in contact with water (H260 series)
            "H270", "H271", "H272",
            # Physical hazards - Oxidizing substances (H270 series)
            "H280", "H281",
            # Physical hazards - Gases under pressure (H280 series)
            "H290",
            # Physical hazards - Corrosive to metals (H290)
            "H300", "H301", "H302", "H303", "H304", "H305",
            # Health hazards - Acute toxicity (H300 series)
            "H310", "H311", "H312", "H313",
            # Health hazards - Dermal toxicity (H310 series)
            "H314", "H315", "H316",
            # Health hazards - Skin corrosion/irritation (H314 series)
            "H317",
            # Health hazards - Skin sensitization (H317)
            "H318", "H319", "H320",
            # Health hazards - Eye damage/irritation (H318 series)
            "H330", "H331", "H332", "H333",
            # Health hazards - Inhalation toxicity (H330 series)
            "H334", "H335", "H336",
            # Health hazards - Respiratory sensitization/narcotic effects (H334 series)
            "H340", "H341",
            # Health hazards - Germ cell mutagenicity (H340 series)
            "H350", "H351",
            # Health hazards - Carcinogenicity (H350 series)
            "H360", "H361", "H362",
            # Health hazards - Reproductive toxicity (H360 series)
            "H370", "H371",
            # Health hazards - Specific target organ toxicity - single exposure (H370 series)
            "H372", "H373",
            # Health hazards - Specific target organ toxicity - repeated exposure (H373 series)
            "H400", "H401", "H402",
            # Environmental hazards - Aquatic toxicity (H400 series)
            "H410", "H411", "H412", "H413",
            # Environmental hazards - Chronic aquatic toxicity (H410 series)
            "H420"
            # Environmental hazards - Hazardous to the ozone layer (H420)
        ]

    def validate_cid(self, cid: Any) -> Dict[str, Any]:
        """
        Validate if PubChem CID is valid.
        # Validate whether a PubChem Compound ID (CID) is valid

        Args:
            cid: Compound ID
            # Compound ID, which may be a string, integer, or null value

        Returns:
            Validation result dictionary
            # Dictionary containing valid (whether valid), reason (explanation), and value (the validated value)
        """
        try:
            # Check whether the CID is null or a placeholder
            # These values are common during data collection and indicate missing information rather than a valid CID
            if cid is None or cid == "" or cid == "N/A" or cid == "null":
                return {
                    "valid": False,
                    "reason": "CID is empty or invalid",
                    "value": cid
                }
            # Attempt to convert the CID to an integer
            cid_int = int(cid)
            # The CID must be a positive integer (CIDs in PubChem increment starting from 1)
            if cid_int <= 0:
                return {
                    "valid": False,
                    "reason": "CID must be a positive integer",
                    "value": cid
                }
            return {
                "valid": True,
                "reason": "CID is valid",
                "value": cid_int
                # Return the converted integer value to avoid subsequent type inconsistency issues
            }
        except (ValueError, TypeError):
            # Catch conversion exceptions: when cid is not a valid numeric string
            return {
                "valid": False,
                "reason": "CID is not a valid number",
                "value": cid
            }

    def validate_material_id(self, material_id: Any) -> Dict[str, Any]:
        """
        Validate if Materials Project material ID is valid.
        # Validate whether a Materials Project material ID (MP-ID) is valid

        Args:
            material_id: Material ID
            # Material ID, which may be a string or null value

        Returns:
            Validation result dictionary
        """
        try:
            # Check whether the material ID is null or a placeholder
            if material_id is None or material_id == "" or material_id == "N/A" or material_id == "null":
                return {
                    "valid": False,
                    "reason": "Material ID is empty or invalid",
                    "value": material_id
                }
            # Ensure it is a string type
            material_id_str = str(material_id)
            # An MP-ID must start with "mp-" and have a suffix longer than 0 characters (i.e., total length > 3)
            # For example, "mp-1234" is valid, while "mp-" is invalid
            if not material_id_str.startswith("mp-") or len(material_id_str) <= 3:
                return {
                    "valid": False,
                    "reason": "Material ID format is incorrect, should start with 'mp-'",
                    "value": material_id
                }
            return {
                "valid": True,
                "reason": "Material ID is valid",
                "value": material_id_str
                # Return the value normalized to a string
            }
        except (ValueError, TypeError):
            return {
                "valid": False,
                "reason": "Material ID is not a valid string",
                "value": material_id
            }

    def validate_cas_number(self, cas_number: str) -> Dict[str, Any]:
        """
        Validate if CAS number format is correct.
        # Validate whether a CAS Registry Number format is correct

        Args:
            cas_number: CAS number
            # CAS Registry Number string

        Returns:
            Validation result dictionary
        """
        # Check whether the CAS number is null or a placeholder
        if not cas_number or cas_number == "N/A" or cas_number == "null":
            return {
                "valid": False,
                "reason": "CAS number is empty or invalid",
                "value": cas_number
            }

        # ==================== CAS Number Format Validation ====================
        # Standard CAS number format: XXXXXXX-XX-X
        # - First part: 2 to 7 digits
        # - Second part: 2 digits
        # - Third part: 1 check digit
        # Examples: 7732-18-5 (water), 67-64-1 (acetone)
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'
        if re.match(cas_pattern, cas_number):
            return {
                "valid": True,
                "reason": "CAS number format is correct",
                "value": cas_number
            }
        else:
            return {
                "valid": False,
                "reason": "CAS number format is incorrect, should be XXXXX-XX-X format",
                "value": cas_number
            }

    def validate_molecular_formula(self, formula: str) -> Dict[str, Any]:
        """
        Validate if molecular formula is valid.
        # Validate whether a molecular formula is valid

        Args:
            formula: Molecular formula
            # Molecular formula string

        Returns:
            Validation result dictionary
        """
        # Check whether the molecular formula is null or a placeholder
        if not formula or formula == "N/A" or formula == "null":
            return {
                "valid": False,
                "reason": "Molecular formula is empty or invalid",
                "value": formula
            }

        # ==================== Molecular Formula Format Validation ====================
        # Two patterns are supported:
        # Pattern 1: Simple molecular formulas, e.g., H2O, NaCl, C6H12O6
        # Pattern 2: Molecular formulas with parentheses, e.g., Ca(OH)2, Fe(CN)3
        formula_pattern = r'^([A-Z][a-z]?[0-9]*)+([A-Z][a-z]?[0-9]*)*$|^([A-Z][a-z]?[0-9]*)*\([A-Z][a-z]?[0-9]*\)[0-9]*([A-Z][a-z]?[0-9]*)*$'
        if re.match(formula_pattern, formula):
            # Extract all element symbols from the molecular formula
            elements = re.findall(r'[A-Z][a-z]?', formula)
            # Check for invalid elements (symbols not in the list of known elements)
            invalid_elements = [e for e in elements if e not in self.valid_elements]
            if not invalid_elements:
                return {
                    "valid": True,
                    "reason": "Molecular formula format is correct and elements are valid",
                    "value": formula
                }
            else:
                return {
                    "valid": False,
                    "reason": f"Molecular formula contains invalid elements: {', '.join(invalid_elements)}",
                    "value": formula
                }
        else:
            return {
                "valid": False,
                "reason": "Molecular formula format is incorrect",
                "value": formula
            }

    def validate_h_statements(self, h_statements: List[str]) -> Dict[str, Any]:
        """
        Validate if GHS hazard statement codes are valid.
        # Validate whether GHS hazard statement codes (H-statements) are valid

        Args:
            h_statements: List of hazard statement codes
            # List of hazard statement codes

        Returns:
            Validation result dictionary
        """
        # An empty list is considered valid (some chemicals may have no hazard statements)
        if not h_statements:
            return {
                "valid": True,
                "reason": "Hazard statement list is empty",
                "value": h_statements
            }

        # Filter out statements not present in the list of known valid H codes
        invalid_statements = [h for h in h_statements if h not in self.valid_h_statements]
        if not invalid_statements:
            return {
                "valid": True,
                "reason": "All hazard statement codes are valid",
                "value": h_statements
            }
        else:
            return {
                "valid": False,
                "reason": f"Contains invalid hazard statement codes: {', '.join(invalid_statements)}",
                "value": h_statements,
                "invalid_statements": invalid_statements
                # Additionally return the list of invalid statements so the caller can locate the specific issues
            }

    def validate_molecular_weight(self, molecular_weight: Union[str, float]) -> Dict[str, Any]:
        """
        Validate if molecular weight is valid.
        # Validate whether a molecular weight is valid

        Args:
            molecular_weight: Molecular weight
            # Molecular weight, which may be a string or a float

        Returns:
            Validation result dictionary
        """
        # Null values or placeholders are considered acceptable (molecular weight information may not have been retrieved yet)
        if molecular_weight == "N/A" or molecular_weight == "null" or molecular_weight is None:
            return {
                "valid": True,
                # Note: null values are treated as valid=True, because "no data" is not the same as "incorrect data"
                "reason": "Molecular weight is empty (acceptable)",
                "value": molecular_weight
            }

        try:
            # Convert to a float for numeric range validation
            mw = float(molecular_weight)
            # The molecular weight must be positive
            if mw <= 0:
                return {
                    "valid": False,
                    "reason": "Molecular weight must be positive",
                    "value": molecular_weight
                }
            # The molecular weight upper limit is set to 100,000 Da (daltons); values above this may indicate a data error
            # The vast majority of small molecules and materials fall within this range; high-molecular-weight polymers may approach but generally do not exceed it
            elif mw > 100000:
                return {
                    "valid": False,
                    "reason": "Molecular weight is too large, may be incorrect",
                    "value": molecular_weight
                }
            else:
                return {
                    "valid": True,
                    "reason": "Molecular weight is valid",
                    "value": mw
                    # Return the converted float value
                }
        except (ValueError, TypeError):
            # Catch exceptions where conversion to a number fails
            return {
                "valid": False,
                "reason": "Molecular weight is not a valid number",
                "value": molecular_weight
            }

    def validate_chemical_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate the completeness and validity of chemical data.
        # Perform comprehensive validation of chemical data (combined validation)

        Args:
            data: Chemical data dictionary
            # Dictionary containing the various chemical data fields

        Returns:
            Validation result dictionary
            # Dictionary containing overall_valid (whether valid overall), per-field validation results, a timestamp, and the original data
        """
        validation_results = {}
        # Stores the independent validation results for each field

        overall_valid = True
        # Overall validity flag: set to False if any field fails validation

        # ==================== Field-by-Field Validation ====================
        # Only validate fields actually present in the data, avoiding false reports for missing fields

        # Validate CID (if the field exists in the data)
        if "pubchem_cid" in data:
            cid_result = self.validate_cid(data["pubchem_cid"])
            validation_results["cid"] = cid_result
            if not cid_result["valid"]:
                overall_valid = False
                # If any field is invalid, mark the whole as invalid

        # Validate CAS number (if the field exists in the data)
        if "cas_number" in data:
            cas_result = self.validate_cas_number(data["cas_number"])
            validation_results["cas_number"] = cas_result
            if not cas_result["valid"]:
                overall_valid = False

        # Validate molecular formula (if the field exists in the data)
        if "molecular_formula" in data:
            formula_result = self.validate_molecular_formula(data["molecular_formula"])
            validation_results["molecular_formula"] = formula_result
            if not formula_result["valid"]:
                overall_valid = False

        # Validate molecular weight (if the field exists in the data)
        if "molecular_weight" in data:
            mw_result = self.validate_molecular_weight(data["molecular_weight"])
            validation_results["molecular_weight"] = mw_result
            if not mw_result["valid"]:
                overall_valid = False

        # Validate hazard statements (if the field exists in the data and is a list)
        if "hazard_statements" in data and isinstance(data["hazard_statements"], list):
            h_result = self.validate_h_statements(data["hazard_statements"])
            validation_results["hazard_statements"] = h_result
            if not h_result["valid"]:
                overall_valid = False

        # Validate material ID (if the field exists in the data)
        if "material_id" in data:
            material_id_result = self.validate_material_id(data["material_id"])
            validation_results["material_id"] = material_id_result
            if not material_id_result["valid"]:
                overall_valid = False

        # Return the combined validation result
        return {
            "valid": overall_valid,
            # Overall validity: True only if all present fields pass validation
            "validation_results": validation_results,
            # Dictionary of detailed validation results for each field
            "timestamp": time.time(),
            # Unix timestamp recording when the validation occurred
            "data": data
            # Original data returned for traceability of results
        }

# ==================== Global Singleton Instance Management ====================
# Implements a lazy-loading singleton pattern using a module-level variable
_data_validator_tool = None
# Initialized to None; the instance is created on the first call to get_data_validator_tool()

def get_data_validator_tool() -> DataValidatorTool:
    """
    Get data validator tool instance.
    # Get the singleton instance of the data validator tool

    Returns:
        DataValidatorTool: Data validator tool instance
    """
    global _data_validator_tool
    # Declare use of the module-level global variable

    if _data_validator_tool is None:
        # Lazy loading: create the instance only on first call, consistent with the pattern in material_identifier_tool
        _data_validator_tool = DataValidatorTool()
    return _data_validator_tool
    # Return the singleton instance
