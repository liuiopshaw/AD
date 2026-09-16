# ---- Standard library imports ----
import json                                            # JSON serialization, used to return results to the CrewAI Agent

# ---- CrewAI framework imports ----
from typing import Optional, List                      # Python type annotations
from crewai.tools import BaseTool                      # CrewAI tool base class; all Agent tools inherit from it
from pydantic import BaseModel, Field                  # Pydantic data validation model, defining the structure of tool input parameters

# ---- Internal module imports ----
from src.tools.materials_project_tool import get_materials_project_tool  # Get the singleton of the underlying MP API tool
from src.utils.context_store import ContextStore       # Context cache shared across Agents

# ============================================================================
#  Pydantic input model — defines the parameter structure of the CrewAI tool
# ============================================================================

class MaterialsProjectToolInput(BaseModel):
    """
    Input model for the Materials Project tool.
    Pydantic Field descriptions are used by the CrewAI framework to
    automatically generate the tool's parameter documentation. When an Agent
    invokes the tool, the framework validates the input against this model.
    """
    action: str = Field(
        default="search",
        description="Action to perform ('search', 'get_material', 'get_summary')"
    )
    # Action specifies the type of operation to perform:
    # - "search": search materials by chemical formula/elements
    # - "get_material": get detailed material information by material_id
    # - "get_summary": get a summary of materials for given elements

    material_id: Optional[str] = Field(
        default=None,
        description="Material ID (for get_material action)"
    )
    # Material ID is only used when action="get_material", in the format "mp-XXXX"

    formula: Optional[str] = Field(
        default=None,
        description="Chemical formula (for search)"
    )
    # Chemical formula, e.g. "C3N4", "Fe2O3"; only used when action="search"

    elements: Optional[List[str]] = Field(
        default=None,
        description="Elements that must be included (for search/get_summary)"
    )
    # List of elements that must be included, e.g. ["Li", "Co", "O"]

    exclude_elements: Optional[List[str]] = Field(
        default=None,
        description="Elements to exclude (for search)"
    )
    # List of elements to exclude, used to filter out unwanted materials

    crystal_system: Optional[str] = Field(
        default=None,
        description="Crystal system (for search)"
    )
    # Crystal system filter, e.g. "cubic", "hexagonal"

    limit: int = Field(
        default=100,
        description="Result limit (for search/get_summary)"
    )
    # Maximum number of results returned, controlling the API call data volume

    skip: int = Field(
        default=0,
        description="Results to skip (for search)"
    )
    # Number of results to skip, used for paginated queries

    fields: Optional[List[str]] = Field(
        default=None,
        description="Data fields to include"
    )
    # Specifies the data fields to return, e.g. ["material_id", "density", "volume"]

# ============================================================================
#  CrewAI tool class — wraps the underlying API as a tool callable by Agents
# ============================================================================

