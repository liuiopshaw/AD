"""
DashScope Embedding Function.
Provides embedding support for CrewAI memory system.

This module implements a custom embedding function that bridges CrewAI's
memory system with Alibaba Cloud's DashScope text-embedding-v2 API.
It uses the OpenAI-compatible SDK pattern because DashScope's embedding
endpoint is OpenAI-compatible.
"""

# os: read the API key from environment variables
import os
# numpy: convert the float lists returned by DashScope into numpy arrays (required by ChromaDB)
import numpy as np
# ChromaDB's embedding function base class -- must be inherited to be usable as a ChromaDB embedder
from chromadb.api.types import EmbeddingFunction as ChromaEmbeddingFunction
# CrewAI's custom embedding function base class -- must be inherited to satisfy CrewAI's Pydantic validation
from crewai.rag.embeddings.providers.custom.embedding_callable import CustomEmbeddingFunction
# CrewAI type definitions: Documents (input text list) and Embeddings (output vector list)
from crewai.rag.core.types import Documents, Embeddings
# OpenAI SDK -- used to call DashScope's embedding API via its compatible protocol
from openai import OpenAI


class DashScopeEmbeddingFunction(CustomEmbeddingFunction, ChromaEmbeddingFunction):
    """
    Embedding function that calls the DashScope Embedding API via the OpenAI SDK

    Inherits from two base classes:
    - CustomEmbeddingFunction: satisfies CrewAI's Pydantic type checking
    - ChromaEmbeddingFunction: satisfies ChromaDB's embedding function interface

    The dual inheritance ensures this class satisfies the type requirements of
    both CrewAI and ChromaDB, avoiding Pydantic validation errors when CrewAI's
    memory system is initialized.

    Model used: text-embedding-v2
    Vector dimension: 1536
    """

    def __init__(self):
        """
        Initialize the DashScope client

        Creates a client with the OpenAI SDK, pointing base_url at DashScope's
        compatible endpoint. QWEN_API_KEY is read from the environment variables
        (already set as an OpenAI-compatible variable in an earlier step).

        Why use the OpenAI SDK instead of the DashScope SDK:
        DashScope's Embedding API endpoint is OpenAI-compatible
        (/compatible-mode/v1), so using the OpenAI SDK lets us reuse its
        mature error handling and retry logic.
        """
        # Create an OpenAI client, but point base_url at DashScope's
        # OpenAI-compatible endpoint
        self.client = OpenAI(
            api_key=os.getenv('QWEN_API_KEY'),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        # text-embedding-v2 is the embedding model currently offered by DashScope
        # Vector dimension 1536, input limit 1-2048 characters
        self.model = "text-embedding-v2"

    def __call__(self, input: Documents) -> Embeddings:
        """
        Convert a list of texts into a list of embedding vectors

        This is the standard interface by which ChromaDB/CrewAI calls an
        embedding function. Overriding __call__ makes class instances callable
        like functions.

        Processing flow:
        1. Truncate texts that exceed the length limit (text-embedding-v2
           allows at most 2048 characters)
        2. Call the DashScope API to obtain embedding vectors
        3. Convert the returned float lists into numpy arrays
        4. If the API call fails, return zero vectors as a fallback

        Args:
            input: list of documents (list of strings); the type signature is
                Documents = list[str]

        Returns:
            Embeddings: list of embedding vectors (list of numpy arrays); the
                type signature is list[np.ndarray]

        Raises:
            Does not raise exceptions -- returns zero vectors as a fallback
            when an error occurs
        """
        try:
            # text-embedding-v2 API limit: 1-2048 characters per text
            # The excess is truncated (Python string slicing truncates by
            # character, which also works for Chinese)
            MAX_LENGTH = 2048
            truncated_input = [
                text[:MAX_LENGTH] if len(text) > MAX_LENGTH else text
                for text in input
            ]

            # Call the DashScope Embedding API (via the OpenAI-compatible SDK)
            # The underlying request actually goes to
            # https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
            response = self.client.embeddings.create(
                model=self.model,
                input=truncated_input
            )

            # Convert the embedding float lists returned by the API into numpy arrays.
            # dtype=np.float32 matches ChromaDB's internal storage format,
            # avoiding type-conversion overhead
            embeddings = [
                np.array(item.embedding, dtype=np.float32)
                for item in response.data
            ]
            return embeddings

        except Exception as e:
            # Fallback when the API call fails:
            # return zero vectors instead, with dimension 1536 (the standard
            # dimension of text-embedding-v2).
            # Zero vectors carry no semantic information, but at least they let
            # the program keep running instead of crashing.
            # A warning is also printed to help troubleshooting
            print(f"⚠️ DashScope Embedding Error: {e}")
            return [np.zeros(1536, dtype=np.float32) for _ in range(len(input))]


def create_dashscope_embedder():
    """
    Create the DashScope embedding function class (returns the class, not an instance)

    This is the factory function called from outside. It returns the
    DashScopeEmbeddingFunction class itself rather than an instance, because
    CrewAI expects a class (callable) in the embedder configuration and will
    instantiate it itself when needed.

    Returns:
        class: the DashScopeEmbeddingFunction class (not an instance)
    """
    return DashScopeEmbeddingFunction
