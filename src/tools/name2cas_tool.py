#!/usr/bin/env python3
"""
Compound Name to CAS Number Tool.
Convert compound names to CAS numbers via PubChem API.

This module implements the conversion from compound names to CAS numbers.
A CAS number (Chemical Abstracts Service Registry Number) is a globally unique
identifier for a chemical substance; each CAS number corresponds to a specific
chemical substance (including its stereochemical structure).
"""

import logging
import requests
import time
import random
from typing import Dict, Any

# Logging configuration: set the default level to WARNING to avoid excessive debug output
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class NameToCASTool:
    """Compound Name to CAS Number Tool Class.

    Converts compound names to CAS numbers via the PubChem REST API (PUG).
    Workflow:
    1. Search PubChem by compound name to obtain the CID
    2. Use the CID to retrieve detailed properties and extract the CAS number
       from the synonyms list in the properties
    """

    def __init__(self):
        """Initialize NameToCAS tool.

        Initialize the HTTP session and set request headers.
        Using a Session object reuses TCP connections, improving the efficiency
        of multiple requests.
        """
        # Base URL of the PubChem PUG REST API
        # PUG = Power User Gateway, the REST-style programmatic interface provided by PubChem
        self.base_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
        # Create a reusable HTTP session object
        self.session = requests.Session()
        # Set the User-Agent header so PubChem can identify and track the request source
        # A well-defined User-Agent helps the API provider with usage statistics and troubleshooting
        self.session.headers.update({
            "User-Agent": "ECOMATS-NameToCAS-Tool/1.0"
        })

    def _make_request(self, endpoint: str, timeout: int = 30, max_retries: int = 3) -> Dict[str, Any]:
        """
        Send API request with retry mechanism.
        Send an API request with a built-in retry mechanism.
        When a network request fails, it automatically retries using an
        exponential backoff strategy, which is the standard practice for
        handling unstable networks.

        Args:
            endpoint: API endpoint (full URL)
            timeout: Timeout in seconds, default 30 seconds
            max_retries: Maximum number of retries, default 3

        Returns:
            API response data dictionary; returns {"error": ...} if all retries fail
        """
        for attempt in range(max_retries):
            try:
                # Send a GET request with a timeout to prevent indefinite waiting
                response = self.session.get(endpoint, timeout=timeout)
                # raise_for_status() raises an exception for HTTP 4xx/5xx status codes
                response.raise_for_status()
                # Parse and return the JSON response
                return response.json()
            except requests.exceptions.RequestException as e:
                # Log a warning including the current retry count
                logger.warning(f"API request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:  # Not the last attempt; keep retrying
                    # Exponential backoff strategy:
                    # 1st retry: wait 1-2 seconds (2^0 + random 0-1 second)
                    # 2nd retry: wait 2-3 seconds (2^1 + random 0-1 second)
                    # 3rd retry: wait 4-5 seconds (2^2 + random 0-1 second)
                    # The random delay avoids the "thundering herd" effect caused by
                    # multiple concurrent requests retrying simultaneously
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    logger.info(f"Retrying in {delay:.2f} seconds")
                    time.sleep(delay)
                else:
                    # All retries failed; log the final error
                    logger.error(f"API request ultimately failed: {e}")
                    return {"error": str(e)}

    def convert_name_to_cas(self, compound_name: str) -> Dict[str, Any]:
        """
        Convert chemical name to CAS number.
        Convert a chemical name to its CAS number.

        Conversion workflow:
        1. Search PubChem by name -> obtain the Compound ID (CID)
        2. Query detailed properties by CID -> extract the CAS number from the synonyms list

        Args:
            compound_name (str): Name of the chemical substance.
                                 Supports multiple formats such as IUPAC names, common
                                 names, and trade names, e.g. "aspirin",
                                 "acetylsalicylic acid", "2-acetoxybenzoic acid"

        Returns:
            Dict[str, Any]: Dictionary containing the CAS number and other related information.
                            On success=True it includes: compound_name, cid, cas_number,
                            iupac_name, molecular_formula, molecular_weight, synonyms.
                            On success=False it includes error information.
        """
        try:
            # Step 1: Use the PubChem API name search endpoint to get the compound CID
            # PUG API format: /compound/name/{name}/cids/JSON
            # Returns a list of all candidate CIDs matching the name
            endpoint = f"{self.base_url}/compound/name/{compound_name}/cids/JSON"
            result = self._make_request(endpoint)

            # Step 2: Extract the CID from the search results
            # IdentifierList.CID contains the compound IDs found in PubChem's internal database
            if "IdentifierList" in result and "CID" in result["IdentifierList"]:
                cids = result["IdentifierList"]["CID"]
                # The CID may be a single integer or a list of integers
                # If the name matches multiple compounds, take the first one (usually the best match)
                if isinstance(cids, list):
                    cid = cids[0]
                else:
                    cid = cids

                # Step 3: Use the CID to get detailed properties and the synonyms list
                # Note: PubChem's property endpoint does not support the CAS/Synonyms property
                # (such requests return 400). The CAS number must be obtained via the
                # /synonyms/JSON endpoint and then filtered from the synonyms list by CAS format
                prop_endpoint = f"{self.base_url}/compound/cid/{cid}/property/IUPACName,MolecularFormula,MolecularWeight/JSON"
                details = self._make_request(prop_endpoint)
                synonyms_endpoint = f"{self.base_url}/compound/cid/{cid}/synonyms/JSON"
                synonyms_data = self._make_request(synonyms_endpoint)

                # Parse the synonyms list (the CAS number is hidden within it, in a format like 50-78-2)
                synonyms = []
                if "InformationList" in synonyms_data and "Information" in synonyms_data["InformationList"]:
                    info_list = synonyms_data["InformationList"]["Information"]
                    if info_list:
                        synonyms = info_list[0].get("Synonym", [])

                # Step 4: Extract the required information from the returned detailed properties
                if "PropertyTable" in details and "Properties" in details["PropertyTable"]:
                    properties = details["PropertyTable"]["Properties"][0]
                    # Search the synonyms list for strings matching the CAS format
                    # CAS format: up to 7 digits - 2 digits - 1 check digit, e.g. 50-78-2
                    cas_numbers = [syn for syn in synonyms if self._is_cas_number(syn)]
                    # Take the first matching CAS number; return "N/A" if none is found
                    cas_number = cas_numbers[0] if cas_numbers else "N/A"

                    return {
                        "success": True,
                        "compound_name": compound_name,
                        "cid": cid,  # PubChem compound ID
                        "cas_number": cas_number,
                        "iupac_name": properties.get("IUPACName", ""),
                        "molecular_formula": properties.get("MolecularFormula", ""),
                        "molecular_weight": properties.get("MolecularWeight", ""),
                        "synonyms": synonyms  # Complete synonyms list
                    }
                else:
                    # The compound exists in PubChem but has no detailed property data
                    return {
                        "success": False,
                        "compound_name": compound_name,
                        "error": "No detailed information found for this compound",
                        "details": details.get("error", "Unknown error")
                    }
            else:
                # No compound matching this name was found in PubChem
                return {
                    "success": False,
                    "compound_name": compound_name,
                    "error": "No CAS number information found for this compound",
                    "details": result.get("error", "Unknown error")
                }

        except Exception as e:
            # Catch all unexpected exceptions to ensure the tool does not crash
            logger.error(f"Error converting chemical name to CAS number: {e}")
            return {
                "success": False,
                "compound_name": compound_name,
                "error": f"Conversion failed: {str(e)}"
            }

    def _is_cas_number(self, text: str) -> bool:
        """
        Determine if text is in CAS number format.
        Determine whether the text is in a valid CAS number format.

        CAS number format:
        - Consists of three parts separated by hyphens "-"
        - First part: 2-7 digits
        - Second part: 2 digits
        - Third part: 1 digit (check digit)
        - Full format examples: 50-78-2 (aspirin), 7440-02-0 (nickel)

        Note: Only the format is validated here; the check digit is not verified.

        Args:
            text: The text to check

        Returns:
            bool: Whether it matches the CAS number format
        """
        import re
        # Regular expression for CAS numbers:
        # ^\d{2,7}  - starts with 2-7 digits
        # -\d{2}    - hyphen followed by 2 digits
        # -\d$      - hyphen followed by 1 digit, end of string
        cas_pattern = r'^\d{2,7}-\d{2}-\d$'
        # re.match matches from the beginning of the string; returns a match object
        # on success, or None on failure
        return bool(re.match(cas_pattern, text))

# Global instance variable (singleton pattern)
# A module-level variable holds the single instance of NameToCASTool
# Python module imports are thread-safe, so this singleton pattern is also safe
# in multi-threaded environments
_name2cas_tool = None

def get_name2cas_tool() -> NameToCASTool:
    """
    Get Name2CAS tool instance.
    Get the NameToCAS tool instance (singleton pattern).

    Uses lazy initialization:
    - The instance is created on the first call; subsequent calls reuse the same instance
    - Avoids unnecessary resource consumption (HTTP Session, etc.)
    - Ensures global state consistency

    Returns:
        NameToCASTool: The singleton instance of the NameToCAS tool
    """
    global _name2cas_tool
    # Create a new instance only when it is None (lazy initialization)
    if _name2cas_tool is None:
        _name2cas_tool = NameToCASTool()
    return _name2cas_tool
