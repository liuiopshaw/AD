#!/usr/bin/env python3
"""
Materials Project API Tool.
Provides access to Materials Project materials database.
Uses official mp-api client.

Materials Project API tool — provides access to the Materials Project materials
database (inorganic materials). Queries are performed via the official mp-api client.
"""

import os
import logging
import time
from typing import Dict, List, Optional, Any

# ---- Logging configuration ----
# Set the log level to WARNING to reduce log noise during normal queries
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ---- Global rate limiting ----
# To prevent overly frequent API calls from triggering rate limits, use a global
# variable to record the time of the last call
_last_call_time = 0                 # Timestamp of the last API call (Unix time)
_call_interval = 2.0               # Call interval: raised to 2 seconds to avoid triggering rate limits with frequent calls
_max_retries = 3                   # Maximum number of retries per operation

# ---- Optional dependency check ----
# mp-api is not a required dependency; mark it unavailable if not installed
try:
    from mp_api.client import MPRester
    MP_API_AVAILABLE = True
except ImportError:
    # mp-api client not installed; the Materials Project tool will be unavailable
    MP_API_AVAILABLE = False
    logger.warning("mp-api client not installed, Materials Project tool will be unavailable")

class MaterialsProjectTool:
    """Materials Project API tool class.

    Supports querying and validating the following categories of inorganic materials:
    1. Pure metal materials
    2. Metal oxides
    3. Metal sulfides
    4. Metal nitrides/carbides
    5. MOF/COF materials (Metal-Organic Frameworks / Covalent Organic Frameworks)
    6. Other inorganic compounds
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Materials Project tool.

        Args:
            api_key (str, optional): Materials Project API key.
                                     If not provided, it is read from the environment
                                     variable MATERIALS_PROJECT_API_KEY.

        Raises:
            ImportError: If the mp-api client is not installed
            ValueError: If the API key is not set
        """
        # Check whether the mp-api dependency is installed
        if not MP_API_AVAILABLE:
            raise ImportError("mp-api client not installed, please run 'pip install mp-api'")

        # Get the API key: prefer the passed-in key, otherwise read from the environment variable
        self.api_key = api_key or os.getenv('MATERIALS_PROJECT_API_KEY')
        if not self.api_key:
            raise ValueError("Materials Project API key not set")

        # Initialize the MPRester client — the core object for communicating with the Materials Project API
        self.mpr = MPRester(self.api_key)

        # ---- Local cache system ----
        # To avoid repeated API calls, use an in-memory dict to cache query results.
        # The cache is bucketed by query type; each bucket stores a {key: value} mapping.
        # The TTL (Time-To-Live) is 600 seconds (10 minutes); entries are re-queried after expiry.
        self._cache = {
            "search": {},        # Cache of search results (exact match on limit/skip/fields)
            "search_norm": {},   # Normalized cache of search results (ignores limit/skip, used for subset slicing)
            "by_id": {},         # Cache of by-ID queries
            "verify": {}         # Cache of ID verification results
        }
        self._ttl_seconds = 600  # Cache validity period: 600 seconds

    def search_materials(self,
                        formula: Optional[str] = None,
                        elements: Optional[List[str]] = None,
                        exclude_elements: Optional[List[str]] = None,
                        crystal_system: Optional[str] = None,
                        limit: int = 100,
                        skip: int = 0,
                        fields: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Search materials — the most comprehensive materials query entry point.

        Supports combined multi-condition queries: chemical formula, included elements,
        excluded elements, crystal system, etc.

        Args:
            formula (str, optional): Chemical formula, e.g. "C3N4"
            elements (List[str], optional): List of elements that must be present, e.g. ["Fe", "O"]
            exclude_elements (List[str], optional): List of elements that must be excluded
            crystal_system (str, optional): Crystal system, e.g. "cubic"
            limit (int): Maximum number of results to return, default 100
            skip (int): Number of results to skip, used for pagination
            fields (List[str], optional): List of data fields to return

        Returns:
            Dict: Search result dictionary containing data (list of materials) and meta (metadata)
        """
        try:
            # ---- Rate limiting + retry mechanism ----
            global _last_call_time, _call_interval, _max_retries
            retries = 0

            while retries < _max_retries:
                try:
                    # If too little time has passed since the last call, wait until the interval is satisfied
                    current_time = time.time()
                    time_since_last_call = current_time - _last_call_time
                    if time_since_last_call < _call_interval:
                        time.sleep(_call_interval - time_since_last_call)
                    _last_call_time = time.time()  # Update the call time

                    # ---- Build search parameters ----
                    # MPRester.materials.search accepts filter conditions as keyword arguments
                    kwargs = {}

                    if formula:
                        kwargs["formula"] = formula
                    if elements:
                        kwargs["elements"] = elements
                    if exclude_elements:
                        kwargs["exclude_elements"] = exclude_elements
                    if crystal_system:
                        kwargs["crystal_system"] = crystal_system

                    # chunk_size: the size of each data chunk pulled from the API.
                    # If querying by elements, limit it to 50 (potentially large result sets); otherwise cap at 100
                    chunk_size = min(limit, 50) if elements else min(limit, 100)

                    # ---- Default returned fields ----
                    # Request only the necessary fields to save bandwidth and API call time
                    default_fields = [
                        "material_id",        # Unique material identifier, e.g. "mp-1234"
                        "formula_pretty"      # Prettified chemical formula, e.g. with subscript formatting
                    ]
                    fields = fields or default_fields

                    # ---- Build the normalized cache key ----
                    # The normalized cache key excludes limit/skip/fields, so results for the
                    # same conditions can be reused across queries
                    normalized_key = (
                        formula or "",
                        tuple(elements) if elements else (),
                        tuple(exclude_elements) if exclude_elements else (),
                        crystal_system or ""
                    )

                    # ---- Check the normalized cache ----
                    # On a hit, slice the cache by skip/limit and return, avoiding a duplicate API call
                    norm_entry = self._cache["search_norm"].get(normalized_key)
                    now = time.time()
                    if norm_entry and now - norm_entry["timestamp"] < self._ttl_seconds:
                        cached_materials = norm_entry["materials"]
                        cached_fields_set = norm_entry.get("fields_set", set())
                        requested_fields_set = set(fields)
                        # Reuse only if the cache contains all requested fields and enough
                        # cached data to cover the requested skip+limit
                        if requested_fields_set.issubset(cached_fields_set) and len(cached_materials) >= (skip + limit):
                            slice_materials = cached_materials[skip:skip+limit]
                            # Return only the requested fields (but always keep material_id and formula as identifiers)
                            subset_list = []
                            for m in slice_materials:
                                subset = {k: v for k, v in m.items() if k in requested_fields_set or k in {"material_id", "formula"}}
                                # Ensure the formula field exists (for compatibility with legacy data)
                                if "formula" not in subset and "formula" in m:
                                    subset["formula"] = m.get("formula")
                                subset_list.append(subset)
                            return {
                                "data": subset_list,
                                "meta": {
                                    "total_count": len(subset_list),
                                    "limit": limit
                                }
                            }

                    # ---- Build the exact cache key ----
                    # Cache key containing the full query parameters (including limit/skip/fields)
                    cache_key = (
                        formula or "",
                        tuple(elements) if elements else (),
                        tuple(exclude_elements) if exclude_elements else (),
                        crystal_system or "",
                        limit,
                        skip,
                        tuple(fields)
                    )
                    now = time.time()
                    cached = self._cache["search"].get(cache_key)
                    # The exact cache stores a (timestamp, result) tuple
                    if cached and now - cached[0] < self._ttl_seconds:
                        return cached[1]

                    # ---- Execute the search ----
                    # Call the mp-api materials.search method
                    docs = self.mpr.materials.search(
                        **kwargs,
                        num_chunks=1,         # Request only 1 data chunk
                        chunk_size=chunk_size,
                        fields=fields
                    )

                    # Manually limit the number of returned results (mp-api may return more than limit)
                    if len(docs) > limit:
                        docs = docs[:limit]

                    # Manually apply the skip parameter, skipping the first skip results
                    if skip > 0:
                        docs = docs[skip:]

                    # ---- Convert the document objects returned by the API into dict format ----
                    # Safe getattr access avoids errors when attributes are missing
                    materials_data = []
                    for doc in docs:
                        material_dict = {
                            "material_id": str(getattr(doc, "material_id", "N/A")),
                            "formula": getattr(doc, "formula_pretty", getattr(doc, "formula", "N/A")),
                            "chemsys": getattr(doc, "chemsys", "N/A")
                        }
                        # If the volume field was requested, append the unit A^3
                        if "volume" in fields:
                            volume_value = getattr(doc, "volume", "N/A")
                            material_dict["volume"] = f"{volume_value} A^3" if volume_value != "N/A" else "N/A"
                        # If the density field was requested, append the unit g/cm^3
                        if "density" in fields:
                            density_value = getattr(doc, "density", "N/A")
                            material_dict["density"] = f"{density_value} g/cm^3" if density_value != "N/A" else "N/A"
                        # If the nsites field was requested (number of atomic sites in the unit cell)
                        if "nsites" in fields:
                            material_dict["nsites"] = getattr(doc, "nsites", "N/A")
                        materials_data.append(material_dict)

                    # Build the standard return format
                    result = {
                        "data": materials_data,
                        "meta": {
                            "total_count": len(materials_data),
                            "limit": limit
                        }
                    }

                    # ---- Update the exact cache ----
                    self._cache["search"][cache_key] = (time.time(), result)

                    # ---- Update the normalized cache ----
                    # The normalized cache keeps a larger result list so that later requests
                    # with different limit/skip values can reuse it
                    prev = self._cache["search_norm"].get(normalized_key)
                    merged_list = materials_data
                    # Collect all field names present in the current results
                    fields_set = set()
                    for item in merged_list:
                        fields_set.update(item.keys())
                    if prev and now - prev["timestamp"] < self._ttl_seconds:
                        # If a cache entry already exists with more results, keep the larger result set
                        if len(prev["materials"]) > len(merged_list):
                            merged_list = prev["materials"]
                            fields_set.update(prev.get("fields_set", set()))
                    self._cache["search_norm"][normalized_key] = {
                        "timestamp": time.time(),
                        "materials": merged_list,
                        "fields_set": fields_set
                    }
                    return result

                except Exception as e:
                    # ---- Retry logic ----
                    retries += 1
                    if retries >= _max_retries:
                        # Maximum retries reached; log the error and return an error message
                        logger.error(f"Error searching materials: {e}")
                        return {"error": f"Error searching materials: {str(e)}"}
                    else:
                        # Maximum retries not reached; log a warning, then wait with exponential backoff
                        logger.warning(f"Error searching materials, retrying ({retries}/{_max_retries}): {e}")
                        time.sleep(_call_interval * retries)  # Exponential backoff: the Nth retry waits N * interval seconds

        except Exception as e:
            # Outermost exception handler, ensuring the program does not crash on unexpected exceptions
            logger.error(f"Error searching materials: {e}")
            return {"error": f"Error searching materials: {str(e)}"}

    def get_material_by_id(self, material_id: str) -> Dict[str, Any]:
        """
        Get detailed information by material ID.

        Typical usage: first obtain a list of material_id values via search_materials,
        then call this method to get detailed properties of a specific material
        (volume, density, crystal symmetry, etc.).

        Args:
            material_id (str): Unique material identifier, in a format like "mp-1234"

        Returns:
            Dict: Material details dictionary containing material_id, formula, chemsys,
                  volume, density, nsites, crystal_system, and other fields
        """
        try:
            # ---- Validate the basic format of material_id ----
            if not material_id or material_id == "N/A" or material_id == "":
                return {"error": f"Invalid material ID: {material_id}"}

            # ---- Rate limiting + retry mechanism ----
            global _last_call_time, _call_interval, _max_retries
            retries = 0

            while retries < _max_retries:
                try:
                    # Check the by_id cache first
                    now = time.time()
                    cached = self._cache["by_id"].get(material_id)
                    if cached and now - cached[0] < self._ttl_seconds:
                        return cached[1]

                    # Rate-limiting wait
                    current_time = time.time()
                    time_since_last_call = current_time - _last_call_time
                    if time_since_last_call < _call_interval:
                        time.sleep(_call_interval - time_since_last_call)
                    _last_call_time = time.time()

                    # ---- Define the required fields ----
                    # Request only the needed fields to reduce API load
                    fields = [
                        "material_id",
                        "formula_pretty",
                        "chemsys",
                        "volume",      # Unit cell volume
                        "density",     # Density
                        "nsites",      # Number of atomic sites
                        "symmetry"     # Symmetry information (includes crystal_system)
                    ]

                    # Exact query by material_ids
                    docs = self.mpr.materials.search(material_ids=[material_id], fields=fields)

                    # Return an error when there are no results
                    if not docs:
                        return {"error": f"Material ID not found: {material_id}"}

                    doc = docs[0]

                    # ---- Verify that the returned material_id matches ----
                    # Guards against the API returning the wrong material
                    retrieved_material_id = str(getattr(doc, "material_id", ""))
                    if retrieved_material_id != material_id:
                        return {"error": f"Material ID mismatch: queried {material_id}, got {retrieved_material_id}"}

                    # ---- Safe attribute access helper functions ----
                    def safe_getattr(obj, attr, default="N/A"):
                        """Safely get an attribute value, ensuring the result is JSON serializable.
                        Handles None, empty strings, and other edge cases."""
                        try:
                            value = getattr(obj, attr, default)
                            if value is None or value == "":
                                return default
                            # Convert to string to ensure JSON serializability
                            return str(value)
                        except Exception:
                            return default

                    def safe_get_nested_attr(obj, attr_chain, default="N/A"):
                        """Safely get a nested attribute value.
                        Example: safe_get_nested_attr(doc, ["symmetry", "crystal_system"])"""
                        try:
                            current = obj
                            for attr in attr_chain:
                                if current is None:
                                    return default
                                current = getattr(current, attr, None)
                            if current is None or current == "":
                                return default
                            return str(current)
                        except Exception:
                            return default

                    # ---- Extract material properties and append units ----
                    # Volume gets the Angstrom^3 unit appended
                    volume_value = safe_getattr(doc, "volume", "N/A")
                    volume_with_unit = f"{volume_value} A^3" if volume_value != "N/A" else "N/A"

                    # Density gets the g/cm^3 unit appended
                    density_value = safe_getattr(doc, "density", "N/A")
                    density_with_unit = f"{density_value} g/cm^3" if density_value != "N/A" else "N/A"

                    # Extract crystal_system from the nested symmetry object
                    crystal_system_value = safe_get_nested_attr(doc, ["symmetry", "crystal_system"], "N/A")

                    # ---- Build the material info dictionary ----
                    material_info = {
                        "material_id": safe_getattr(doc, "material_id", "N/A"),
                        "formula": safe_getattr(doc, "formula_pretty", safe_getattr(doc, "formula", "N/A")),
                        "chemsys": safe_getattr(doc, "chemsys", "N/A"),
                        "volume": volume_with_unit,
                        "density": density_with_unit,
                        "nsites": safe_getattr(doc, "nsites", "N/A"),
                        "crystal_system": crystal_system_value,
                        "validated": True,               # Marked as validated via the MP API
                        "validation_time": time.time()   # Record the validation timestamp
                    }

                    # Update the cache
                    self._cache["by_id"][material_id] = (time.time(), material_info)
                    return material_info

                except Exception as e:
                    # ---- Retry logic ----
                    retries += 1
                    if retries >= _max_retries:
                        logger.error(f"Error getting material details: {e}")
                        return {"error": f"Error getting material details: {str(e)}"}
                    else:
                        logger.warning(f"Error getting material details, retrying ({retries}/{_max_retries}): {e}")
                        time.sleep(_call_interval * retries)  # Exponential backoff

        except Exception as e:
            logger.error(f"Error getting material details: {e}")
            return {"error": f"Error getting material details: {str(e)}"}

    def validate_material_id(self, material_id: Any) -> bool:
        """
        Validate whether the material ID format is valid (format check only, no API call).

        A valid material_id format:
        - Non-empty
        - Not "N/A"
        - Starts with the "mp-" prefix
        - Longer than 3 characters (contains at least 1 valid digit character)

        Args:
            material_id: The material ID to validate

        Returns:
            bool: Whether the format is valid
        """
        try:
            # Exclude empty values and placeholders
            if material_id is None or material_id == "" or material_id == "N/A":
                return False
            material_id_str = str(material_id)
            # Must start with "mp-" and be longer than 3 characters
            return material_id_str.startswith("mp-") and len(material_id_str) > 3
        except (ValueError, TypeError):
            return False

    def verify_material_id_exists(self, material_id: str) -> bool:
        """
        Verify whether a material_id actually exists in the Materials Project database (via API query).

        Checks the local caches (by_id and verify caches) first; on a miss, queries the
        Materials Project API by ID to confirm existence.

        Args:
            material_id (str): The material ID to verify

        Returns:
            bool: Whether the ID exists in the MP database
        """
        try:
            # Perform the basic format check first
            if not self.validate_material_id(material_id):
                return False

            # ---- Cache check ----
            global _last_call_time, _call_interval
            now = time.time()
            # Check the by_id cache first: if detailed info for this material already
            # exists without an error, the ID exists
            cached_by_id = self._cache["by_id"].get(material_id)
            if cached_by_id and now - cached_by_id[0] < self._ttl_seconds and isinstance(cached_by_id[1], dict) and not cached_by_id[1].get("error"):
                return True
            # Check the dedicated verify cache
            cached_verify = self._cache["verify"].get(material_id)
            if cached_verify and now - cached_verify[0] < self._ttl_seconds:
                return cached_verify[1]

            # ---- Rate-limiting wait ----
            current_time = time.time()
            time_since_last_call = current_time - _last_call_time
            if time_since_last_call < _call_interval:
                time.sleep(_call_interval - time_since_last_call)
            _last_call_time = time.time()

            # ---- API verification: request only the material_id field to minimize data volume ----
            docs = self.mpr.materials.search(material_ids=[material_id], fields=["material_id"])

            # If results are returned and the material_id matches, the ID exists
            if docs and len(docs) > 0:
                retrieved_material_id = str(getattr(docs[0], "material_id", ""))
                result = retrieved_material_id == material_id
                self._cache["verify"][material_id] = (time.time(), result)
                return result

            # No results; cache False
            self._cache["verify"][material_id] = (time.time(), False)
            return False
        except Exception as e:
            logger.warning(f"Error verifying material ID: {e}")
            return False

    def get_materials_summary(self,
                             elements: Optional[List[str]] = None,
                             limit: int = 100) -> Dict[str, Any]:
        """
        Get a materials summary — a lighter-weight query than search_materials.

        Returns only the most basic material identifiers and density information,
        suitable for quick browsing.

        Args:
            elements (List[str], optional): List of elements to restrict to, e.g. ["Fe"]
            limit (int): Maximum number of results to return, default 100

        Returns:
            Dict: Summary dictionary containing data and meta
        """
        try:
            # ---- Build search parameters ----
            kwargs = {}
            if elements:
                kwargs["elements"] = elements

            # ---- Request only the core fields to speed up the query ----
            fields = [
                "material_id",
                "formula_pretty",
                "chemsys",
                "density"
            ]

            # Execute the search (a larger chunk_size is given to fetch more results at once)
            docs = self.mpr.materials.search(
                **kwargs,
                chunk_size=min(limit, 1000),
                fields=fields
            )

            # ---- Convert to summary format ----
            materials_data = []
            for doc in docs:
                # Density gets the g/cm^3 unit appended
                density_value = getattr(doc, "density", "N/A")
                density_with_unit = f"{density_value} g/cm^3" if density_value != "N/A" else "N/A"

                material_dict = {
                    "material_id": str(getattr(doc, "material_id", "N/A")),
                    "formula": getattr(doc, "formula_pretty", getattr(doc, "formula", "N/A")),
                    "chemsys": getattr(doc, "chemsys", "N/A"),
                    "density": density_with_unit
                }
                materials_data.append(material_dict)

            return {
                "data": materials_data,
                "meta": {
                    "total_count": len(materials_data),
                    "limit": limit
                }
            }

        except Exception as e:
            logger.error(f"Error getting material summary: {e}")
            return {"error": f"Error getting material summary: {str(e)}"}

# ---- Global singleton management ----
# Use a module-level variable to store the tool instance, avoiding repeated creation (singleton pattern)

# Global MaterialsProjectTool instance, initially None
materials_project_tool = None

def get_materials_project_tool(api_key: Optional[str] = None) -> MaterialsProjectTool:
    """
    Get the singleton instance of the Materials Project tool.
    Created on first call; subsequent calls return the same instance.

    Args:
        api_key (str, optional): Materials Project API key (used only on first creation)

    Returns:
        MaterialsProjectTool: The tool instance
    """
    global materials_project_tool
    if materials_project_tool is None:
        materials_project_tool = MaterialsProjectTool(api_key)
    return materials_project_tool
