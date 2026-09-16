# ---- Standard library imports ----
import json                                            # JSON serialization, converts query results into Agent-readable strings

# ---- CrewAI framework imports ----
from crewai.tools import BaseTool                      # CrewAI tool base class
from pydantic import BaseModel, Field                  # Pydantic data validation models, defining the tool's input parameter structure

# ---- Internal module imports ----
from src.tools.pubchem_tool import get_pubchem_tool   # Get the underlying PubChemTool singleton
from src.utils.context_store import ContextStore       # Context cache store shared across Agents

# ============================================================================
#  Pydantic input model — defines the parameter structure of the CrewAI tool
# ============================================================================

class PubChemToolInput(BaseModel):
    """
    Input model for the PubChem tool.
    The CrewAI framework automatically generates Agent-readable parameter
    descriptions from each Field's description, and automatically maps the
    Agent's invocation requests to the parameters of the _run method.
    """

    query: str = Field(
        description="Query content (chemical name, formula or InChIKey)"
    )
    # query is a required field — the identifier of the chemical substance to query.
    # Three formats are supported: compound name (e.g. "caffeine"), molecular formula (e.g. "C8H10N4O2"), InChIKey

    search_type: str = Field(
        default="auto",
        description="Query type ('auto', 'name', 'formula', 'inchikey')"
    )
    # search_type controls how the query is routed:
    # - "auto": automatically detect the query format and choose the appropriate endpoint (recommended)
    # - "name": force query by compound name
    # - "formula": force query by molecular formula (uses the fastformula endpoint)
    # - "inchikey": force query by InChIKey

    get_cas: bool = Field(
        default=True,
        description="Whether to get CAS number"
    )
    # When get_cas=True, calls get_compound_info_with_cas to extract the CAS number from synonyms
    # Note: get_full_info takes precedence over get_cas

    get_full_info: bool = Field(
        default=False,
        description="Whether to get full compound info"
    )
    # When get_full_info=True, calls get_compound_info, returning the most complete set of properties
    # including SMILES, InChI, XLogP, TPSA and all other computed properties

# ============================================================================
#  CrewAI tool class — wraps the PubChem API as an Agent-callable tool
# ============================================================================

class CrewAIPubChemTool(BaseTool):
    """
    CrewAI tool wrapper — exposes the PubChem REST API to CrewAI Agents.

    Design highlights:
    - name and description are descriptive texts the Agent uses to understand the tool's functionality
    - args_schema defines the parameter structure the tool accepts; the framework validates it automatically
    - the _run method is the core execution entry point and returns a JSON string
    - Cache strategy: ContextStore (cross-Agent) > instance-level _cache > underlying API

    Use cases:
    - Verify chemical information: query compound properties such as molecular weight and formula
    - Retrieve safety data: query compound toxicity and physicochemical properties
    - Extract CAS numbers: extract standard CAS identifiers from synonym lists
    """

    # Required by the CrewAI framework: name lets the Agent identify the tool
    name: str = "PubChem Database Query"

    # Required by the CrewAI framework: description describes the tool's functionality and usage
    # The Agent uses this description to decide whether to invoke the tool
    description: str = (
        "Query PubChem chemical database to get compound information. "
        "Search compounds by name, formula or InChIKey. "
        "Get CAS number, molecular weight, SMILES, InChI and other properties. "
        "Use when you need to verify chemical info or get compound details."
    )

    # Pydantic input parameter model; the CrewAI framework generates a JSON Schema from it and validates inputs
    args_schema: type[BaseModel] = PubChemToolInput

    def __init__(self):
        """
        Initialize the CrewAI PubChem tool.
        Creates an instance-level cache, forming a three-tier caching system together
        with the underlying PubChemTool cache and the ContextStore.
        """
        super().__init__()
        # Instance-level cache dict: key -> (timestamp, result) tuple
        self._cache = {}
        # Cache time-to-live: 600 seconds (10 minutes); re-query after expiry
        self._ttl_seconds = 600

    def _run(
        self,
        query: str,
        search_type: str = "auto",
        get_cas: bool = True,
        get_full_info: bool = False
    ) -> str:
        """
        Execute a PubChem database query — the core invocation entry point of the CrewAI framework.

        The CrewAI framework automatically maps the Agent's request to the parameters of the _run method.

        Cache strategy (three tiers, fastest to slowest):
        1. ContextStore (global cross-Agent cache): looked up by query type + content
        2. Instance-level _cache: looked up by the full parameter combination
        3. Underlying PubChemTool API call: fetches real data via HTTP requests

        Query priority logic:
        - If get_full_info=True: calls get_compound_info (most complete properties)
        - Else if get_cas=True (default): calls get_compound_info_with_cas (includes CAS number)
        - Else: calls search_compound (basic query)

        Args:
            query: Query content (compound name, molecular formula or InChIKey)
            search_type: Query type ("auto", "name", "formula", "inchikey")
            get_cas: Whether to get the CAS number (default True)
            get_full_info: Whether to get full compound information (default False)

        Returns:
            JSON-formatted query result string (parsed and read directly by the Agent)
        """
        try:
            # ---- Build the cache key ----
            # The cache key includes all parameters that affect the query result
            key = (query, search_type, bool(get_cas), bool(get_full_info))

            import time as _t
            now = _t.time()

            # ---- First cache tier: ContextStore (global cache shared across Agents) ----
            # Use different cache namespaces by query type to avoid cross-contamination between cache types
            if get_full_info:
                # Full-info query cache, key format: pubchem_full:<query>
                cached_ctx = ContextStore.get(f"pubchem_full:{query}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)
            elif get_cas:
                # CAS-number query cache, key format: pubchem_cas:<query>
                cached_ctx = ContextStore.get(f"pubchem_cas:{query}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)
            else:
                # Basic search cache, key format: pubchem_search:<type>:<query>
                # Here type is search_type ("auto"/"name"/"formula"/"inchikey")
                cached_ctx = ContextStore.get(f"pubchem_search:{search_type}:{query}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # ---- Second cache tier: instance-level cache ----
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # ---- Third tier: call the underlying PubChemTool API ----
            # Get the PubChemTool singleton instance
            tool = get_pubchem_tool()

            # Only write successful results into ContextStore (a permanent cache without TTL):
            # failed results containing "error" are not cached, to prevent error results
            # from being permanently reused by subsequent queries
            if get_full_info:
                # Get the most complete compound information (including all computed properties)
                result = tool.get_compound_info(query)
                # Update the global cache
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pubchem_full:{query}", result)
            elif get_cas:
                # Get compound information including the CAS number
                result = tool.get_compound_info_with_cas(query)
                # Update the global cache
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pubchem_cas:{query}", result)
            else:
                # Basic search (uses smart routing to automatically determine the query type)
                result = tool.search_compound(query, search_type)
                # Update the global cache
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pubchem_search:{search_type}:{query}", result)

            # ---- Update the instance-level cache ----
            self._cache[key] = (now, result)

            # ---- Return the JSON string ----
            # The CrewAI framework requires the _run method to return a string
            # ensure_ascii=False allows Unicode characters such as Chinese to be output directly
            # indent=2 makes the output more readable
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            # Exception fallback: return a formatted error JSON string
            # ensure_ascii=False: allows non-ASCII characters to be output natively
            return json.dumps({"error": f"Query error: {str(e)}"}, ensure_ascii=False)

# ============================================================================
#  Module-level tool instance — imported directly by the tool factory
# ============================================================================

# Create the globally unique CrewAIPubChemTool instance
# This instance is referenced directly by ToolFactory in factory.py
pubchem_tool = CrewAIPubChemTool()
