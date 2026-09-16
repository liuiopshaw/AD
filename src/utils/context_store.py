#!/usr/bin/env python3
# Context store module - provides a thread-safe data sharing mechanism
# In the ECOMATS multi-agent collaboration architecture, different agents may run in
# different threads; this module ensures they can safely share data without race conditions

# The typing module provides type annotations; Dict and Any describe the key-value pair types
from typing import Any, Dict
# The threading module provides thread-locking mechanisms to ensure data consistency in multi-threaded environments
import threading

class ContextStore:
    """
    Thread-safe context store for sharing data among multiple agents.

    Design principles:
    - Use class-level variables (rather than instance variables) so all agents share the same data.
    - Use a reentrant lock (RLock) to protect read/write operations and support nested calls.
    - Provide simple set/get/clear interfaces, similar to dictionary operations.
    """
    # Class-level storage dictionary holding all shared key-value data
    # Class variables are used instead of instance variables so that all callers see
    # the same data, achieving global sharing
    _store: Dict[str, Any] = {}
    # Reentrant lock (RLock)
    # RLock allows the same thread to acquire the lock multiple times without deadlocking,
    # which is very useful when nested calls exist
    # For example, if the get() method calls set() inside a callback, RLock guarantees no deadlock
    _lock = threading.RLock()

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """
        Set a key-value pair in the context store.

        This method is thread-safe: the lock ensures no other thread reads or writes concurrently during the write.

        Args:
            key: The key name of the data (string), e.g. "material_identifier"
            value: The value to store; can be data of any type
        """
        # The with statement automatically acquires and releases the lock,
        # releasing it safely even if an exception occurs inside
        with cls._lock:
            cls._store[key] = value

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        Retrieve a value from the context store.

        This method is thread-safe: the lock ensures data consistency during the read.

        Args:
            key: The key name of the data to retrieve
            default: The default value returned if the key does not exist; defaults to None

        Returns:
            The value associated with key; returns the default argument if key does not exist
        """
        # Use the lock to protect the read operation, avoiding reading partially written dirty data
        with cls._lock:
            # Use dict.get() to safely retrieve the value, returning default when absent
            return cls._store.get(key, default)

    @classmethod
    def clear(cls) -> None:
        """
        Clear all data in the context store.

        Typically called after a task completes to free memory and prevent data
        from polluting the next task.
        Also thread-safe.
        """
        # Use the lock to protect the clear operation
        with cls._lock:
            cls._store.clear()
