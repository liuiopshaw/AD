"""
ECOMATS Workflow Module
Modular components for workflow execution.

This package contains the modularized components that support the
async and sync workflow execution pipelines, separated from the
main entry points for better maintainability and reusability.

Modules:
- patches: CrewAI compatibility hotfixes (ChromaDB async, Windows signals)
- callback_factory: Task callback factory with parallel task timing support
- embeddings: DashScope text embedding function for CrewAI memory system
"""

# ---- Import from submodules and re-export the public API ----
# This pattern allows external code to access everything directly via
# 'from workflow import xxx', without needing to know which submodule
# each implementation lives in

# patches module: CrewAI compatibility patches
# apply_crewai_patches: unified entry point -- applies all patches (Windows + ChromaDB + RAGStorage)
from .patches import apply_crewai_patches

# callback_factory module: task callback factory
# create_task_callback_factory: creates a callback function factory with
# parallel task timing support
from .callback_factory import create_task_callback_factory

# embeddings module: DashScope embedding function
# create_dashscope_embedder: returns the embedding function class (for use in
# CrewAI's embedder configuration)
from .embeddings import create_dashscope_embedder

# ---- Define the package's public interface ----
# __all__ controls what is exported by 'from workflow import *'
# It also serves as the public API documentation of this package
__all__ = [
    'apply_crewai_patches',
    'create_task_callback_factory',
    'create_dashscope_embedder',
]
