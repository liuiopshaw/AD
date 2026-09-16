#!/usr/bin/env python3
"""
PubChem database query tool via REST API.

PubChem database query tool -- queries compound information via the PubChem REST API (PUG-REST).
Supports retrieving physicochemical properties of organic compounds by name, molecular formula,
CID, InChIKey, and more.
"""

# ---- Standard library and third-party imports ----
import requests       # HTTP request library, used to call the PubChem REST API
import logging        # Logging
import time           # Time handling, used for request rate limiting and retry intervals
import random         # Random numbers, used to add random delays on retries (avoid thundering herd)
import os             # OS interface, used to read environment variables
from typing import Dict, Any  # Type annotations

# ---- Logging configuration ----
# WARNING level: only record warnings and errors, reducing log noise during normal operation
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class PubChemTool:
    """
    PubChem database query tool -- encapsulates all query methods of the PubChem PUG-REST API.

    Supported organic material types for querying and validation:
    1. Pure organic compounds
    2. Bio-based materials
    3. Carbon-based materials (partially)
    4. Other materials containing organic components

    Uses the PubChem REST API (PUG-REST):
    Base URL: https://pubchem.ncbi.nlm.nih.gov/rest/pug
    """

    def __init__(self, api_key: str = None):
        """
        Initialize the PubChem tool.

        Args:
            api_key (str, optional): PubChem API key.
                                     If provided, it can increase the API call rate limit.
                                     If not provided, it is read from the environment variable
                                     PUBCHEM_API_KEY.
        """
        # Base address of the PubChem PUG-REST API
        self.base_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

        # API key: prefer the passed-in parameter, fall back to the environment variable
        self.api_key = api_key or os.getenv('PUBCHEM_API_KEY')

        # ---- HTTP request headers ----
        # Set a User-Agent to identify ourselves, in compliance with PubChem usage guidelines
        self.headers = {
            "User-Agent": "ECOMATS-PubChem-Tool/1.0"
        }

        # If an API key is available, add it to the request headers (raises the request rate limit)
        if self.api_key:
            self.headers["X-PubChem-API-Key"] = self.api_key

        # ---- Request rate limiting ----
        # PubChem limits request rates; set a minimum interval to avoid throttling/banning
        self.last_request_time = 0             # Timestamp of the last request
        self.min_request_interval = 1.0        # Minimum request interval: 1 second (faster than default, allowed when an API key is present)

    def _make_request(self, endpoint: str, timeout: int = 10, max_retries: int = 2) -> Dict[str, Any]:
        """
        Send an API request (with retry mechanism) -- the underlying method for all PubChem API calls.

        Retry strategy:
        - 503 error (server busy): use the server-returned Retry-After delay
        - Timeout: retry after a fixed 2 seconds
        - Other request exceptions: exponential backoff + random jitter delay

        Args:
            endpoint: API endpoint path (appended after base_url)
            timeout: Request timeout in seconds, default 10 seconds
            max_retries: Maximum number of retries, default 2

        Returns:
            Dict: Parsed JSON dictionary returned by the API; if all retries fail, returns {"error": ...}
        """
        # ---- Request rate limiting ----
        # Compute the elapsed time since the last request; if insufficient, wait until the minimum interval is met
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last_request)

        for attempt in range(max_retries):
            try:
                # Build the full API URL
                url = f"{self.base_url}/{endpoint}"
                logger.debug(f"Requesting PubChem API: {url}")

                # Update the last request time (before sending the request)
                self.last_request_time = time.time()

                # Send the GET request
                response = requests.get(url, headers=self.headers, timeout=timeout)

                # ---- Special handling for 503 errors ----
                # When the PubChem server is busy it returns 503 with a Retry-After header
                if response.status_code == 503:
                    retry_after = int(response.headers.get('Retry-After', 30))
                    logger.warning(f"PubChem server is busy, will retry after {retry_after} seconds")
                    if attempt < max_retries - 1:
                        logger.info(f"Waiting {retry_after} seconds before retry")
                        time.sleep(retry_after)
                        continue

                # Raise an exception for HTTP errors (4xx/5xx; 503 is already handled above)
                response.raise_for_status()
                # Return the parsed JSON result
                return response.json()

            except requests.exceptions.Timeout:
                # ---- Timeout handling ----
                logger.warning(f"PubChem API request timeout (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    delay = 2  # Wait 2 seconds after a timeout before retrying
                    logger.info(f"Waiting {delay} seconds before retry")
                    time.sleep(delay)
                else:
                    # All retries exhausted
                    logger.error(f"PubChem API request finally timed out")
                    return {"error": f"API request timeout: Please check network connection"}

            except requests.exceptions.RequestException as e:
                # ---- Other request exceptions ----
                logger.warning(f"PubChem API request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:  # Not the last attempt
                    # Exponential backoff + random jitter (1-3 second random delay)
                    # Formula: 2^attempt + random(0, 1): 1s, 2-3s, ...
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    logger.info(f"Waiting {delay:.2f} seconds before retry")
                    time.sleep(delay)
                else:
                    logger.error(f"PubChem API request finally failed: {e}")
                    return {"error": f"API request failed: {str(e)}"}

            except Exception as e:
                # ---- Other unknown exceptions ----
                logger.error(f"Error processing response: {e}")
                return {"error": f"Error processing response: {str(e)}"}

    # ============================================================================
    #  Basic query methods -- query compound properties by different identifiers
    # ============================================================================

    def get_basic_properties_by_name(self, compound_name: str) -> Dict[str, Any]:
        """
        Query basic physicochemical properties by compound name.

        Uses the PubChem API endpoint compound/name/<name>/property/<properties>/JSON.

        Properties retrieved include: molecular formula, molecular weight, IUPAC name,
        SMILES, InChI/InChIKey, XLogP (octanol-water partition coefficient),
        hydrogen bond donor/acceptor counts, rotatable bond count,
        TPSA (topological polar surface area), complexity, etc.

        Args:
            compound_name: Compound name (in English), e.g. "caffeine", "benzene"

        Returns:
            Dict: Basic compound property information
        """
        # Build the endpoint: fetch all key properties in a single request
        endpoint = f"compound/name/{compound_name}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
        return self._make_request(endpoint, max_retries=3)

    def get_synonyms_with_cas(self, compound_name: str) -> Dict[str, Any]:
        """
        Get the compound synonym list (including CAS numbers).

        CAS numbers follow the format XXXXX-XX-X and can be filtered out of the synonym list.
        This is the primary way to obtain CAS numbers, since PubChem has no dedicated
        "CAS" property field.

        Args:
            compound_name: Compound name

        Returns:
            Dict: Response containing the synonym list, from which CAS numbers can be filtered
        """
        endpoint = f"compound/name/{compound_name}/synonyms/JSON"
        return self._make_request(endpoint, max_retries=3)

    def get_properties_by_cid(self, cid: int) -> Dict[str, Any]:
        """
        Get detailed information by PubChem CID (unique integer compound identifier).

        When the compound's CID is already known, this method is more precise and
        efficient than querying by name.

        Args:
            cid: PubChem compound ID (positive integer), e.g. 2519 (caffeine)

        Returns:
            Dict: Detailed compound information
        """
        endpoint = f"compound/cid/{cid}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
        return self._make_request(endpoint, max_retries=3)

    def search_by_molecular_formula(self, formula: str) -> Dict[str, Any]:
        """
        Search compounds by molecular formula.

        Uses PubChem's fastformula endpoint, which is optimized for molecular formula
        searches and is faster than a general search.

        Args:
            formula: Chemical molecular formula, e.g. "C8H10N4O2" (caffeine)

        Returns:
            Dict: List of compounds matching the molecular formula, with properties
        """
        endpoint = f"compound/fastformula/{formula}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
        return self._make_request(endpoint, max_retries=3)

    def search_by_inchikey(self, inchikey: str) -> Dict[str, Any]:
        """
        Search compounds by InChIKey.

        InChIKey is the standard hashed identifier of a compound (27 characters),
        used to uniquely identify a chemical structure.
        For example: RYYVLZVUVIJVGH-UHFFFAOYSA-N (caffeine)

        Args:
            inchikey: InChIKey identifier string

        Returns:
            Dict: Compound information
        """
        endpoint = f"compound/inchikey/{inchikey}/property/MolecularFormula,MolecularWeight,IUPACName,CanonicalSMILES,IsomericSMILES,InChI,InChIKey,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
        return self._make_request(endpoint, max_retries=3)

    # ============================================================================
    #  Smart search -- automatically detect the query type and call the matching endpoint
    # ============================================================================

    def search_compound(self, query: str, search_type: str = "auto") -> Dict[str, Any]:
        """
        Smart compound search -- automatically determines the query type and routes
        it to the appropriate endpoint.

        Decision logic when search_type="auto":
        1. If it matches the InChIKey format (27 characters, contains hyphens) -> use the inchikey endpoint
        2. If it looks like a molecular formula (element symbols + digits) -> use the fastformula endpoint
        3. Otherwise -> use the name endpoint

        Args:
            query: Query content (compound name, molecular formula, or InChIKey)
            search_type: Search type ("auto": automatic, "name": name, "formula": molecular formula, "inchikey": InChIKey)

        Returns:
            Dict: Compound query result
        """
        if search_type == "auto":
            # Check whether it is in InChIKey format (27 characters, at least 2 hyphens)
            if len(query) == 27 and query.count('-') >= 2:
                # Most likely an InChIKey; query via the inchikey endpoint
                return self.search_by_inchikey(query)
            # Check whether it is in molecular formula format (element symbols and digits)
            elif self._is_molecular_formula(query):
                # Most likely a molecular formula; query via the fastformula endpoint
                return self.search_by_molecular_formula(query)
            else:
                # Default to querying by compound name
                return self.get_basic_properties_by_name(query)
        elif search_type == "name":
            return self.get_basic_properties_by_name(query)
        elif search_type == "formula":
            return self.search_by_molecular_formula(query)
        elif search_type == "inchikey":
            return self.search_by_inchikey(query)
        else:
            return {"error": f"Unsupported search type: {search_type}"}

    def _is_molecular_formula(self, query: str) -> bool:
        """
        Determine whether the query string is in molecular formula format.

        Characteristics of a molecular formula:
        - Composed of element symbols (starting with an uppercase letter, optionally
          followed by a lowercase letter) and digits
        - May contain parentheses (e.g. Ca(OH)2)
        - Examples: H2O, C6H6, C12H22O11, Ca(OH)2, NaCl

        Two regex patterns are used:
        - Pattern 1: pure element-digit sequence, e.g. NaCl, H2O, C6H12O6
        - Pattern 2: formula containing parentheses, e.g. Ca(OH)2, Al2(SO4)3

        Args:
            query: The string to check

        Returns:
            bool: Whether it looks like a molecular formula
        """
        import re
        # Pattern 1: pure element symbol + digit sequence -- e.g. "NaCl", "H2O", "C6H12O6"
        # Pattern 2: formula containing parentheses -- e.g. "Ca(OH)2", "Al2(SO4)3"
        # Each element symbol: an uppercase letter [A-Z] followed by 0-1 lowercase letters [a-z]?,
        # then 0 or more digits [0-9]*
        formula_pattern = r'^([A-Z][a-z]?[0-9]*)+([A-Z][a-z]?[0-9]*)*$|^([A-Z][a-z]?[0-9]*)*\([A-Z][a-z]?[0-9]*\)[0-9]*([A-Z][a-z]?[0-9]*)*$'
        return bool(re.match(formula_pattern, query))

    # ============================================================================
    #  Get complete compound information -- integrate results from multiple queries
    # ============================================================================

    def get_compound_info(self, query: str) -> Dict[str, Any]:
        """
        Get complete compound information -- first search to obtain the CID, then
        fetch detailed properties by CID.

        This method is the main entry point for obtaining complete compound information. It:
        1. First locates the compound via smart search
        2. Extracts the CID
        3. Fetches the full property list by CID
        4. Performs basic validation on the SMILES
        5. Merges all information and returns it

        Args:
            query: Compound name, CID, molecular formula, or InChIKey

        Returns:
            Dict: Complete compound information, in the format {"Compound": {property dict}}
        """
        try:
            # Step 1: smart search to get basic information and the CID
            basic_info = self.search_compound(query)

            # If the search returned an error, return it directly
            if "error" in basic_info:
                return basic_info

            try:
                # Step 2: extract the CID from the search results
                if "PropertyTable" in basic_info and "Properties" in basic_info["PropertyTable"]:
                    properties = basic_info["PropertyTable"]["Properties"]
                    if properties and len(properties) > 0:
                        cid = properties[0].get("CID")
                        if cid:
                            # Step 3: fetch detailed properties by CID
                            endpoint = f"compound/cid/{cid}/property/CanonicalSMILES,IsomericSMILES,InChI,InChIKey,MolecularFormula,MolecularWeight,IUPACName,XLogP,HBondDonorCount,HBondAcceptorCount,RotatableBondCount,TPSA,Complexity/JSON"
                            details = self._make_request(endpoint, max_retries=3)

                            if "PropertyTable" in details and "Properties" in details["PropertyTable"]:
                                detail_props = details["PropertyTable"]["Properties"][0]

                                # ---- Extract and validate SMILES ----
                                canonical_smiles = detail_props.get("CanonicalSMILES", "N/A")
                                isomeric_smiles = detail_props.get("IsomericSMILES", "N/A")

                                # Perform validity checks on the SMILES
                                if canonical_smiles != "N/A" and self._is_valid_smiles(canonical_smiles):
                                    canonical_smiles_value = canonical_smiles
                                else:
                                    canonical_smiles_value = "N/A"

                                if isomeric_smiles != "N/A" and self._is_valid_smiles(isomeric_smiles):
                                    isomeric_smiles_value = isomeric_smiles
                                else:
                                    isomeric_smiles_value = "N/A"

                                # ---- Merge all property information ----
                                result = properties[0].copy()  # Keep the base properties from the first query
                                result.update({
                                    "canonical_smiles": canonical_smiles_value,
                                    "isomeric_smiles": isomeric_smiles_value,
                                    "inchi": detail_props.get("InChI", "N/A"),
                                    "inchi_key": detail_props.get("InChIKey", "N/A"),
                                    "molecular_formula": detail_props.get("MolecularFormula", "N/A"),
                                    "molecular_weight": detail_props.get("MolecularWeight", "N/A"),
                                    "iupac_name": detail_props.get("IUPACName", "N/A"),
                                    "xlogp": detail_props.get("XLogP", "N/A"),
                                    # XLogP: computed octanol-water partition coefficient, measures lipophilicity
                                    "hydrogen_bond_donor_count": detail_props.get("HBondDonorCount", "N/A"),
                                    # Hydrogen bond donor count: affects solubility and drug activity
                                    "hydrogen_bond_acceptor_count": detail_props.get("HBondAcceptorCount", "N/A"),
                                    # Hydrogen bond acceptor count
                                    "rotatable_bond_count": detail_props.get("RotatableBondCount", "N/A"),
                                    # Rotatable bond count: measures molecular flexibility
                                    "tpsa": detail_props.get("TPSA", "N/A"),
                                    # TPSA: topological polar surface area, predicts cell membrane permeability
                                    "complexity": detail_props.get("Complexity", "N/A")
                                    # Complexity: molecular structural complexity score
                                })
                                return {"Compound": result}
                            else:
                                return {"error": "Failed to get compound detailed information"}
                        else:
                            return {"error": "Failed to extract compound CID"}
                    else:
                        return {"error": "Compound property information not found"}
                else:
                    # No data in the property table; return the basic information
                    return basic_info

            except Exception as e:
                logger.error(f"Error getting compound detailed information: {e}")
                return {"error": f"Error getting compound detailed information: {str(e)}"}

        except Exception as e:
            logger.error(f"Error getting complete compound information: {e}")
            return {"error": f"Error getting complete compound information: {str(e)}"}

    def _is_valid_smiles(self, smiles: str) -> bool:
        """
        Simply validate the validity of a SMILES string.

        SMILES (Simplified Molecular Input Line Entry System) is a specification for
        representing chemical structures as ASCII strings. This method performs basic
        checks without relying on third-party chemistry libraries.

        Validation rules:
        1. Must not contain obviously invalid values (placeholders such as N/A, None, null)
        2. Must contain at least one letter (a valid SMILES necessarily contains element symbols)
        3. Must contain at least one common chemical element symbol (C, H, O, N, etc.)

        Args:
            smiles: The SMILES string to validate

        Returns:
            bool: Whether it passes basic validation
        """
        # Rule 1: exclude obviously invalid placeholder values (exact match, no substring matching)
        # Note: "#" is a legal character in SMILES (denotes a triple bond, e.g. C#N), so it cannot
        # be treated as invalid; an empty string is checked explicitly because "" in smiles is
        # always True for any string
        invalid_placeholders = {"N/A", "None", "null", "NULL"}
        if not smiles or smiles.strip() in invalid_placeholders:
            return False

        # Rule 2: must contain at least one letter character
        if not any(c.isalpha() for c in smiles):
            return False

        # Rule 3: must contain at least one common chemical element symbol
        common_elements = ['C', 'H', 'O', 'N', 'P', 'S', 'F', 'Cl', 'Br', 'I', 'B', 'Si']
        if not any(element in smiles for element in common_elements):
            return False

        return True

    def validate_cid(self, cid: Any) -> bool:
        """
        Validate whether a CID format is valid (format check only, no API call).

        A valid CID must be a value convertible to a positive integer (> 0).
        A PubChem CID is a unique integer identifier for each compound.

        Args:
            cid: The CID value to validate

        Returns:
            bool: Whether the format is valid
        """
        try:
            # Exclude empty values and placeholders
            if cid is None or cid == "" or cid == "N/A":
                return False
            # CID must be a positive integer
            cid_int = int(cid)
            return cid_int > 0
        except (ValueError, TypeError):
            return False

    # ============================================================================
    #  Validated compound information -- with data checks and validation flags
    # ============================================================================

    def get_validated_compound_info(self, query: str) -> Dict[str, Any]:
        """
        Get validated compound information.

        Compared to get_compound_info, this adds:
        1. CID format validity check (positive integer check)
        2. Molecular weight sanity check (must be positive)
        3. Adds a validated=True flag and a validation_time timestamp

        Args:
            query: Query content

        Returns:
            Dict: Validated compound information; contains error information on failure
        """
        try:
            # First get the complete compound information
            compound_info = self.get_compound_info(query)

            # If the underlying query already failed, return it directly
            if "error" in compound_info:
                return compound_info

            # ---- Perform validation ----
            if "Compound" in compound_info:
                compound = compound_info["Compound"]
                cid = compound.get("CID")

                # Validation 1: CID format
                if not self.validate_cid(cid):
                    return {
                        "success": False,
                        "query": query,
                        "error": f"Invalid CID: {cid}"
                    }

                # Validation 2: molecular weight must be positive
                molecular_weight = compound.get("MolecularWeight")
                if molecular_weight == "N/A" or molecular_weight is None:
                    # A missing molecular weight is acceptable (some compounds may not have this data)
                    pass
                else:
                    try:
                        mw = float(molecular_weight)
                        if mw <= 0:
                            return {
                                "success": False,
                                "query": query,
                                "error": f"Invalid molecular weight: {molecular_weight}"
                            }
                    except (ValueError, TypeError):
                        # Molecular weight is not numeric, but it may be a special value; let it pass for now
                        pass

                # ---- Add validation flags ----
                compound_info["validated"] = True                # Mark as validated
                compound_info["validation_time"] = time.time()   # Record the validation timestamp

            return compound_info

        except Exception as e:
            logger.error(f"Error validating compound information: {e}")
            return {
                "success": False,
                "query": query,
                "error": f"Validation failed: {str(e)}"
            }

    # ============================================================================
    #  Complete compound information including CAS numbers
    # ============================================================================

    def get_compound_info_with_cas(self, query: str) -> Dict[str, Any]:
        """
        Get complete compound information including CAS numbers.

        A CAS (Chemical Abstracts Service) number is an authoritative identifier for
        chemical substances. PubChem has no dedicated CAS field; CAS numbers are hidden
        in the synonym list (format: XXXXX-XX-X). This method first queries the basic
        properties to obtain the CID, then queries the synonyms and filters out CAS numbers.

        Args:
            query: Compound name or molecular formula

        Returns:
            Dict: Compound information containing a CASNumbers array
        """
        # Step 1: get basic property information
        basic_info = self.search_compound(query)

        if "error" in basic_info:
            return basic_info

        try:
            # Step 2: extract the CID from the property table
            if "PropertyTable" in basic_info and "Properties" in basic_info["PropertyTable"]:
                properties = basic_info["PropertyTable"]["Properties"]
                if properties and len(properties) > 0:
                    cid = properties[0].get("CID")
                    if cid:
                        # Step 3: get the synonym list (which contains CAS numbers)
                        synonyms_data = self.get_synonyms_with_cas(query)
                        cas_numbers = []

                        # Parse the synonym response and extract CAS numbers
                        if "InformationList" in synonyms_data and "Information" in synonyms_data["InformationList"]:
                            info_list = synonyms_data["InformationList"]["Information"]
                            if info_list and len(info_list) > 0:
                                synonyms = info_list[0].get("Synonym", [])
                                # Filter out synonyms matching the CAS format (XXXXX-XX-X)
                                cas_numbers = [syn for syn in synonyms if self._is_cas_number(syn)]

                        # Step 4: merge the CAS numbers into the result
                        result = properties[0].copy()
                        result["CASNumbers"] = cas_numbers
                        return {"Compound": result}

            # Return the basic information when no CAS information is available
            return basic_info

        except Exception as e:
            logger.error(f"Error getting complete compound information: {e}")
            return {"error": f"Error getting complete compound information: {str(e)}"}

    def _is_cas_number(self, text: str) -> bool:
        """
        Determine whether the text is in CAS number format.

        A CAS number is divided by hyphens into three parts: XXXXX-XX-X
        - Part 1: 2-7 digits
        - Part 2: 2 digits
        - Part 3: 1 check digit

        Examples: 58-08-2 (caffeine), 7732-18-5 (water)

        Args:
            text: The text to check

        Returns:
            bool: Whether it matches the CAS number format
        """
        import re
        # CAS regex: 2-7 digits - 2 digits - 1 digit
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'
        return bool(re.match(cas_pattern, text))

# ============================================================================
#  Global singleton management
# ============================================================================

# Global PubChemTool instance, initially None
pubchem_tool = None

def get_pubchem_tool(api_key: str = None) -> PubChemTool:
    """
    Get the PubChem tool singleton instance.
    Uses lazy initialization: created on first call, the same instance returned on subsequent calls.

    Args:
        api_key (str, optional): PubChem API key (used only on first creation)

    Returns:
        PubChemTool: The tool instance
    """
    global pubchem_tool
    if pubchem_tool is None:
        pubchem_tool = PubChemTool(api_key)
    return pubchem_tool
