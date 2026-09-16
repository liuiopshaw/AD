import requests
import logging
import time
import random
import os
from typing import Dict, Any, List, Optional

# Configure logging: set default level to WARNING to reduce log noise at runtime
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class MolPortTool:
    """MolPort database query tool.

    MolPort is a commercial chemical database providing supplier, stock, and
    pricing information for compounds. This tool wraps the core functionality
    of the MolPort API to assess the commercial availability of compounds.

    Supported features:
    1. Search compounds by SMILES (exact match, similarity search, substructure search, etc.)
    2. Retrieve detailed information by MolPort ID
    3. Retrieve supplier, stock, and pricing information
    4. Assess the commercial availability of compounds
    """

    # Search type constant definitions
    # The MolPort API uses integer codes for different search modes
    SEARCH_TYPE_EXACT = 3        # Exact match search
    SEARCH_TYPE_SIMILARITY = 4   # Similarity search (default mode)
    SEARCH_TYPE_SUBSTRUCTURE = 1 # Substructure search: find compounds containing the specified substructure
    SEARCH_TYPE_SUPERSTRUCTURE = 2 # Superstructure search: find compounds contained within the specified structure
    SEARCH_TYPE_PERFECT = 5      # Perfect match: including stereochemistry
    SEARCH_TYPE_EXACT_FRAGMENT = 6 # Exact fragment search

    def __init__(self, api_key: str = None):
        """
        Initialize MolPort tool.
        Initialize the MolPort tool, configuring the API connection and request control.

        Args:
            api_key: MolPort API key; if not provided, it is read from the
                     MOLPORT_API_KEY environment variable. Storing the API key
                     in an environment variable is a security best practice that
                     avoids hardcoding sensitive information in the code
        """
        # Base URL of the MolPort API
        self.base_url = "https://api.molport.com/api"
        # API key: prefer the passed-in parameter, then the environment variable; empty string if neither
        self.api_key = api_key or os.getenv('MOLPORT_API_KEY', '')
        # Create a reusable HTTP session object
        self.session = requests.Session()

        # Set HTTP request headers
        # User-Agent identifies the tool; Content-Type and Accept specify JSON data exchange
        self.session.headers.update({
            "User-Agent": "ECOMATS-MolPort-Tool/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

        # Request rate control
        # last_request_time records the timestamp of the last request, used to enforce the minimum request interval
        self.last_request_time = 0
        # Minimum request interval of 1.0 second: the MolPort API rate limit is relatively lenient
        self.min_request_interval = 1.0

    def _make_get_request(self, endpoint: str, params: Dict = None, timeout: int = 30, max_retries: int = 3) -> Dict[str, Any]:
        """
        Send GET request with retry mechanism.

        Design highlights:
        1. Rate control: ensure the interval between requests is no shorter than min_request_interval to avoid hitting the API rate limit
        2. Exponential backoff retry: automatically retry on network failures with progressively longer intervals
        3. Random jitter: add a random factor to the backoff delay to avoid the "thundering herd" effect

        Args:
            endpoint: API endpoint path
            params: URL query parameter dictionary
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries

        Returns:
            API response data dictionary; returns {"error": ...} on failure
        """
        # Rate control: if the time since the last request is shorter than the minimum interval, wait for the remaining time
        # This is client-side throttling to ensure we do not put excessive pressure on the API server
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last_request)

        for attempt in range(max_retries):
            try:
                # Construct the full request URL
                url = f"{self.base_url}/{endpoint}"
                logger.debug(f"Requesting MolPort API (GET): {url}")

                # Update the last request time (updated before sending the request to ensure frequent requests are properly throttled)
                self.last_request_time = time.time()

                # Send the GET request
                response = self.session.get(url, params=params, timeout=timeout)
                # Check the HTTP status code; 4xx/5xx raises an exception
                response.raise_for_status()

                # Return the parsed JSON data
                return response.json()

            except requests.exceptions.RequestException as e:
                # Network request exception (connection error, timeout, server error, etc.)
                logger.warning(f"MolPort API request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    # Exponential backoff delay: 2^attempt seconds + 0-1 second of random jitter
                    # So the 1st retry waits about 1-2s, the 2nd about 2-3s, the 3rd about 4-5s
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    logger.info(f"Retrying in {delay:.2f} seconds")
                    time.sleep(delay)
                else:
                    # All retries failed; log the final error
                    logger.error(f"MolPort API request ultimately failed: {e}")
                    return {"error": f"API request failed: {str(e)}"}
            except Exception as e:
                # Other exceptions (e.g., JSON parsing errors)
                logger.error(f"Error processing response: {e}")
                return {"error": f"Error processing response: {str(e)}"}

        # This should never be reached in theory (the loop always returns, or the last iteration returns an error),
        # but kept as a defensive fallback return
        return {"error": "Request failed"}

    def _make_post_request(self, endpoint: str, data: Dict = None, timeout: int = 60, max_retries: int = 3) -> Dict[str, Any]:
        """
        Send POST request with retry mechanism.

        Differences from _make_get_request:
        - Uses the POST method to send a JSON request body
        - Longer default timeout (60 seconds), because chemical structure searches can be time-consuming
        - Data is sent via the json=data parameter (automatically serialized to JSON with Content-Type set)

        Args:
            endpoint: API endpoint path
            data: Request body data dictionary
            timeout: Request timeout in seconds, default 60 seconds
            max_retries: Maximum number of retries

        Returns:
            API response data dictionary; returns {"error": ...} on failure
        """
        # Rate control: ensure the minimum request interval is respected
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last_request)

        for attempt in range(max_retries):
            try:
                url = f"{self.base_url}/{endpoint}"
                logger.debug(f"Requesting MolPort API (POST): {url}")

                # Update the last request time
                self.last_request_time = time.time()

                # Send the POST request; json=data automatically serializes the dictionary to JSON
                # The requests library automatically sets Content-Type to application/json
                response = self.session.post(url, json=data, timeout=timeout)
                response.raise_for_status()

                return response.json()

            except requests.exceptions.RequestException as e:
                logger.warning(f"MolPort API request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    # Exponential backoff + random jitter
                    delay = (2 ** attempt) + (random.randint(0, 1000) / 1000)
                    logger.info(f"Retrying in {delay:.2f} seconds")
                    time.sleep(delay)
                else:
                    logger.error(f"MolPort API request ultimately failed: {e}")
                    return {"error": f"API request failed: {str(e)}"}
            except Exception as e:
                logger.error(f"Error processing response: {e}")
                return {"error": f"Error processing response: {str(e)}"}

        return {"error": "Request failed"}

    def load_molecule_by_id(self, molecule_id: str) -> Dict[str, Any]:
        """
        Load molecule details by MolPort ID.

        MolPort ID formats:
        - Short format: e.g., "2325020"
        - Long format: e.g., "Molport-002-325-020"
        Format conversion is handled automatically inside the method.

        Args:
            molecule_id: MolPort molecule ID (both formats supported)

        Returns:
            Molecule details dictionary containing SMILES, suppliers, prices, stock, etc.
        """
        # Check whether the API key is configured
        if not self.api_key:
            return {"error": "MOLPORT_API_KEY is not configured; please set it in the .env file"}

        # Handle the MolPort ID format: strip the "Molport-" prefix and all "-" symbols
        # For example, "Molport-002-325-020" -> "002325020"
        if isinstance(molecule_id, str) and molecule_id.startswith("Molport-"):
            molecule_id = molecule_id.replace("Molport-", "").replace("-", "")

        # The MolPort API molecule/load endpoint
        endpoint = "molecule/load"
        params = {
            "molecule": molecule_id,  # Molecule ID
            "apikey": self.api_key     # API key passed as a query parameter
        }

        # Send the GET request to retrieve molecule information
        return self._make_get_request(endpoint, params=params)

    def search_by_smiles(
        self,
        smiles: str,
        search_type: int = None,
        similarity_index: float = 0.9,
        max_results: int = 100,
        max_search_time: int = 60000
    ) -> Dict[str, Any]:
        """
        Search by SMILES structure.
        Search compounds by SMILES (Simplified Molecular Input Line Entry System) structure.

        SMILES is a linear notation that represents chemical structures as ASCII strings,
        and is one of the most commonly used molecular structure representations in cheminformatics.

        Args:
            smiles: SMILES string, e.g., "CCO" for ethanol, "c1ccccc1" for benzene
            search_type: Search type (1-6); defaults to similarity search (type 4)
            similarity_index: Similarity threshold (0-1); applies only to similarity search
                             0.9 means requiring at least 90% structural similarity
            max_results: Maximum number of returned results (upper limit 10000)
            max_search_time: Maximum search time in milliseconds, default 60000ms (60 seconds)

        Returns:
            Search result list containing matched molecule IDs, SMILES, and similarity indices
        """
        # Check the API key
        if not self.api_key:
            return {"error": "MOLPORT_API_KEY is not configured; please set it in the .env file"}

        # If no search type is specified, default to similarity search (the most commonly used search mode)
        if search_type is None:
            search_type = self.SEARCH_TYPE_SIMILARITY

        # Parameter validation: ensure max_results does not exceed the API upper limit of 10000
        if max_results > 10000:
            max_results = 10000
        # The similarity index must be between 0 and 1
        if similarity_index < 0 or similarity_index > 1:
            similarity_index = 0.9

        # Endpoint for MolPort chemical structure search
        endpoint = "chemical-search/search"
        # Construct the POST request body
        data = {
            "API Key": self.api_key,
            "Structure": smiles,                    # SMILES structure string
            "Search Type": search_type,              # Search type (1-6)
            "Maximum Result Count": max_results,     # Maximum result count
            "Maximum Search Time": max_search_time,  # Maximum search time
            "Chemical Similarity Index": similarity_index  # Chemical similarity index
        }

        # Structure search uses a POST request because SMILES data can be long and contain special characters
        return self._make_post_request(endpoint, data=data)

    def get_availability_info(self, molecule_id: str) -> Dict[str, Any]:
        """
        Get commercial availability info (simplified version).

        Integrates the following information:
        - Basic molecule information (SMILES, IUPAC name, formula, molecular weight)
        - Supplier count and details
        - Price range and currency
        - Stock quantity

        Args:
            molecule_id: MolPort molecule ID

        Returns:
            Dictionary containing availability, supplier count, price range, etc.
        """
        # First load the complete molecule data by MolPort ID
        molecule_data = self.load_molecule_by_id(molecule_id)

        # Return the error directly if loading failed
        if "error" in molecule_data:
            return molecule_data

        try:
            # MolPort API response structure: Data.Molecule contains the core molecule information
            data = molecule_data.get("Data", {}).get("Molecule", {})

            # Extract key availability information
            availability_info = {
                "molport_id": data.get("Molport Id", ""),
                "status": data.get("Status", ""),        # Molecule status (e.g., active/inactive)
                "type": data.get("Type", ""),            # Molecule type (e.g., screening/building block)
                "largest_stock": data.get("Largest Stock", ""),     # Largest stock quantity
                "largest_stock_measure": data.get("Largest Stock Measure", ""),  # Stock unit of measure
                "smiles": data.get("SMILES", ""),
                "iupac": data.get("IUPAC", ""),
                "formula": data.get("Formula", ""),
                "molecular_weight": data.get("Molecular Weight", ""),
                "supplier_count": 0,   # Supplier counter
                "min_price": None,     # Minimum price
                "max_price": None,     # Maximum price
                "currency": None       # Currency unit
            }

            # Collect supplier and pricing information
            # Catalogues contains supplier catalogues of different categories
            catalogues = data.get("Catalogues", {})
            all_suppliers = []

            # Iterate over the three supplier categories:
            # - Screening Block Suppliers: screening compound suppliers
            # - Building Block Suppliers: building block suppliers
            # - Virtual Suppliers: virtual suppliers (may not have stock on hand)
            for category in ["Screening Block Suppliers", "Building Block Suppliers", "Virtual Suppliers"]:
                suppliers = catalogues.get(category, [])
                # extend adds the list elements one by one to all_suppliers instead of nesting lists
                all_suppliers.extend(suppliers)

            # Record the total supplier count
            availability_info["supplier_count"] = len(all_suppliers)

            # Collect pricing information from all suppliers
            # Price structure: supplier -> catalogue -> packing specification -> unit price
            prices = []
            for supplier in all_suppliers:
                for catalogue in supplier.get("Catalogues", []):
                    for packing in catalogue.get("Available Packings", []):
                        price = packing.get("Price")
                        currency = packing.get("Currency")
                        if price is not None:
                            # Record price, currency, amount, and unit
                            prices.append({
                                "price": price,
                                "currency": currency,
                                "amount": packing.get("Amount", ""),
                                "measure": packing.get("Measure", "")
                            })

            # If price data exists, compute summary statistics
            if prices:
                # Assume all prices use the same currency (usually USD)
                # Take the currency of the first price entry as the default currency
                availability_info["currency"] = prices[0]["currency"]
                # Extract a plain list of price values to compute min/max
                price_values = [p["price"] for p in prices]
                availability_info["min_price"] = min(price_values)
                availability_info["max_price"] = max(price_values)
                # Keep only the first 5 price entries as examples to avoid oversized return data
                availability_info["price_details"] = prices[:5]

            return availability_info

        except Exception as e:
            # An exception occurred while parsing the data
            logger.error(f"Error parsing availability info: {e}")
            return {"error": f"Failed to parse data: {str(e)}"}

    def check_compound_availability(self, smiles: str, similarity_threshold: float = 0.95) -> Dict[str, Any]:
        """
        Check compound commercial availability by SMILES.

        Uses a two-stage search strategy:
        1. First try an exact match search (find the identical compound)
        2. If no exact match is found, try a similarity search (find structurally similar alternatives)

        This strategy maximizes the probability of finding a purchasable compound.

        Args:
            smiles: SMILES string
            similarity_threshold: Similarity threshold (0-1) that determines the "available" criterion
                                  Default 0.95, meaning 95%+ structural similarity counts as available

        Returns:
            Availability assessment result dictionary, including match status, best match, etc.
        """
        # Stage 1: exact search
        # An exact match is the highest-quality match; the compound structure is identical
        exact_result = self.search_by_smiles(smiles, search_type=self.SEARCH_TYPE_EXACT, max_results=10)

        # If the exact search itself errors out, return the error directly
        if "error" in exact_result:
            return exact_result

        # Extract the search results
        result_data = exact_result.get("Data", {})
        molecules = result_data.get("Molecules", [])

        # Initialize the assessment result object
        assessment = {
            "query_smiles": smiles,
            "exact_match_found": len(molecules) > 0,  # Whether an exact match exists
            "match_count": len(molecules),
            "availability_status": "unknown",  # Availability status: available/similar_available/not_available
            "best_match": None
        }

        if molecules:
            # Exact match found: the compound can be purchased directly from suppliers
            assessment["availability_status"] = "available"
            best_match = molecules[0]  # Take the first (usually the best) match
            assessment["best_match"] = {
                "molport_id": best_match.get("Molport Id", ""),
                "smiles": best_match.get("SMILES", ""),
                "canonical_smiles": best_match.get("Canonical SMILES", ""),
                "verified_amount": best_match.get("Verified Amount", 0),    # Verified stock quantity
                "unverified_amount": best_match.get("Unverified Amount", 0) # Unverified stock quantity
            }
        else:
            # Stage 2: no exact match, try a similarity search
            # A similarity search can find structurally similar but not identical alternatives
            similar_result = self.search_by_smiles(
                smiles,
                search_type=self.SEARCH_TYPE_SIMILARITY,
                similarity_index=similarity_threshold,
                max_results=10
            )

            if "error" not in similar_result:
                similar_molecules = similar_result.get("Data", {}).get("Molecules", [])
                if similar_molecules:
                    # Structurally similar compounds exist: an analog can be purchased
                    assessment["availability_status"] = "similar_available"
                    assessment["match_count"] = len(similar_molecules)
                    best_match = similar_molecules[0]
                    assessment["best_match"] = {
                        "molport_id": best_match.get("Molport Id", ""),
                        "smiles": best_match.get("SMILES", ""),
                        "canonical_smiles": best_match.get("Canonical SMILES", ""),
                        "similarity_index": best_match.get("Similarity Index", 0),  # Similarity index
                        "verified_amount": best_match.get("Verified Amount", 0),
                        "unverified_amount": best_match.get("Unverified Amount", 0)
                    }
                else:
                    # Neither an exact nor a similar match: the compound is not purchasable
                    assessment["availability_status"] = "not_available"

        return assessment


# Singleton pattern: a globally unique instance
# Use a module-level variable to hold the MolPortTool instance, ensuring global reuse
_molport_tool_instance = None

def get_molport_tool(api_key: str = None) -> MolPortTool:
    """
    Get MolPort tool singleton.

    Advantages of the singleton pattern:
    - HTTP session reuse: avoids creating a new TCP connection for every call
    - Request rate control: globally unified management of API request intervals
    - Memory efficient: only one instance and its cached data

    Args:
        api_key: MolPort API key (optional)
                 Used only when the instance is first created; ignored on subsequent calls

    Returns:
        The singleton instance of MolPortTool
    """
    global _molport_tool_instance
    # Lazy initialization: the instance is created only on the first call
    if _molport_tool_instance is None:
        _molport_tool_instance = MolPortTool(api_key=api_key)
    return _molport_tool_instance
