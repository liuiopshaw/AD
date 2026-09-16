import json
# Import the BaseTool base class from the CrewAI framework; all CrewAI tools must inherit from it
from crewai.tools import BaseTool
# Import Pydantic's data model class, used to define the tool's input parameter structure
# BaseModel provides automatic validation and type checking; Field adds parameter descriptions and default values
from pydantic import BaseModel, Field
# Import the singleton getter for the underlying PNEC query tool
from src.tools.pnec_tool import get_pnec_tool
# Import the context store, used to share query results between Agents (cross-Agent cache)
from src.utils.context_store import ContextStore

class PNECToolInput(BaseModel):
    """PNEC Tool Input Model

    Defines the input parameter model for the CrewAI PNEC tool.
    Using Pydantic BaseModel provides automatic parameter validation, type checking, and default values.
    The CrewAI framework automatically generates the parameter schema for tool calls from this model.
    """
    # query: the query content, which can be a CAS number (e.g. "7440-02-0") or a compound name (e.g. "Nickel")
    query: str = Field(description="Query content (CAS number or compound name)")
    # query_type: the query type, defaults to "name"; set to "cas" to query by CAS number
    query_type: str = Field(default="name", description="Query type ('name' or 'cas')")

class CrewAIPNECTool(BaseTool):
    """CrewAI tool wrapper for PNEC data query

    Wraps the underlying PNECTool as a tool usable by the CrewAI framework.
    Inheriting from BaseTool allows it to be automatically discovered and invoked by CrewAI Agents.
    Includes a two-layer caching mechanism: a cross-Agent context cache and a local TTL cache.
    """

    # Tool name: used when referencing this tool in a CrewAI Agent's task description
    name: str = "PNEC Database Query"
    # Tool description: helps the LLM understand when and how to use this tool
    # This is a key piece of hint information; the LLM decides whether to call this tool based on the description
    description: str = (
        "Query Predicted No-Effect Concentration (PNEC) data for environmental risk assessment. "
        "Look up PNEC values by CAS number or compound name. "
        "Use this tool when evaluating the environmental safety of a chemical. "
        "Note: only real reference data is provided (such as built-in literature values for metal toxicity); "
        "for compounds without real data, it explicitly returns data_available=false and never gives estimated values."
    )
    # args_schema: specifies the tool's input parameter structure
    # CrewAI uses this schema to validate inputs and perform type conversion before calling _run
    args_schema: type[BaseModel] = PNECToolInput

    def __init__(self):
        """Initialize the CrewAI PNEC tool.

        Calls the parent BaseTool's initialization method,
        and sets up the local in-memory cache and TTL (time-to-live) configuration.
        """
        super().__init__()
        # _cache: local in-memory cache dictionary
        # Keys are (query type, query content) tuples; values are (timestamp, result) tuples
        self._cache = {}
        # _ttl_seconds: cache time-to-live (seconds)
        # Cached data automatically expires after 600 seconds (10 minutes), ensuring data does not become stale
        self._ttl_seconds = 600

    def _run(self, query: str, query_type: str = "name") -> str:
        """
        Execute PNEC data query.
        Executes the PNEC data query. The CrewAI framework calls this method automatically.

        Caching strategy (fastest to slowest):
        1. First check the cross-Agent context cache (ContextStore): shares data across multiple Agents
        2. Then check the local TTL cache (_cache): avoids repeated requests to the PubChem API
        3. Only then actually execute the query

        Args:
            query: the query content (CAS number or compound name)
            query_type: the query type ("name" or "cas")

        Returns:
            Query result string in JSON format
            CrewAI tools must return a string, so the dictionary is serialized to JSON here
        """
        try:
            # Build the cache key: a combination of query type and query content
            # e.g. ("cas", "7440-02-0") or ("name", "Nickel")
            key = (query_type.lower(), query)
            # Get the current timestamp, used to determine whether the local cache has expired
            import time as _t
            now = _t.time()

            # First cache layer: try to get from the cross-Agent context store
            # ContextStore can share data between different Agents, avoiding duplicate queries
            if query_type.lower() == "cas":
                cached_ctx = ContextStore.get(f"pnec:cas:{query}")
                if cached_ctx is not None:
                    # Cache hit, return directly (without re-requesting the PubChem API)
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)
            else:
                cached_ctx = ContextStore.get(f"pnec:name:{query}")
                if cached_ctx is not None:
                    return json.dumps(cached_ctx, ensure_ascii=False, indent=2)

            # Second cache layer: try to get from the local TTL cache
            # A time-based TTL strategy is used here; cache entries older than _ttl_seconds are considered expired
            cached = self._cache.get(key)
            if cached and now - cached[0] < self._ttl_seconds:
                return json.dumps(cached[1], ensure_ascii=False, indent=2)

            # Cache miss: get the underlying tool instance and execute the actual query
            tool = get_pnec_tool()

            # Call the corresponding underlying method based on the query type
            # Only successful results are written to the cross-Agent context cache (no TTL); error results are not cached,
            # to prevent a single failed query from being permanently reused by all subsequent Agents
            if query_type.lower() == "cas":
                result = tool.get_pnec_by_cas(query)
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pnec:cas:{query}", result)
            else:
                result = tool.get_pnec_by_name(query)
                if isinstance(result, dict) and "error" not in result:
                    ContextStore.set(f"pnec:name:{query}", result)

            # Also write to the local TTL cache (timestamp + result tuple)
            self._cache[key] = (now, result)
            # Serialize the result to a JSON string for return
            # ensure_ascii=False preserves non-ASCII characters; indent=2 makes the output readable
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            # Exception handling: return JSON containing the error message, preventing a tool crash from failing the Agent
            return json.dumps({"error": f"Query error: {str(e)}"}, ensure_ascii=False)
