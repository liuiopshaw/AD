#!/usr/bin/env python3
# Specify the Python interpreter, ensuring the script uses python3 when executed directly on Unix

"""
Material Search Tool.
Search for materials with specific properties.
"""
# Module docstring: describes the tool's functionality -- search for materials by specific properties

import json
# Import the json module to serialize search results as JSON-formatted strings

import logging
# Import the logging module to record runtime warnings and error logs

from typing import Optional, List
# Import Optional and List type annotations from typing for better readability and type checking

from crewai.tools import BaseTool
# Import the BaseTool base class from crewai.tools; all custom CrewAI tools must inherit from it

from pydantic import BaseModel, Field
# Import BaseModel and Field from pydantic to define the tool's input parameter model and field descriptions

from src.tools.materials_project_tool import get_materials_project_tool
# Import the singleton accessor for the Materials Project tool, used to query the materials database

logging.basicConfig(level=logging.WARNING)
# Configure basic logging settings: only output WARNING level and above to reduce noise

logger = logging.getLogger(__name__)
# Create a logger named after the current module for easier log source identification

class MaterialSearchInput(BaseModel):
    """Material Search Tool Input Model"""
    # Pydantic input model: defines the parameters accepted by the search tool and their constraints

    query: str = Field(..., description="Search query: material type, formula or elements")
    # Search query string; ... means required; supports material type, chemical formula, or element combination

    limit: int = Field(default=10, description="Result limit")
    # Maximum number of results to return; defaults to 10

class MaterialSearchTool(BaseTool):
    """Material Search Tool"""
    # Material search tool class, inheriting BaseTool, invoked by CrewAI agents

    name: str = "Material Search Tool"
    # Tool name; the CrewAI framework identifies and references tools by name

    description: str = (
        "Search for materials with specific properties. "
        "Search by material type, formula or element combination."
    )
    # Tool description; CrewAI agents use it to decide when to use this tool;
    # note: externally it is automatically lowercased; the Chinese part was for internal readability only

    args_schema: type[BaseModel] = MaterialSearchInput
    # Specify the tool's input parameter model; the CrewAI framework parses and validates arguments based on it

    def _run(self, query: str, limit: int = 10) -> str:
        """
        Search materials.
        # Core method that executes the material search (_run is the interface method required by CrewAI BaseTool)

        Args:
            query: Search query
            limit: Result limit

        Returns:
            JSON formatted search results
        """
        try:
            # Get the singleton instance of the Materials Project tool
            mp_tool = get_materials_project_tool()
            materials = []
            # Initialize an empty list to accumulate material data from different search strategies

            # ==================== Strategy 1: search by chemical formula ====================
            # First, try searching with the user query directly as a chemical formula
            formula_result = mp_tool.search_materials(
                formula=query,
                limit=limit,
                fields=["material_id", "formula_pretty", "chemsys", "volume", "density", "nsites"]
                # Specify the fields to return: material ID, pretty formula, chemical system, volume, density, number of sites
            )

            # If the search succeeded and returned data, add the results to the materials list
            if "error" not in formula_result and formula_result.get("data"):
                materials.extend(formula_result["data"])

            # ==================== Strategy 2: search by elements ====================
            # If the formula search returned no results, try parsing element symbols from the query and searching by elements
            if not materials:
                elements = self._parse_elements(query)
                # Extract a list of valid chemical element symbols from the query string
                if elements:
                    element_result = mp_tool.search_materials(
                        elements=elements,
                        limit=limit,
                        fields=["material_id", "formula_pretty", "chemsys", "volume", "density", "nsites"]
                    )
                    if "error" not in element_result and element_result.get("data"):
                        materials.extend(element_result["data"])

            # ==================== Strategy 3: search by hyphen-separated element combination ====================
            # If the first two strategies found nothing, try splitting the query by "-" into an element list
            if not materials:
                if "-" in query:
                    element_list = [elem.strip() for elem in query.split("-") if elem.strip()]
                    # Split by "-" and strip whitespace and empty strings
                    if element_list:
                        combo_result = mp_tool.search_materials(
                            elements=element_list,
                            limit=limit,
                            fields=["material_id", "formula_pretty", "chemsys", "volume", "density", "nsites"]
                        )
                        if "error" not in combo_result and combo_result.get("data"):
                            materials.extend(combo_result["data"])

            # ==================== No-result handling ====================
            # If all search strategies found no matching materials, return an informational message
            if not materials:
                return json.dumps({
                    "query": query,
                    "results": [],
                    "message": f"No materials found matching '{query}'"
                }, ensure_ascii=False, indent=2)
                # ensure_ascii=False ensures non-ASCII characters (e.g., special characters in chemical symbols) display correctly

            # ==================== Result truncation and formatting ====================
            materials = materials[:limit]
            # Truncate the results to the user-specified limit

            formatted_results = []
            # Iterate over each material record, extracting key fields and formatting them
            for material in materials:
                formatted_material = {
                    "material_id": material.get("material_id", "N/A"),
                    # Material ID; filled with "N/A" if missing
                    "formula": material.get("formula", "N/A"),
                    # Chemical formula
                    "chemsys": material.get("chemsys", "N/A"),
                    # Chemical system (element combination)
                    "volume": material.get("volume", "N/A"),
                    # Unit cell volume
                    "density": material.get("density", "N/A"),
                    # Density
                    "nsites": material.get("nsites", "N/A")
                    # Number of atomic sites
                }
                formatted_results.append(formatted_material)

            # Return the final search results in JSON format
            return json.dumps({
                "query": query,
                "results": formatted_results
            }, ensure_ascii=False, indent=2)

        except Exception as e:
            # Catch all exceptions, log the error, and return the error message as JSON
            logger.error(f"Error searching material '{query}': {e}")
            return json.dumps({"error": f"Search error for '{query}': {str(e)}"}, ensure_ascii=False)

    def _parse_elements(self, query: str) -> Optional[List[str]]:
        """
        Parse elements from query.
        # Parse and extract valid chemical element symbols from the query string

        Args:
            query: Query string

        Returns:
            Element list or None
            # Returns the element list, or None if no valid elements were extracted
        """
        elements = []
        import re
        # Import re inside the method so it is loaded only when needed

        # Use a regex to match an uppercase letter followed by an optional lowercase letter (typical chemical element symbol format)
        element_chars = re.findall(r'[A-Z][a-z]?', query)

        # Define the list of known valid chemical element symbols (first 54 elements, the commonly used range)
        valid_elements = ["H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
                         "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
                         "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe"]

        # Filter: keep only symbols present in the known valid element list
        for element in element_chars:
            if element in valid_elements:
                elements.append(element)

        # Return the list if elements were extracted, otherwise None (distinguishes "no elements" from "empty list")
        return elements if elements else None

# ==================== Global singleton instance ====================
# Create a singleton instance of the tool to avoid re-instantiation on every call (saves memory and initialization overhead)
material_search_tool = MaterialSearchTool()

def get_material_search_tool():
    """Get material search tool instance"""
    # Return the singleton instance of the material search tool, for use by other modules (e.g., the CrewAI wrapper layer)
    return material_search_tool