class CrewAIMaterialsProjectTool(BaseTool):
    """
    CrewAI tool wrapper — exposes the Materials Project API to CrewAI Agents.
    Agents invoke it via the natural-language tool definition, and the
    framework automatically maps the parameters to the _run method.

    Key design:
    - name and description are references for the Agent's understanding and decision-making
    - args_schema specifies the structure of the input parameters; the framework performs JSON Schema validation automatically
    - _cache is an instance-level cache, complementary to the cache of the underlying MaterialsProjectTool
    - ContextStore provides a data cache shared across Agents
    """

    # Required by the CrewAI framework: name is the tool's display name, by which the Agent identifies the tool
    name: str = "Materials Project Database Access"

    # Required by the CrewAI framework: description is the tool's functional
    # description; the Agent reads this description to decide when to call the tool
    description: str = (
        "Access Materials Project database. "
        "Actions: 'search' (by formula/elements), 'get_material' (by ID), 'get_summary' (element-based summary). "
        "Usage: action='search', formula='C3N4'"
    )

    # Pydantic model defining the tool's input parameter schema
    args_schema: type[BaseModel] = MaterialsProjectToolInput

    def __init__(self):
        """
        Initialize the CrewAI Materials Project tool.
        Sets up an instance-level cache (dict + TTL), complementing the
        singleton cache of the underlying tool.
        """
        super().__init__()
        # Instance-level cache: stores (timestamp, result) tuples
        self._cache: dict = {}
        # Cache validity period: 600 seconds (10 minutes)
        self._ttl_seconds = 600

    def _sanitize_fields(self, fields: Optional[List[str]], action: str) -> Optional[List[str]]:
        """
        Field whitelist filtering — prevents API errors caused by the Agent
        requesting unsupported fields.

        Restricts allowed fields based on the action type:
        - search: allows basic fields (no nested symmetry object)
        - others (get_material, etc.): allows fields including symmetry

        Args:
            fields: list of fields requested by the user
            action: current operation type

        Returns:
            The filtered list of safe fields, or None
        """
        if not fields:
            return None
        # Fields available for search (excluding the nested symmetry object)
        allowed_search = {"material_id", "formula_pretty", "chemsys", "volume", "density", "nsites"}
        # Fields available for detail queries (adds symmetry)
        allowed_detail = allowed_search | {"symmetry"}
        if action == "search":
            # Keep only whitelisted fields for search
            return [f for f in fields if f in allowed_search]
        # Non-search operations use the wider whitelist
        return [f for f in fields if f in allowed_detail]

    def _run(
        self,
        action: str = "search",
        material_id: Optional[str] = None,
        formula: Optional[str] = None,
        elements: Optional[List[str]] = None,
        exclude_elements: Optional[List[str]] = None,
        crystal_system: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
        fields: Optional[List[str]] = None
    ) -> str:
        """
        Execute a Materials Project API operation — the core invocation entry
        point of the CrewAI framework.

        The CrewAI framework automatically maps the Agent's request to the
        parameters of the _run method, which processes it and returns a JSON
        string to the Agent.

        Caching strategy (multi-layer):
        1. ContextStore (shared across Agents): check the global cache first
        2. Instance-level _cache: then check the instance cache
        3. Underlying API call: finally call the underlying tool's cache/API

        Args:
            action: operation type ("search", "get_material", "get_summary")
            material_id: material ID (used by the get_material operation)
            formula: chemical formula (used by the search operation)
            elements: list of required elements (used by search/get_summary operations)
            exclude_elements: list of excluded elements (used by the search operation)
            crystal_system: crystal system (used by the search operation)
            limit: result count limit
            skip: number of results to skip
            fields: data fields to return

        Returns:
            JSON-formatted API response string (read directly by the Agent)
        """
        try:
            # ---- Get the underlying MaterialsProjectTool singleton ----
            tool = get_materials_project_tool()

            # ---- Build the cache key ----
            # The cache key contains all query parameters, ensuring that caches
            # of different queries do not interfere with each other
            key = (
                action,
                material_id or "",
                formula or "",
                tuple(elements) if elements else (),
                tuple(exclude_elements) if exclude_elements else (),
                crystal_system or "",
                int(limit or 0),
                int(skip or 0),
                tuple(fields) if fields else ()
            )

            import time as _t
            now = _t.time()

            # ---- First cache layer: ContextStore (cache shared across Agents) ----
            # The cache key carries the query conditions (formula / material_id), ensuring that:
            # - Results can be reused among multiple evaluation Agents for the same material (same key)
            # - Queries for different materials never hit each other's cache, avoiding cross-material data leakage
            if action == "search":
                # Check the cache by the specific chemical formula (no generalized key,
                # to avoid hitting query results of other materials)
                if formula:
                    cached_ctx = ContextStore.get(f"materials_project_search:{formula}")
                    if cached_ctx is not None:
                        return json.dumps(cached_ctx, ensure_ascii=False, indent=2)
            elif action == "get_material" and material_id:
                # Check the cache by material_id
                cached_ctx = ContextStore.get(f"materials_project_get:{material_id}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # ---- Second cache layer: instance-level cache ----
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # ---- Execute the corresponding underlying operation based on the action type ----
            if action == "search":
                # Apply safe filtering to the fields
                fields = self._sanitize_fields(fields, action)
                # When querying by elements, cap limit at 10 to avoid pulling too much data
                if elements and (limit is None or limit > 10):
                    limit = 10
                result = tool.search_materials(
                    formula=formula,
                    elements=elements,
                    exclude_elements=exclude_elements,
                    crystal_system=crystal_system,
                    limit=min(limit or 100, 10),  # upper limit 10, controlling data volume
                    skip=skip,
                    fields=fields
                )
            elif action == "get_material":
                # An ID must be provided when fetching details by material_id
                if not material_id:
                    return json.dumps({"error": "material_id required for get_material action"})
                fields = self._sanitize_fields(fields, action)
                result = tool.get_material_by_id(material_id)
                # Store in ContextStore for reuse by other Agents (only successful
                # results are cached; error results are not put into the permanent cache)
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"materials_project_get:{material_id}", result)
            elif action == "get_summary":
                # Get material summary information
                result = tool.get_materials_summary(
                    elements=elements,
                    limit=min(limit or 100, 100)  # ensure limit does not exceed 100
                )
            else:
                # Unsupported operation type; return an error message
                return json.dumps({"error": f"Unsupported action: {action}"})

            # ---- Update caches and return the result ----
            # Update the instance-level cache
            self._cache[key] = (now, result)
            # Update ContextStore (shared across Agents)
            # Only successful results are cached under the formula key: error results
            # (containing "error") are not written to the permanent cache, and no
            # generalized key is used, avoiding cross-contamination between query
            # results of different materials
            if action == "search" and isinstance(result, dict) and "error" not in result:
                if formula:
                    ContextStore.set(f"materials_project_search:{formula}", result)
            # Return the JSON string (the CrewAI framework requires _run to return str)
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            # Exception fallback: return formatted error information as JSON
            return json.dumps({"error": f"Operation error: {str(e)}"}, ensure_ascii=False)

# ============================================================================
#  Module-level tool instance — for direct import by the tool factory
# ============================================================================

# Create the globally unique CrewAIMaterialsProjectTool instance
# This instance is directly referenced by ToolFactory in factory.py
materials_project_tool = CrewAIMaterialsProjectTool()
