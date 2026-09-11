"""
DashScope Embedding Function.
Provides embedding support for CrewAI memory system.

This module implements a custom embedding function that bridges CrewAI's
memory system with Alibaba Cloud's DashScope text-embedding-v2 API.
It uses the OpenAI-compatible SDK pattern because DashScope's embedding
endpoint is OpenAI-compatible.
"""

# os: 读取环境变量中的 API Key
import os
# numpy: 将 DashScope 返回的浮点数列表转换为 numpy 数组（ChromaDB 要求）
import numpy as np
# ChromaDB 的嵌入函数基类——需要继承它才能作为 ChromaDB 的嵌入器使用
from chromadb.api.types import EmbeddingFunction as ChromaEmbeddingFunction
# CrewAI 的自定义嵌入函数基类——需要继承它以满足 CrewAI 的 Pydantic 验证
from crewai.rag.embeddings.providers.custom.embedding_callable import CustomEmbeddingFunction
# CrewAI 的类型定义：Documents（输入文本列表）和 Embeddings（输出向量列表）
from crewai.rag.core.types import Documents, Embeddings
# OpenAI SDK——利用其兼容协议调用 DashScope 的 embedding API
from openai import OpenAI


class DashScopeEmbeddingFunction(CustomEmbeddingFunction, ChromaEmbeddingFunction):
    """
    使用 OpenAI SDK 调用 DashScope Embedding API 的嵌入函数

    继承自两个基类：
    - CustomEmbeddingFunction: 满足 CrewAI 的 Pydantic 类型检查
    - ChromaEmbeddingFunction: 满足 ChromaDB 的嵌入函数接口

    双重继承确保此类同时满足 CrewAI 和 ChromaDB 的类型要求，
    避免在 CrewAI 的内存系统初始化时出现 Pydantic 验证错误。

    使用的模型: text-embedding-v2
    向量维度: 1536
    """

    def __init__(self):
        """
        初始化 DashScope 客户端

        使用 OpenAI SDK 创建客户端，将 base_url 指向 DashScope 的兼容端点。
        QWEN_API_KEY 从环境变量中读取（在先前的流程中已设置为 OpenAI 兼容变量）。

        为什么使用 OpenAI SDK 而不是 DashScope SDK：
        DashScope 的 Embedding API 端点是 OpenAI 兼容的（/compatible-mode/v1），
        使用 OpenAI SDK 可以复用其完善的错误处理和重试逻辑。
        """
        # 创建 OpenAI 客户端，但 base_url 指向 DashScope 的 OpenAI 兼容端点
        self.client = OpenAI(
            api_key=os.getenv('QWEN_API_KEY'),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        # text-embedding-v2 是 DashScope 当前提供的嵌入模型
        # 向量维度 1536，输入限制 1-2048 个字符
        self.model = "text-embedding-v2"

    def __call__(self, input: Documents) -> Embeddings:
        """
        将文本列表转换为嵌入向量列表

        这是 ChromaDB/CrewAI 调用嵌入函数的标准接口。
        重写 __call__ 方法使类实例可以像函数一样被调用。

        处理流程：
        1. 截断超出长度限制的文本（text-embedding-v2 最大 2048 字符）
        2. 调用 DashScope API 获取嵌入向量
        3. 将返回的浮点数列表转换为 numpy 数组
        4. 如果 API 调用失败，返回零向量作为兜底方案

        Args:
            input: 文档列表（字符串列表），类型签名是 Documents = list[str]

        Returns:
            Embeddings: 嵌入向量列表（numpy 数组列表），类型签名是 list[np.ndarray]

        Raises:
            不会抛出异常——遇到错误时返回零向量作为兜底
        """
        try:
            # text-embedding-v2 的 API 限制：每条文本 1-2048 个字符
            # 超出部分截断（Python 字符串切片按字符截断，中文也适用）
            MAX_LENGTH = 2048
            truncated_input = [
                text[:MAX_LENGTH] if len(text) > MAX_LENGTH else text
                for text in input
            ]

            # 调用 DashScope Embedding API（通过 OpenAI 兼容 SDK）
            # 底层实际请求的是 https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
            response = self.client.embeddings.create(
                model=self.model,
                input=truncated_input
            )

            # 将 API 返回的 embedding 浮点数列表转换为 numpy 数组
            # dtype=np.float32 与 ChromaDB 内部存储格式一致，避免类型转换开销
            embeddings = [
                np.array(item.embedding, dtype=np.float32)
                for item in response.data
            ]
            return embeddings

        except Exception as e:
            # API 调用失败的兜底方案：
            # 返回零向量代替，维度 1536（text-embedding-v2 的标准维度）
            # 零向量虽然没有语义信息，但至少能让程序继续运行而不会崩溃
            # 同时打印警告信息便于排查问题
            print(f"⚠️ DashScope Embedding Error: {e}")
            return [np.zeros(1536, dtype=np.float32) for _ in range(len(input))]


def create_dashscope_embedder():
    """
    创建 DashScope 嵌入函数类（返回类而非实例）

    这是外部调用的工厂函数。返回 DashScopeEmbeddingFunction 类本身
    而不是实例，因为 CrewAI 期望在 embedder 配置中传入一个类（callable），
    CrewAI 会在需要时自己实例化。

    Returns:
        class: DashScopeEmbeddingFunction 类（不是实例）
    """
    return DashScopeEmbeddingFunction
