#!/usr/bin/env python3
# Use the Python 3 interpreter to run this script

"""
Name to Properties Query Tool.
Query key physicochemical properties by material name.

A tool for querying key physicochemical properties by material name.
The user provides a material name, and the tool returns the material's key
physicochemical property information (such as density, volume, crystal system, etc.).
"""

import json
# Import the json module to serialize query results into a JSON-formatted string

import logging
# Import the logging module to record error logs for debugging and tracing runtime exceptions

from crewai.tools import BaseTool
# Import the BaseTool base class from crewai.tools; all CrewAI tools must inherit from it

from pydantic import BaseModel, Field
# Import BaseModel and Field from pydantic to define the tool's input parameter model and field constraints

from src.tools.materials_project_tool import get_materials_project_tool
# Import the singleton getter for the Materials Project tool, which encapsulates calls to the Materials Project API

logging.basicConfig(level=logging.WARNING)
# Set the global log level to WARNING to reduce low-level log output and avoid interfering with normal business logs

logger = logging.getLogger(__name__)
# Get the logger instance for the current module to record errors within this module; log entries include the module name

class Name2PropertiesInput(BaseModel):
    """Name to Properties Query Tool Input Model
    Input parameter model for the name-to-properties query tool. Defines the input fields the tool accepts and their validation rules."""

    name: str = Field(..., description="Material name")
    # Material name field of type string; "..." indicates the field is required (no default value)

class Name2PropertiesTool(BaseTool):
    """Name to Properties Query Tool
    Name-to-properties query tool class. Inherits from CrewAI's BaseTool and implements querying physicochemical properties by material name."""

    name: str = "Name to Properties Query Tool"
    # The tool's name identifier, used by the CrewAI framework to reference and execute the tool

    description: str = (
        "Query key physicochemical properties by material name. "
        "Input material name, returns property information."
    )
    # Functional description of the tool, helping the LLM understand when to invoke this tool and what it does

    args_schema: type[BaseModel] = Name2PropertiesInput
    # Specifies Name2PropertiesInput as the tool's input parameter model; CrewAI validates and parses inputs accordingly

    def _run(self, name: str) -> str:
        """
        Query material properties by name.
        Core execution logic: queries physicochemical properties by material name.

        Args:
            name: Material name

        Returns:
            Material property information in JSON format
        """
        try:
            mp_tool = get_materials_project_tool()
            # Get the singleton instance of the Materials Project tool to avoid re-initializing the API connection

            search_result = mp_tool.search_materials(formula=name, limit=5, fields=["material_id", "formula_pretty"])
            # Search the Materials Project database using the material name as the search term
            # limit=5 caps the results at 5 entries; fields restricts the response to material_id and formula_pretty to save bandwidth

            if "error" in search_result:
                return json.dumps({"error": search_result["error"]}, ensure_ascii=False)
                # If the search result contains an "error" key, the API call failed; wrap the error message as JSON and return it
                # ensure_ascii=False keeps non-ASCII/special characters in the JSON unescaped instead of \uXXXX sequences

            if not search_result.get("data"):
                return json.dumps({"error": f"No material found with name {name}"}, ensure_ascii=False)
                # If the "data" field of the search result is empty or missing, no matching material was found; return an error message

            first_material = search_result["data"][0]
            # Take the first record in the search results as the best-matching material

            material_id = first_material.get("material_id")
            # Extract the Materials Project internal material ID from the first matching result

            if not material_id or material_id == "N/A":
                return json.dumps({"error": f"No valid material ID found for name {name}"}, ensure_ascii=False)
                # If the material ID is missing or "N/A", the result is invalid; return an error message

            detail_result = mp_tool.get_material_by_id(material_id)
            # Use the retrieved material ID to query the material's detailed property information

            if "error" in detail_result:
                return json.dumps({"error": detail_result["error"]}, ensure_ascii=False)
                # If the detail query returns an error, wrap it as JSON and return it as well

            properties = {
                "name": name,
                # The originally queried material name, preserved from user input for reference

                "formula": detail_result.get("formula", "N/A"),
                # The material's chemical formula; returns "N/A" if unavailable

                "material_id": detail_result.get("material_id", "N/A"),
                # The material ID in Materials Project, a globally unique identifier

                "chemsys": detail_result.get("chemsys", "N/A"),
                # Chemical system, indicating the combination of element types contained in the material

                "volume": detail_result.get("volume", "N/A"),
                # The material's unit cell volume, in Angstrom^3

                "density": detail_result.get("density", "N/A"),
                # The material's theoretical density, in g/cm^3

                "nsites": detail_result.get("nsites", "N/A"),
                # The number of atomic sites in the unit cell

                "crystal_system": detail_result.get("crystal_system", "N/A")
                # The material's crystal system (e.g., cubic, hexagonal, monoclinic, etc.)
            }

            return json.dumps(properties, ensure_ascii=False, indent=2)
            # Serialize the properties dictionary into a formatted JSON string; indent=2 makes the output more readable

        except Exception as e:
            logger.error(f"Error querying properties for name {name}: {e}")
            # Catch all exceptions and log them, including the exception details for troubleshooting

            return json.dumps({"error": f"Query error for name {name}: {str(e)}"}, ensure_ascii=False)
            # Wrap the exception information as a JSON-formatted error response and return it to the caller

# Create a singleton instance of the tool at module level, ensuring the entire application shares the same tool object
name2properties_tool = Name2PropertiesTool()

def get_name2properties_tool():
    """Get name to properties query tool instance
    Get the singleton instance of the name-to-properties query tool.
    Provides a unified access entry point; other modules obtain the same tool instance by calling this function."""
    return name2properties_tool
