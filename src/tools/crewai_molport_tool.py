import json
# Import the BaseTool base class from the CrewAI framework
from crewai.tools import BaseTool
# Import Pydantic data model classes for defining the tool input parameter schema
from pydantic import BaseModel, Field
# Import the singleton getter for the underlying MolPort tool
from src.tools.molport_tool import get_molport_tool
# Import the cross-agent context store for sharing query results between agents
from src.utils.context_store import ContextStore

# ============================================================================
# Input parameter model definitions
# Each CrewAI tool corresponds to a Pydantic BaseModel defining the parameters it accepts
# ============================================================================

class MolPortAvailabilityInput(BaseModel):
    """Input parameters for MolPort availability query

    Used to check whether a compound can be purchased from MolPort suppliers.
    """
    # smiles: SMILES representation of the compound, e.g. "CCO" (ethanol), "c1ccccc1" (benzene)
    smiles: str = Field(description="SMILES string of the compound")
    # similarity_threshold: similarity criterion for judging "available"
    # Default 0.95, i.e. structural similarity >= 95% is considered available
    similarity_threshold: float = Field(default=0.95, description="Similarity threshold (0-1), default 0.95")

class MolPortSearchInput(BaseModel):
    """Input parameters for MolPort structure search

    Supports multiple modes such as exact match, similarity search, and sub/superstructure search.
    """
    smiles: str = Field(description="SMILES string of the compound")
    # search_type: 1=substructure, 2=superstructure, 3=exact, 4=similarity (default), 5=perfect, 6=exact fragment
    search_type: int = Field(default=4, description="Search type: 1=substructure, 2=superstructure, 3=exact, 4=similarity (default), 5=perfect, 6=exact fragment")
    # similarity_index: only effective for similarity search (type 4)
    similarity_index: float = Field(default=0.9, description="Similarity threshold (0-1), default 0.9")
    # max_results: controls the number of returned results to avoid data overload
    max_results: int = Field(default=100, description="Maximum number of results, default 100 (upper limit 10000)")

class MolPortMoleculeInfoInput(BaseModel):
    """Input parameters for MolPort molecule info query

    Queries detailed information of a molecule via its internal MolPort ID.
    """
    # molecule_id: MolPort's unique molecule identifier
    molecule_id: str = Field(description="MolPort molecule ID (e.g. '2325020' or 'Molport-002-325-020')")


# ============================================================================
# CrewAI tool class definitions
# Each tool wraps a specific function of MolPortTool so it can be invoked by CrewAI agents
# ============================================================================

class CrewAIMolPortAvailabilityTool(BaseTool):
    """CrewAI tool: check compound commercial availability

    This tool helps the agent determine whether a compound can be purchased
    from commercial suppliers, and under what conditions (number of suppliers,
    price range, etc.).
    This is crucial for evaluating material economic feasibility and precursor availability.
    """

    # Tool name: CrewAI agents use this name to invoke the tool
    name: str = "MolPort Compound Availability Checker"
    # Tool description: the LLM uses this description to decide when to use the tool
    # The description should clearly state the tool's purpose, inputs/outputs, and behavior
    description: str = (
        "Checks the commercial availability of a compound. "
        "Queries via a SMILES string whether the compound can be purchased from suppliers. "
        "Returns availability status, matched compound IDs, stock levels, and other information. "
        "Used to evaluate material economic feasibility and precursor availability."
    )
    # Specify the data model for input parameters (a BaseModel subclass)
    args_schema: type[BaseModel] = MolPortAvailabilityInput

    def __init__(self):
        """Initialize the tool instance.

        Sets up the local in-memory cache and related configuration.
        """
        super().__init__()
        # _cache: local in-memory cache dictionary
        # Keys are cache key strings; values are (timestamp, result data) tuples
        self._cache = {}
        # _ttl_seconds: cache validity period, 3600 seconds (1 hour)
        # Availability data is relatively stable, so a longer TTL is set
        self._ttl_seconds = 3600

    def _run(self, smiles: str, similarity_threshold: float = 0.95) -> str:
        """
        Check compound commercial availability.

        Caching strategy:
        1. Check the cross-agent context cache (ContextStore) first
        2. Then check the local TTL cache
        3. Finally execute the actual query

        Args:
            smiles: compound SMILES string
            similarity_threshold: similarity threshold (0-1)

        Returns:
            Availability evaluation result as a JSON-formatted string
        """
        try:
            # Build the cache key: includes smiles and similarity threshold
            # Different similarity thresholds produce different results, so it must be part of the key
            cache_key = f"molport_availability:{smiles}:{similarity_threshold}"
            # First cache layer: cross-agent context store
            # ContextStore allows different agents to share the results of the same query
            cached_ctx = ContextStore.get(cache_key)
            if cached_ctx is not None:
                return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # Second cache layer: local TTL in-memory cache
            import time as _t
            now = _t.time()
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self._ttl_seconds:
                # Cache not expired; return the cached data directly
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # Cache miss: get the underlying tool and execute the query
            tool = get_molport_tool()
            result = tool.check_compound_availability(smiles, similarity_threshold)

            # Write the result into both cache layers (ContextStore only caches successful results; error results are not written)
            if isinstance(result, dict) and "error" not in result:
                ContextStore.set(cache_key, result)      # cross-agent cache
            self._cache[cache_key] = (now, result)   # local TTL cache

            # Return the JSON-serialized result
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            # Exception handling: return a JSON object containing the error message
            return json.dumps({"error": f"Query error: {str(e)}"}, ensure_ascii=False)


