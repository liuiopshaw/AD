#!/usr/bin/env python3
# 上下文存储模块 - 提供线程安全的数据共享机制
# 在 ECOMATS 多 Agent 协作架构中，不同 Agent 可能运行在不同的线程中，
# 本模块确保它们能够安全地共享数据而不会出现竞态条件（race condition）

# typing 模块用于提供类型注解，Dict 和 Any 表示键值对的类型
from typing import Any, Dict
# threading 模块提供线程锁机制，确保多线程环境下的数据一致性
import threading

class ContextStore:
    """
    线程安全的上下文存储类，用于在多个 Agent 之间共享数据。

    设计思想：
    - 使用类级别变量（而非实例变量），使所有 Agent 共享同一份数据。
    - 使用可重入锁 (RLock) 保护读写操作，支持嵌套调用。
    - 提供简单的 set/get/clear 接口，类似字典操作。
    """
    # 类级别的存储字典，存放所有共享的键值对数据
    # 使用类变量而非实例变量的原因：所有调用方看到的是同一份数据，实现全局共享
    _store: Dict[str, Any] = {}
    # 可重入锁 (Reentrant Lock)
    # RLock 允许同一线程多次获取锁而不会死锁，这在存在嵌套调用时非常有用
    # 例如 get() 方法在回调中又调用了 set()，RLock 可以保证不会死锁
    _lock = threading.RLock()

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """
        向上下文存储中设置一个键值对。

        此方法是线程安全的：通过锁确保在写入期间不会有其他线程同时读写。

        Args:
            key: 数据的键名（字符串），如 "material_identifier"
            value: 要存储的值，可以是任意类型的数据
        """
        # with 语句自动获取和释放锁，即使在内部发生异常也会安全释放
        with cls._lock:
            cls._store[key] = value

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        从上下文存储中获取一个值。

        此方法是线程安全的：通过锁确保读取期间数据的一致性。

        Args:
            key: 要获取的数据的键名
            default: 如果键不存在时的默认返回值，默认为 None

        Returns:
            与 key 关联的值；如果 key 不存在则返回 default 参数的值
        """
        # 使用锁保护读取操作，避免读到半写入的脏数据
        with cls._lock:
            # 使用 dict.get() 方法安全获取值，不存在时返回 default
            return cls._store.get(key, default)

    @classmethod
    def clear(cls) -> None:
        """
        清空上下文存储中的所有数据。

        通常在任务完成后调用，释放内存并避免数据污染下一次任务。
        同样是线程安全的。
        """
        # 使用锁保护清空操作
        with cls._lock:
            cls._store.clear()

