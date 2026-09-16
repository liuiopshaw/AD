# src/__init__.py
# The presence of this file makes the src directory a Python package
# Without this file, Python would not recognize the src directory as an importable package,
# which would cause statements like import src.xxx to fail

# __init__.py is the initialization file of a Python package and is executed automatically
# when the package is first imported

# This file makes the src directory a Python package
# Translation of the line above: this file makes the src directory a Python package

# The __all__ variable defines the list of symbols imported by "from src import *"
# It is currently an empty list, meaning "from src import *" imports nothing
# This is a conservative approach that encourages callers to explicitly import the submodules they need
__all__ = []

# You can also add other important imports here if needed
# If you later need certain submodules to be loaded automatically when the src package is imported,
# you can add import statements here
# For example, uncommenting the lines below will make import src automatically load
# the agents, tasks, and tools modules

# from .agents import *
# from .tasks import *
# from .tools import *