class CrewAIMolPortSearchTool(BaseTool):
    """CrewAI tool: MolPort chemical structure search

    Supports multiple search modes:
    - Exact search: find compounds with identical structures
    - Similarity search: find structurally similar compounds (most commonly used, for finding substitutes)
    - Substructure search: find compounds containing the specified substructure
    - Superstructure search: find compounds contained within the specified structure
    """

    name: str = "MolPort Chemical Structure Search"
    description: str = (
        "Searches chemical structures in the MolPort database. "
        "Supports exact match, similarity search, substructure search, etc. "
        "Searches for similar compounds via a SMILES string, returning MolPort IDs and similarity indices. "
        "Used to find similar purchasable compounds or to validate material design feasibility."
    )
    args_schema: type[BaseModel] = MolPortSearchInput

    def __init__(self):
        super().__init__()
        self._cache = {}
        self._ttl_seconds = 3600  # 1-hour cache

    def _run(
        self,
        smiles: str,
        search_type: int = 4,
        similarity_index: float = 0.9,
        max_results: int = 100
    ) -> str:
        """
        Execute a chemical structure search.

        Args:
            smiles: compound SMILES string
            search_type: search type (1-6)
            similarity_index: similarity threshold (0-1)
            max_results: maximum number of results to return

        Returns:
            Search results as a JSON-formatted string
        """
        try:
            # Build the cache key: includes all search parameters, since different parameter combinations produce different results
            cache_key = f"molport_search:{search_type}:{smiles}:{similarity_index}:{max_results}"
            # Check the cross-agent context cache first
            cached_ctx = ContextStore.get(cache_key)
            if cached_ctx is not None:
                return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # Then check the local TTL cache
            import time as _t
            now = _t.time()
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # Execute the actual query
            tool = get_molport_tool()
            result = tool.search_by_smiles(
                smiles,
                search_type=search_type,
                similarity_index=similarity_index,
                max_results=max_results
            )

            # Update both cache layers (only successful results are cached; error results are not written to the TTL-less ContextStore)
            if isinstance(result, dict) and "error" not in result:
                ContextStore.set(cache_key, result)
            self._cache[cache_key] = (now, result)

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Search error: {str(e)}"}, ensure_ascii=False)


class CrewAIMolPortMoleculeInfoTool(BaseTool):
    """CrewAI tool: get detailed MolPort molecule information

    Retrieves complete information via the MolPort molecule ID, including:
    - Molecular identity: SMILES, IUPAC name, molecular formula, molecular weight
    - Commercial information: supplier list, prices, stock, delivery time
    - Used to evaluate the commercial availability and cost of a specific compound
    """

    name: str = "MolPort Molecule Information Loader"
    description: str = (
        "Retrieves detailed information about a compound via its MolPort ID, including SMILES, IUPAC name, molecular formula, "
        "molecular weight, supplier information, stock, prices, delivery time, etc. "
        "Used to evaluate the commercial availability and cost of a specific compound."
    )
    args_schema: type[BaseModel] = MolPortMoleculeInfoInput

    def __init__(self):
        super().__init__()
        self._cache = {}
        self._ttl_seconds = 3600  # 1-hour cache: molecule information is relatively stable

    def _run(self, molecule_id: str) -> str:
        """
        Get detailed molecule information.

        Args:
            molecule_id: MolPort molecule ID (both formats supported)

        Returns:
            Detailed molecule information as a JSON-formatted string
        """
        try:
            # Build the cache key: uses only molecule_id as the identifier
            cache_key = f"molport_molecule:{molecule_id}"
            # Check the cross-agent context cache first
            cached_ctx = ContextStore.get(cache_key)
            if cached_ctx is not None:
                return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # Then check the local TTL cache
            import time as _t
            now = _t.time()
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # Execute the query: use get_availability_info to get complete commercial information
            tool = get_molport_tool()
            result = tool.get_availability_info(molecule_id)

            # Update both cache layers (only successful results are cached; error results are not written to the TTL-less ContextStore)
            if isinstance(result, dict) and "error" not in result:
                ContextStore.set(cache_key, result)
            self._cache[cache_key] = (now, result)

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Info retrieval error: {str(e)}"}, ensure_ascii=False)


# ============================================================================
# Create global tool instances
# These instances are created at module import time for CrewAI agent configuration
# ============================================================================

# Compound availability checker tool instance
molport_availability_tool = CrewAIMolPortAvailabilityTool()
# Chemical structure search tool instance
molport_search_tool = CrewAIMolPortSearchTool()
# Molecule detailed information loader tool instance
molport_molecule_info_tool = CrewAIMolPortMoleculeInfoTool()
