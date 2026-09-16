#!/usr/bin/env python3
"""
PNEC Tool.
PNEC (Predicted No Effect Concentration) database query tool.
Used to query predicted no effect concentration data of chemical substances.

This module provides query functionality for PNEC (Predicted No Effect Concentration) data.
PNEC is a key indicator in environmental risk assessment, representing the maximum
concentration of a chemical substance in the environment that will not cause
adverse effects on ecosystems.
"""

import logging
import re
import requests
from typing import Dict, Any, List

# Configure logging: set the default log level to WARNING to avoid excessive debug output
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class PNECTool:
    """PNEC Tool Class - Query predicted no effect concentration data of chemical substances.

    This tool class provides two query methods:
    1. Query PNEC data by CAS number
    2. Query PNEC data by compound name
    Internally it uses the PubChem API to retrieve basic compound information; PNEC
    values come only from the built-in metal toxicity reference data (values from
    public literature). For compounds without reference data, it honestly returns
    "no data" and does not provide estimated values.
    """

    def __init__(self):
        """Initialize PNEC tool.

        The following work is done during initialization:
        - Set the base URL of the PubChem REST API
        - Create a reusable HTTP session (reuses TCP connections to improve request efficiency)
        - Set the User-Agent to identify the request source
        - Load the built-in metal toxicity reference data (from public literature)
        """
        # PubChem is an open chemistry database maintained by the NIH, providing
        # public information such as compound structures and properties
        self.base_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
        # Use a Session object to keep the HTTP connection alive, avoiding
        # re-establishing a TCP connection for every request
        self.session = requests.Session()
        # Set a custom User-Agent header so the API server can identify and track
        # the request source
        self.session.headers.update({
            "User-Agent": "ECOMATS-PNEC-Tool/1.0"
        })

        # Toxicity data for common metal elements and their corresponding valence states
        # Keys are element symbols; values are the freshwater PNEC data of that element
        # at different valence states
        # These data come from public environmental risk research literature and are
        # for reference only
        self.metal_toxicity_data = {
            "Ni": {
                "valences": ["Ni²⁺"],  # Common valence state of nickel in aquatic environments
                "cas_numbers": ["7440-02-0"],
                "freshwater_pnec": {
                    "Ni²⁺": {"value": 0.02, "unit": "mg/L", "description": "Predicted no effect concentration of Ni²⁺ ions in freshwater"}
                }
            },
            "W": {
                "valences": ["W⁶⁺"],  # Common valence state of tungsten in aquatic environments
                "cas_numbers": ["7440-07-5"],
                "freshwater_pnec": {
                    "W⁶⁺": {"value": 0.1, "unit": "mg/L", "description": "Predicted no effect concentration of W⁶⁺ ions in freshwater"}
                }
            },
            "Co": {
                "valences": ["Co²⁺"],  # Common valence state of cobalt in aquatic environments
                "cas_numbers": ["7440-48-4"],
                "freshwater_pnec": {
                    "Co²⁺": {"value": 0.01, "unit": "mg/L", "description": "Predicted no effect concentration of Co²⁺ ions in freshwater"}
                }
            },
            "Mo": {
                "valences": ["Mo⁶⁺"],  # Common valence state of molybdenum in aquatic environments
                "cas_numbers": ["7439-98-7"],
                "freshwater_pnec": {
                    "Mo⁶⁺": {"value": 0.05, "unit": "mg/L", "description": "Predicted no effect concentration of Mo⁶⁺ ions in freshwater"}
                }
            },
            "Fe": {
                "valences": ["Fe²⁺", "Fe³⁺"],  # Iron has two common valence states; the corresponding PNEC is given for each
                "cas_numbers": ["7439-89-6"],
                "freshwater_pnec": {
                    "Fe²⁺": {"value": 0.5, "unit": "mg/L", "description": "Predicted no effect concentration of Fe²⁺ ions in freshwater"},
                    "Fe³⁺": {"value": 0.3, "unit": "mg/L", "description": "Predicted no effect concentration of Fe³⁺ ions in freshwater"}
                }
            }
        }

    def get_pnec_by_cas(self, cas_number: str) -> Dict[str, Any]:
        """
        Query PNEC data by CAS number.
        Query PNEC data by CAS number. This is the most precise query method,
        because every compound has a unique CAS number.

        Args:
            cas_number (str): CAS number of the chemical substance
                              The CAS number (Chemical Abstracts Service Registry Number)
                              is the unique identifier of a chemical substance, usually
                              in the format XXX-XX-X

        Returns:
            Dict[str, Any]: Dictionary containing PNEC data
                            Returns a dictionary containing the compound name, molecular
                            formula, molecular weight, valence analysis, and PNEC data
        """
        try:
            # Step 1: Get basic compound information from PubChem by CAS number
            compound_info = self._get_compound_info_by_cas(cas_number)

            # If the PubChem query fails, return the error information directly
            if "error" in compound_info:
                return {
                    "success": False,
                    "cas_number": cas_number,
                    "error": compound_info["error"]
                }

            # Step 2: Analyze the valence states of metal elements in the compound
            # Valence analysis is important for PNEC calculation, because the toxicity
            # of the same element at different valence states may differ significantly
            valence_analysis = self._analyze_element_valences(compound_info)

            # Step 3: Summarize PNEC data availability
            # Note: this tool is not connected to a professional PNEC database; when no
            # real data is available it honestly returns "no data"
            pnec_data = self._calculate_pnec(compound_info)

            return {
                "success": True,
                "cas_number": cas_number,
                "compound_name": compound_info.get("name", ""),
                "molecular_formula": compound_info.get("molecular_formula", ""),
                "molecular_weight": compound_info.get("molecular_weight", ""),
                "valence_analysis": valence_analysis,
                "pnec_data": pnec_data
            }

        except Exception as e:
            # Catch all exceptions to ensure the tool does not crash due to unexpected errors
            logger.error(f"Error querying PNEC by CAS number: {e}")
            return {
                "success": False,
                "cas_number": cas_number,
                "error": f"Query failed: {str(e)}"
            }

    def get_pnec_by_name(self, compound_name: str) -> Dict[str, Any]:
        """
        Query PNEC data by compound name.
        Query PNEC data by compound name. This is a two-step query:
        1. First convert the name to a CAS number
        2. Then query the PNEC by CAS number

        Args:
            compound_name (str): Chemical substance name
                                 The compound name, which can be an IUPAC name, a common
                                 name, or a trade name

        Returns:
            Dict[str, Any]: Dictionary containing PNEC data
        """
        try:
            # Step 1: Get the CAS number from the compound name
            # PubChem supports searching compounds by name
            cas_result = self._get_cas_by_name(compound_name)

            # If the name-to-CAS conversion fails, return an error
            if "error" in cas_result:
                return {
                    "success": False,
                    "compound_name": compound_name,
                    "error": cas_result["error"]
                }

            # Extract the CAS number; report an error if it is empty
            cas_number = cas_result.get("cas_number")
            if not cas_number:
                return {
                    "success": False,
                    "compound_name": compound_name,
                    "error": "Could not get CAS number for the compound"
                }

            # Step 2: Reuse the existing method to query PNEC data by CAS number
            # This design avoids code duplication and follows the DRY (Don't Repeat
            # Yourself) principle
            return self.get_pnec_by_cas(cas_number)

        except Exception as e:
            logger.error(f"Error querying PNEC by compound name: {e}")
            return {
                "success": False,
                "compound_name": compound_name,
                "error": f"Query failed: {str(e)}"
            }

    def _get_compound_info_by_cas(self, cas_number: str) -> Dict[str, Any]:
        """
        Get compound basic info by CAS number.
        Get basic compound information from PubChem by CAS number.
        This is an internal method (prefixed with _) and is not exposed externally.

        Args:
            cas_number (str): CAS number

        Returns:
            Dict[str, Any]: Compound basic info
                           Includes CID, molecular formula, molecular weight, IUPAC name,
                           SMILES, etc.
        """
        try:
            # Construct the request URL for the PubChem PUG REST API
            # PUG (Power User Gateway) is PubChem's REST-style API
            # Note: a CAS number is not a PubChem CID, so you cannot directly request
            # compound/cid/{cas}. The correct approach: CAS numbers are indexed in
            # PubChem as synonyms, so use the name endpoint to first resolve the CAS
            # number to a list of CIDs
            url = f"{self.base_url}/compound/name/{cas_number}/cids/JSON"
            # Set a 30-second timeout to prevent the request from waiting indefinitely
            # due to network problems
            response = self.session.get(url, timeout=30)
            # If the server returns an error status code (4xx/5xx), an exception is
            # raised automatically
            response.raise_for_status()
            data = response.json()

            # IdentifierList.CID contains the compound CIDs matched by this CAS number
            # (as a synonym)
            cids = data.get("IdentifierList", {}).get("CID", [])
            if cids:
                # Take the first matching CID (PubChem's internal unique identifier)
                cid = cids[0]

                # Get more detailed compound property information by CID
                details = self._get_compound_details(cid)
                if "error" in details:
                    return details
                # Also add the originally queried CAS number to the details for traceability
                details["cas_number"] = cas_number
                return details
            else:
                return {"error": "Compound not found for this CAS number"}

        except requests.exceptions.RequestException as e:
            # Network request exceptions (connection timeout, DNS failure, server error, etc.)
            logger.error(f"PubChem API request failed: {e}")
            return {"error": f"API request failed: {str(e)}"}
        except Exception as e:
            # Other exceptions such as data parsing errors
            logger.error(f"Error processing response: {e}")
            return {"error": f"Error processing response: {str(e)}"}

    def _get_cas_by_name(self, compound_name: str) -> Dict[str, Any]:
        """
        Get CAS number by compound name.
        Get the CAS number from PubChem by compound name.
        A name search may return multiple candidates; the first matching result is
        used here.

        Args:
            compound_name (str): Compound name

        Returns:
            Dict[str, Any]: Info containing CAS number
        """
        try:
            # Use PubChem's name search endpoint
            url = f"{self.base_url}/compound/name/{compound_name}/json"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "PC_Compounds" in data and len(data["PC_Compounds"]) > 0:
                compound = data["PC_Compounds"][0]
                # The structure of id.id in PUG JSON is {"cid": 2244}; the integer
                # value needs to be extracted from it
                cid_obj = compound["id"]["id"]
                cid = cid_obj.get("cid") if isinstance(cid_obj, dict) else cid_obj

                # Get compound details to extract the CAS number
                # PubChem's name search returns a summary; detailed information
                # requires a separate query
                details = self._get_compound_details(cid)
                return {
                    "cas_number": details.get("cas_number", ""),
                    "name": details.get("name", compound_name)
                }
            else:
                return {"error": "Info not found for this compound name"}

        except requests.exceptions.RequestException as e:
            logger.error(f"PubChem API request failed: {e}")
            return {"error": f"API request failed: {str(e)}"}
        except Exception as e:
            logger.error(f"Error processing response: {e}")
            return {"error": f"Error processing response: {str(e)}"}

    def _get_compound_details(self, cid: str) -> Dict[str, Any]:
        """
        Get compound detailed info.
        Get detailed compound property information by PubChem CID.

        Args:
            cid (str): PubChem compound ID
                       The unique numeric identifier PubChem internally assigns to
                       each compound

        Returns:
            Dict[str, Any]: Compound detailed info
                           Includes molecular formula, molecular weight, IUPAC name,
                           SMILES, etc.
        """
        try:
            # Use PubChem's property endpoint to fetch the required properties in bulk
            # Fetching multiple properties in one request is more efficient than
            # querying them one by one
            # Required properties: title (common name), molecular formula, molecular
            # weight, IUPAC name, canonical SMILES, isomeric SMILES
            url = f"{self.base_url}/compound/cid/{cid}/property/Title,MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES/JSON"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            # PropertyTable.Properties contains all the requested property values
            if "PropertyTable" in data and "Properties" in data["PropertyTable"] and len(data["PropertyTable"]["Properties"]) > 0:
                properties = data["PropertyTable"]["Properties"][0]
                # The CAS number is not a standalone property field in PubChem; it must
                # be extracted from the synonyms list by matching the CAS format
                # (2-7 digits - 2 digits - 1 digit) with a regular expression
                cas_number = self._get_cas_from_synonyms(cid)
                return {
                    "cid": cid,
                    "name": properties.get("Title", ""),
                    "cas_number": cas_number,
                    "molecular_formula": properties.get("MolecularFormula", ""),
                    "molecular_weight": properties.get("MolecularWeight", ""),
                    "iupac_name": properties.get("IUPACName", ""),
                    "canonical_smiles": properties.get("CanonicalSMILES", ""),
                    "isomeric_smiles": properties.get("IsomericSMILES", "")
                }
            else:
                return {"error": "Could not get compound detailed info"}

        except requests.exceptions.RequestException as e:
            logger.error(f"PubChem API request failed: {e}")
            return {"error": f"API request failed: {str(e)}"}
        except Exception as e:
            logger.error(f"Error processing response: {e}")
            return {"error": f"Error processing response: {str(e)}"}

    def _get_cas_from_synonyms(self, cid) -> str:
        """
        Extract CAS number from compound synonyms.
        Extract the CAS number from the compound's synonym list.
        PubChem has no standalone CAS property field; CAS numbers are stored as
        synonyms and must be fetched via the /synonyms endpoint and filtered by format.

        Args:
            cid: PubChem compound ID

        Returns:
            str: The first synonym matching the CAS format; returns an empty string
                 if not found
        """
        try:
            # Synonyms endpoint: returns the full synonym list of the compound
            url = f"{self.base_url}/compound/cid/{cid}/synonyms/JSON"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            info_list = data.get("InformationList", {}).get("Information", [])
            if info_list:
                synonyms = info_list[0].get("Synonym", [])
                # CAS number format: ^\d{2,7}-\d{2}-\d$, e.g. 50-78-2 (aspirin),
                # 7440-02-0 (nickel)
                cas_pattern = r'^\d{2,7}-\d{2}-\d$'
                for syn in synonyms:
                    if re.match(cas_pattern, syn):
                        return syn
            return ""
        except Exception as e:
            # A failed synonym query does not block the main flow; only log it and
            # return an empty string
            logger.warning(f"Failed to extract CAS number from synonyms (CID={cid}): {e}")
            return ""

    def _analyze_element_valences(self, compound_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze valence states of metal elements in compound.
        Analyze the valence states of metal elements in the compound. This is
        important for PNEC calculation because:
        - Different valence states of the same metal element may have significantly
          different toxicity
        - For example, Fe²⁺ and Fe³⁺ have different PNEC values

        Args:
            compound_info (Dict[str, Any]): Compound info

        Returns:
            Dict[str, Any]: Element valence analysis result
        """
        try:
            # Get the compound name and molecular formula
            compound_name = compound_info.get("name", "")
            molecular_formula = compound_info.get("molecular_formula", "")

            # Extract the list of element symbols from the molecular formula
            # For example, "H2O" is extracted as ["H", "O"], and "NiSO4" as
            # ["Ni", "S", "O"]
            elements = self._extract_elements_from_formula(molecular_formula)

            # Iterate over the extracted elements and match them against the built-in
            # metal toxicity data
            # Only keep elements that have records in our metal toxicity data dictionary
            metal_valences = {}
            for element in elements:
                if element in self.metal_toxicity_data:
                    metal_info = self.metal_toxicity_data[element]
                    # Record the element's different valence states in freshwater and
                    # the corresponding PNEC data
                    metal_valences[element] = {
                        "valences": metal_info["valences"],
                        "cas_numbers": metal_info["cas_numbers"],
                        "toxicity_data": metal_info["freshwater_pnec"]
                    }

            return {
                "success": True,
                "compound_name": compound_name,
                "molecular_formula": molecular_formula,
                "metal_elements": metal_valences
            }

        except Exception as e:
            logger.error(f"Error analyzing element valences: {e}")
            return {
                "success": False,
                "error": f"Error analyzing element valences: {str(e)}"
            }

    def _extract_elements_from_formula(self, formula: str) -> List[str]:
        """
        Extract element symbols from chemical formula.
        Extract the list of element symbols from a chemical formula.
        The rule for element symbols in a chemical formula: one uppercase letter
        optionally followed by one lowercase letter (e.g. Na, Fe, Cl).

        Args:
            formula (str): Chemical formula
                           Chemical formula string, e.g. "NiSO4·6H2O", "Fe2O3"

        Returns:
            List[str]: List of element symbols (deduplicated)
                       Deduplicated list of element symbols
        """
        import re
        # Regex to match element symbols: one uppercase letter followed by 0-1
        # lowercase letters
        # This is the standard pattern for element symbols (e.g. H, He, Li, Na)
        elements = re.findall(r'[A-Z][a-z]?', formula)
        # Filter out short strings that may not be elements (validated against a list
        # of common elements)
        valid_elements = []
        # List of common elements (simplified version, covering most common elements
        # in the periodic table)
        # Used to validate whether an extracted symbol is a valid chemical element
        common_elements = ['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar',
                          'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr',
                          'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
                          'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
                          'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn']

        for element in elements:
            # Only keep symbols confirmed to be in the periodic table
            if element in common_elements:
                valid_elements.append(element)

        # Deduplicate using set and convert back to a list (an element may appear
        # multiple times in a chemical formula)
        return list(set(valid_elements))

    def _calculate_pnec(self, compound_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Report PNEC data availability for the compound.
        Report the PNEC data availability for this compound.

        Note: this tool is not connected to a professional PNEC/ecotoxicity database
        and cannot provide real PNEC values. According to project rules, it is
        forbidden to use fabricated formulas or hardcoded data to impersonate real
        query results, so this honestly returns "no data" and never returns an
        estimated value. The only real data available comes from the built-in metal
        toxicity reference table (see valence_analysis).

        Args:
            compound_info (Dict[str, Any]): Compound info

        Returns:
            Dict[str, Any]: A result indicating that data is unavailable (contains no
                            fabricated PNEC values)
        """
        return {
            "acute_pnec": None,
            "chronic_pnec": None,
            "data_available": False,
            "note": "No real PNEC data: this tool is not connected to a professional PNEC/ecotoxicity database and does not provide estimated values"
        }

# Global instance variable (used to implement the singleton pattern)
# The module-level _pnec_tool variable holds the unique instance of PNECTool
_pnec_tool = None

def get_pnec_tool() -> PNECTool:
    """
    Get PNEC tool instance.
    Get the PNEC tool instance. Implements the singleton pattern to ensure there is
    only one PNECTool instance globally. This allows:
    - Reusing the HTTP Session, reducing connection overhead
    - Avoiding repeated initialization of built-in data
    - Ensuring data consistency in multi-threaded/multi-Agent environments

    Returns:
        PNECTool: PNEC tool instance
    """
    global _pnec_tool
    # Create the instance only on the first call (lazy initialization)
    if _pnec_tool is None:
        _pnec_tool = PNECTool()
    return _pnec_tool
