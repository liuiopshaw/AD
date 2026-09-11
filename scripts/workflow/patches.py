"""
CrewAI Compatibility Patches.
Fixes for CrewAI 1.7.0 async memory issues.

This module contains hotfix patches for known incompatibilities between
CrewAI 1.7.0's async memory system and the synchronous ChromaDB client.
The patches override async methods to delegate to their synchronous counterparts.
"""

# sys: 用于检测操作系统平台（Windows/Linux/macOS）
import sys
# signal: 用于处理 Windows 上不支持的操作系统信号
import signal


def apply_windows_patches():
    """
    应用 Windows 平台特定的兼容性补丁

    Windows 与 Unix 系统有两个关键差异：
    1. 不支持 SIGHUP 信号——创建占位符 None 避免 AttributeError
    2. 默认控制台编码不是 UTF-8——重新配置为 UTF-8 防止中文输出乱码

    这些补丁只在 Windows 平台生效，Linux/macOS 下直接跳过。
    """
    # 检查是否为 Windows 平台
    if sys.platform == 'win32':
        # SIGHUP 是 Unix 的信号（终端挂断），Windows 不支持
        # 在 signal 模块上动态添加 SIGHUP 属性，值设为 None
        # 这样代码中所有 signal.SIGHUP 引用都不会抛异常
        if not hasattr(signal, 'SIGHUP'):
            signal.SIGHUP = None

        # 将标准输出和标准错误的编码改为 UTF-8
        # Windows 终端默认使用 GBK 编码，会导致中文显示为乱码
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            # Python < 3.7 不支持 reconfigure() 方法，静默跳过
            pass


def apply_chromadb_async_patch():
    """
    修补 ChromaDBClient.asearch() 方法

    问题背景：
    CrewAI 1.7.0 的异步内存系统在调用记忆搜索时使用了 async/await 模式，
    但底层 ChromaDB 客户端只提供了同步的 search() 方法，没有 asearch()。
    这导致在异步模式下调用记忆搜索时会抛出 AttributeError。

    解决方案：
    创建 PatchedChromaDBClient 子类，覆写 asearch() 方法，
    让它直接调用父类的同步 search() 方法。
    async/await 会等待这个同步调用完成，但不影响其他异步操作。

    应用方式：
    在模块级别替换 ChromaDBClient 类，CrewAI 后续会实例化修补后的版本。
    """
    # 导入 CrewAI 的 ChromaDB 客户端模块
    import crewai.rag.chromadb.client as chromadb_client_module
    # 保留原始类引用（以防后续需要）
    original_ChromaDBClient = chromadb_client_module.ChromaDBClient

    class PatchedChromaDBClient(original_ChromaDBClient):
        """
        修补后的 ChromaDBClient

        唯一修改：将异步 asearch() 重定向到同步 search()。
        **kwargs 捕获所有关键字参数并原封不动传递给同步方法。
        """
        async def asearch(self, **kwargs):
            """
            异步搜索的同步兜底实现

            将异步调用转为同步执行。在事件循环中，这个同步调用
            会阻塞当前协程但不影响其他协程（因为它在 async def 中）。

            Args:
                **kwargs: 搜索参数（query、limit、filter 等），直接透传给 search()

            Returns:
                与 search() 相同的返回值
            """
            return self.search(**kwargs)

    # 在模块级别替换类——CrewAI 后续会导入并使用修补后的版本
    chromadb_client_module.ChromaDBClient = PatchedChromaDBClient


def apply_rag_storage_async_patch():
    """
    修补 RAGStorage.asearch() 方法

    问题背景：
    与 ChromaDB 类似，CrewAI 的 RAGStorage 类在异步模式下也会尝试
    调用 asearch() 方法，但实现中没有这个方法。

    解决方案：
    创建 PatchedRAGStorage 子类，覆写 asearch() 方法，
    用相同的参数直接调用同步 search() 方法。

    这个方法签名必须与 CrewAI 预期的一致：
    - query: 搜索查询文本
    - limit: 返回结果数量上限
    - filter: 可选的过滤条件
    - score_threshold: 相似度阈值
    """
    # 导入 CrewAI 的 RAG 存储模块
    import crewai.memory.storage.rag_storage as rag_storage_module
    # 保留原始类引用
    original_RAGStorage = rag_storage_module.RAGStorage

    class PatchedRAGStorage(original_RAGStorage):
        """
        修补后的 RAGStorage

        asearch() 重定向到 search()，参数完全一致。
        这确保了 CrewAI 的异步记忆搜索能正常工作。
        """
        async def asearch(self, query: str, limit: int = 5, filter=None, score_threshold: float = 0.6):
            """
            异步检索的同步兜底实现

            将异步搜索委托给同步的 search() 方法，所有参数原样传递。

            Args:
                query: 搜索查询字符串
                limit: 返回结果的最大数量，默认 5
                filter: 可选的元数据过滤条件
                score_threshold: 相似度分数阈值，默认 0.6（只返回较相似的结果）

            Returns:
                与 search() 相同的返回值
            """
            return self.search(query, limit, filter, score_threshold)

    # 在模块级别替换类
    rag_storage_module.RAGStorage = PatchedRAGStorage


def apply_crewai_patches(verbose: bool = True):
    """
    应用所有 CrewAI 兼容性补丁

    这是补丁模块的统一入口函数。调用它会依次应用：
    1. Windows 平台补丁（信号和编码）
    2. ChromaDB 异步补丁（asearch -> search）
    3. RAG 存储异步补丁（asearch -> search）

    必须在导入 CrewAI 核心类（Crew, Agent, Task 等）之前调用，
    因为 ChromaDB 和 RAGStorage 的补丁需要在类被使用之前生效。

    Args:
        verbose: 是否打印补丁应用成功的确认消息，默认 True
    """
    # 依次应用三个补丁
    apply_windows_patches()
    apply_chromadb_async_patch()
    apply_rag_storage_async_patch()

    # 打印确认消息（仅在 verbose=True 时）
    if verbose:
        print("✅ CrewAI async memory compatibility patch applied")
