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

# ---- 从子模块导入并重新导出公共 API ----
# 这种模式使外部代码可以通过 'from workflow import xxx' 直接访问，
# 而不需要知道具体实现在哪个子模块中

# patches 模块：CrewAI 兼容性补丁
# apply_crewai_patches: 统一入口——应用所有补丁（Windows + ChromaDB + RAGStorage）
from .patches import apply_crewai_patches

# callback_factory 模块：任务回调工厂
# create_task_callback_factory: 创建支持并行任务计时的回调函数工厂
from .callback_factory import create_task_callback_factory

# embeddings 模块：DashScope 嵌入函数
# create_dashscope_embedder: 返回嵌入函数类（供 CrewAI embedder 配置使用）
from .embeddings import create_dashscope_embedder

# ---- 定义包的公开接口 ----
# __all__ 控制 from workflow import * 时的导出列表
# 同时也是这个包的公共 API 文档
__all__ = [
    'apply_crewai_patches',
    'create_task_callback_factory',
    'create_dashscope_embedder',
]
