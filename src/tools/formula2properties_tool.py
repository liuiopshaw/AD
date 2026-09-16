#!/usr/bin/env python3
# Specify that this script should be run with the Python 3 interpreter

"""
Formula to Properties Query Tool.
Query key physicochemical properties by material formula.

Tool for querying material physicochemical properties by chemical formula.
The user inputs a chemical formula (e.g. "TiO2", "LiFePO4"),
and the tool searches the Materials Project database and returns the
corresponding physicochemical properties.
"""

import json
# Import the json module to serialize query results into JSON format strings

import logging
# Import the logging module to record runtime error information

from crewai.tools import BaseTool
# Import the BaseTool base class from crewai.tools to build tools conforming to the CrewAI framework standard

from pydantic import BaseModel, Field
# Import BaseModel and Field from pydantic to define the tool's input parameter model

from src.tools.materials_project_tool import get_materials_project_tool
# Import the singleton getter of the Materials Project tool to access the Materials Project API

logging.basicConfig(level=logging.WARNING)
# Set the log level to WARNING so only warnings and above are emitted, avoiding log noise

logger = logging.getLogger(__name__)
# Get the logger instance for the current module; log entries carry the module name prefix for easier issue tracing

class Formula2PropertiesInput(BaseModel):
    """Formula to Properties Query Tool Input Model
    Input parameter model for the formula-to-properties query tool. Defines the required parameters the tool accepts."""

    formula: str = Field(..., description="Chemical formula")
    # Formula field, of type string
    # "..." (Ellipsis) marks the field as required; it must be provided on every call
    # description provides the parameter explanation for the LLM

class Formula2PropertiesTool(BaseTool):
    """Formula to Properties Query Tool
    Tool class for querying properties by chemical formula. Inherits from CrewAI's BaseTool
    and implements searching materials in the Materials Project by formula and returning detailed properties."""

    name: str = "Formula to Properties Query Tool"
    # The tool's identifier name, used by the CrewAI framework to reference the tool

    description: str = (
        "Query key physicochemical properties by material formula. "
        "Input formula, returns material property information."
    )
    # Tool capability description, telling the LLM what the tool does and when to use it

    args_schema: type[BaseModel] = Formula2PropertiesInput
    # Specifies Formula2PropertiesInput as the input model; CrewAI validates input parameters against it

    def _run(self, formula: str) -> str:
        """
        Query material properties by formula.
        Query a material's physicochemical properties by chemical formula. This is the tool's execution entry method.

        Workflow:
        1. Search the Materials Project database
        2. Take the best-matching material ID
        3. Use the material ID to fetch detailed properties
        4. Return the formatted JSON result

        Args:
            formula: Chemical formula (e.g. H2O, NaCl, TiO2)

        Returns:
            JSON formatted material property info
        """
        try:
            mp_tool = get_materials_project_tool()
            # Get the singleton instance of the Materials Project tool, reusing the existing API connection

            search_result = mp_tool.search_materials(formula=formula, limit=5, fields=["material_id", "formula_pretty"])
            # Search the Materials Project database for materials matching the formula
            # limit=5 caps the results at 5 entries; fields restricts the response to the necessary fields to reduce data transfer
            # formula_pretty is the formatted formula (with sub/superscripts); material_id is the unique identifier

            if "error" in search_result:
                return json.dumps({"error": search_result["error"]}, ensure_ascii=False)
                # If the search API returns an error, wrap the error message as JSON and return it directly

            if not search_result.get("data"):
                return json.dumps({"error": f"No material found with formula {formula}"}, ensure_ascii=False)
                # If the search result is empty (the data field is missing or empty), the database has no record for this formula

            first_material = search_result["data"][0]
            # Take the first (most relevant) material record from the search results

            material_id = first_material.get("material_id")
            # Extract the unique material ID in the Materials Project

            if not material_id or material_id == "N/A":
                return json.dumps({"error": f"No valid material ID found for formula {formula}"}, ensure_ascii=False)
                # If the material ID is invalid or missing, the detailed query cannot proceed; return an error

            detail_result = mp_tool.get_material_by_id(material_id)
            # Use the obtained material ID to request the material's full detailed information

            if "error" in detail_result:
                return json.dumps({"error": detail_result["error"]}, ensure_ascii=False)
                # If the detailed query fails, return the error message

            properties = {
                "formula": detail_result.get("formula", formula),
                # The material's chemical formula; prefer the formatted formula returned by the API, falling back to the user input if absent

                "material_id": detail_result.get("material_id", "N/A"),
                # The material's unique identifier ID in the Materials Project

                "chemsys": detail_result.get("chemsys", "N/A"),
                # Chemical system identifier, indicating which elements the material consists of (e.g. "Li-Fe-P-O")

                "volume": detail_result.get("volume", "N/A"),
                # Unit cell volume in Angstrom^3 (cubic angstroms), reflecting the basic size of the crystal structure

                "density": detail_result.get("density", "N/A"),
                # Theoretical density in g/cm^3, calculated from the unit cell mass and volume

                "nsites": detail_result.get("nsites", "N/A"),
                # Number of atomic sites in the unit cell, i.e. the total count of independent atomic positions within the cell

                "crystal_system": detail_result.get("crystal_system", "N/A")
                # Crystal system type, e.g. cubic, hexagonal, tetragonal, etc.
            }

            return json.dumps(properties, ensure_ascii=False, indent=2)
            # Serialize the properties dictionary into a formatted JSON string
            # ensure_ascii=False keeps non-ASCII characters unescaped
            # indent=2 gives the output an indented hierarchy for readability

        except Exception as e:
            logger.error(f"Error querying properties for formula {formula}: {e}")
            # Log the exception details, including the formula that triggered it and the error stack

            return json.dumps({"error": f"Query error for formula {formula}: {str(e)}"}, ensure_ascii=False)
            # Wrap the exception as a JSON-formatted error response, ensuring the interface always returns valid JSON

# Create the tool's singleton instance at module level
# Created when the module is first imported; subsequent imports share the same instance
formula2properties_tool = Formula2PropertiesTool()

def get_formula2properties_tool():
    """Get formula to properties query tool instance
    Get the singleton instance of the formula-to-properties query tool.
    Provides a unified external access interface returning the module-level singleton tool object."""
    return formula2properties_tool
