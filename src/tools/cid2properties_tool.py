#!/usr/bin/env python3
# Specify that this script should be run with the Python 3 interpreter

"""
CID2Properties Tool.
Query compound properties by PubChem CID.

A tool for querying compound properties by PubChem compound CID.
CID (Compound ID) is the unique numeric identifier of each compound in the
PubChem database. This tool uses the PubChem REST API to retrieve compound
information such as molecular formula, molecular weight, and SMILES.
"""

import logging
# Import the logging module to record errors and exceptions during queries

from typing import Dict, Any
# Import type hints from typing; Dict and Any annotate the return value structure

from src.tools.pubchem_tool import get_pubchem_tool
# Import the singleton getter for the PubChem tool, which wraps calls to the PubChem REST API

# Configure the global logging level and format; only WARNING and above are emitted
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
# Get the logger instance for the current module; log output carries the module name
# to make it easier to locate the source of issues

class CID2PropertiesTool:
    """CID2Properties Tool Class - Query compound properties by PubChem CID.
    CID-to-properties query tool class. It does not inherit from BaseTool (it is not
    a direct CrewAI tool); instead it serves as a pure business-logic class invoked
    by a CrewAI wrapper."""

    def __init__(self):
        """Initialize CID2Properties tool.
        Obtain the singleton reference to the PubChem tool when initializing the tool instance."""
        self.pubchem_tool = get_pubchem_tool()
        # Store the PubChem tool instance as an instance attribute for later method calls

    def get_properties_by_cid(self, cid: str) -> Dict[str, Any]:
        """
        Query compound properties by PubChem CID.
        Query detailed property information of a compound by its PubChem CID.

        Args:
            cid (str): PubChem compound ID (string format, converted to an integer internally)

        Returns:
            Dict[str, Any]: Dictionary containing compound properties, structured as
            {"success": bool, "cid": str, ...property fields}
        """
        try:
            # Call the PubChem tool to query compound information by CID; cid is
            # converted from a string to an integer
            result = self.pubchem_tool.get_properties_by_cid(int(cid))
            # int(cid) ensures the CID is passed to the PubChem API in integer format

            # Check whether the query succeeded (absence of an "error" key means success)
            if "error" not in result:
                # Parse the nested data structure returned by the PubChem API
                # PubChem's PropertyTable.Properties array contains the properties of
                # the first matching result
                if "PropertyTable" in result and "Properties" in result["PropertyTable"]:
                    properties = result["PropertyTable"]["Properties"][0]
                    # Take the first element of the Properties array (a CID query
                    # usually returns only one result)

                    return {
                        "success": True,
                        # Mark the query as successful

                        "cid": cid,
                        # Keep the originally queried CID so the caller can cross-reference it

                        "molecular_formula": properties.get("MolecularFormula", "N/A"),
                        # Molecular formula, e.g. H2O, C6H12O6; returns "N/A" if absent

                        "molecular_weight": properties.get("MolecularWeight", "N/A"),
                        # Molecular weight (relative molecular mass), in g/mol

                        "iupac_name": properties.get("IUPACName", "N/A"),
                        # Compound name under IUPAC systematic nomenclature, the most
                        # authoritative chemical naming

                        "canonical_smiles": properties.get("CanonicalSMILES", "N/A"),
                        # Canonical SMILES string, a linear notation uniquely
                        # representing the molecular structure

                        "isomeric_smiles": properties.get("IsomericSMILES", "N/A"),
                        # Isomeric SMILES string, including stereochemical information
                        # (e.g. labels of chiral centers)

                        "inchi": properties.get("InChI", "N/A"),
                        # IUPAC International Chemical Identifier (InChI), the standard
                        # text representation of a molecular structure

                        "inchi_key": properties.get("InChIKey", "N/A")
                        # InChI Key, the hashed version of InChI, used for database
                        # indexing and searching
                    }
                else:
                    return {
                        "success": False,
                        # Mark the query as failed

                        "cid": cid,
                        # Keep the CID for the caller's reference

                        "error": "Unable to parse return data"
                        # The data structure returned by the PubChem API could not be
                        # parsed; the API format may have changed
                    }
            else:
                return {
                    "success": False,
                    # Mark the query as failed

                    "cid": cid,
                    # Keep the CID for the caller's reference

                    "error": result.get("error", "Query failed")
                    # Return the specific error message from the PubChem API; fall back
                    # to a default message if it is empty
                }

        except Exception as e:
            logger.error(f"Error querying compound properties by CID: {e}")
            # Log the exception information, including the specific error description

            return {
                "success": False,
                # Mark the query as failed

                "cid": cid,
                # Keep the CID for the caller's reference

                "error": f"Query failed: {str(e)}"
                # Wrap the exception information as an error message and return it
            }

# Module-level global variable storing the singleton instance of CID2PropertiesTool
# Initialized to None and lazily created on first call
_cid2properties_tool = None

def get_cid2properties_tool() -> CID2PropertiesTool:
    """
    Get CID2Properties tool instance.
    Get the singleton instance of the CID2Properties tool.

    Uses the lazy-loading pattern (Lazy Singleton): the instance is created only on
    the first call, and subsequent calls return the same instance, avoiding repeated
    creation and network connection overhead.

    Returns:
        CID2PropertiesTool: CID2Properties tool instance
        The globally unique instance of the CID2Properties tool
    """
    global _cid2properties_tool
    # Declare use of the module-level global variable so it can be modified in the function

    if _cid2properties_tool is None:
        _cid2properties_tool = CID2PropertiesTool()
        # Create a new instance on the first call; subsequent calls return the existing instance

    return _cid2properties_tool
    # Return the singleton instance
