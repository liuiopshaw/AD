"""
CrewAI Compatibility Patches.
Fixes for CrewAI 1.7.0 async memory issues.

This module contains hotfix patches for known incompatibilities between
CrewAI 1.7.0's async memory system and the synchronous ChromaDB client.
The patches override async methods to delegate to their synchronous counterparts.
"""

# sys: used to detect the operating system platform (Windows/Linux/macOS)
import sys
# signal: used to handle OS signals not supported on Windows
import signal


def apply_windows_patches():
    """
    Apply Windows platform-specific compatibility patches

    There are two key differences between Windows and Unix systems:
    1. SIGHUP is not supported -- create a None placeholder to avoid AttributeError
    2. The default console encoding is not UTF-8 -- reconfigure to UTF-8 to
       prevent garbled Chinese output

    These patches only take effect on Windows; they are skipped on Linux/macOS.
    """
    # Check whether the platform is Windows
    if sys.platform == 'win32':
        # SIGHUP is a Unix signal (terminal hangup) and is not supported on Windows.
        # Dynamically add a SIGHUP attribute to the signal module, set to None,
        # so that all references to signal.SIGHUP in the code do not raise exceptions
        if not hasattr(signal, 'SIGHUP'):
            signal.SIGHUP = None

        # Change the encoding of stdout and stderr to UTF-8.
        # Windows terminals default to GBK encoding, which would display
        # Chinese as garbled characters
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            # Python < 3.7 does not support the reconfigure() method; skip silently
            pass


def apply_chromadb_async_patch():
    """
    Patch the ChromaDBClient.asearch() method

    Background:
    CrewAI 1.7.0's async memory system uses the async/await pattern when
    invoking memory search, but the underlying ChromaDB client only provides
    a synchronous search() method and has no asearch().
    This causes an AttributeError when memory search is called in async mode.

    Solution:
    Create a PatchedChromaDBClient subclass that overrides asearch()
    so that it directly calls the parent class's synchronous search() method.
    async/await will wait for this synchronous call to complete without
    affecting other asynchronous operations.

    How it is applied:
    Replace the ChromaDBClient class at module level; CrewAI will later
    instantiate the patched version.
    """
    # Import CrewAI's ChromaDB client module
    import crewai.rag.chromadb.client as chromadb_client_module
    # Keep a reference to the original class (in case it is needed later)
    original_ChromaDBClient = chromadb_client_module.ChromaDBClient

    class PatchedChromaDBClient(original_ChromaDBClient):
        """
        Patched ChromaDBClient

        The only modification: redirect the async asearch() to the synchronous
        search(). **kwargs captures all keyword arguments and passes them
        through unchanged to the synchronous method.
        """
        async def asearch(self, **kwargs):
            """
            Synchronous fallback implementation of async search

            Converts the async call into synchronous execution. In the event
            loop, this synchronous call blocks the current coroutine but does
            not affect other coroutines (because it is inside an async def).

            Args:
                **kwargs: search parameters (query, limit, filter, etc.),
                    passed straight through to search()

            Returns:
                The same return value as search()
            """
            return self.search(**kwargs)

    # Replace the class at module level -- CrewAI will later import and use
    # the patched version
    chromadb_client_module.ChromaDBClient = PatchedChromaDBClient


def apply_rag_storage_async_patch():
    """
    Patch the RAGStorage.asearch() method

    Background:
    Similar to ChromaDB, CrewAI's RAGStorage class also tries to call an
    asearch() method in async mode, but the implementation does not provide
    this method.

    Solution:
    Create a PatchedRAGStorage subclass that overrides asearch()
    to directly call the synchronous search() method with the same arguments.

    This method signature must match what CrewAI expects:
    - query: search query text
    - limit: maximum number of results to return
    - filter: optional filter conditions
    - score_threshold: similarity threshold
    """
    # Import CrewAI's RAG storage module
    import crewai.memory.storage.rag_storage as rag_storage_module
    # Keep a reference to the original class
    original_RAGStorage = rag_storage_module.RAGStorage

    class PatchedRAGStorage(original_RAGStorage):
        """
        Patched RAGStorage

        asearch() is redirected to search() with exactly the same arguments.
        This ensures CrewAI's async memory search works correctly.
        """
        async def asearch(self, query: str, limit: int = 5, filter=None, score_threshold: float = 0.6):
            """
            Synchronous fallback implementation of async retrieval

            Delegates the async search to the synchronous search() method,
            passing all arguments through unchanged.

            Args:
                query: search query string
                limit: maximum number of results to return, default 5
                filter: optional metadata filter conditions
                score_threshold: similarity score threshold, default 0.6
                    (only fairly similar results are returned)

            Returns:
                The same return value as search()
            """
            return self.search(query, limit, filter, score_threshold)

    # Replace the class at module level
    rag_storage_module.RAGStorage = PatchedRAGStorage


def apply_crewai_patches(verbose: bool = True):
    """
    Apply all CrewAI compatibility patches

    This is the unified entry point of the patch module. Calling it applies,
    in order:
    1. Windows platform patches (signals and encoding)
    2. ChromaDB async patch (asearch -> search)
    3. RAG storage async patch (asearch -> search)

    Must be called before importing CrewAI core classes (Crew, Agent, Task,
    etc.), because the ChromaDB and RAGStorage patches need to take effect
    before the classes are used.

    Args:
        verbose: whether to print a confirmation message that the patches
            were applied successfully, default True
    """
    # Apply the three patches in order
    apply_windows_patches()
    apply_chromadb_async_patch()
    apply_rag_storage_async_patch()

    # Print the confirmation message (only when verbose=True)
    if verbose:
        print("✅ CrewAI async memory compatibility patch applied")
