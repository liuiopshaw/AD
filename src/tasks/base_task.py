#!/usr/bin/env python3
"""
Base Task Class — 基础任务类

本模块定义了所有任务的基类以及任务文本加载工具函数。
所有具体任务（如设计、评估、验证等）都继承自 BaseTask，
通过统一的接口创建 CrewAI 的 Task 对象。
"""

import os
import yaml
from crewai import Task


def get_language():
    """获取当前语言设置

    从项目配置中读取 LANGUAGE 字段，决定任务提示文本使用哪种语言。
    如果配置不可用或读取失败，默认返回 'zh'（中文）。

    Returns:
        str: 语言代码，'zh' 或 'en'
    """
    try:
        # 延迟导入，避免循环依赖 —— Config 模块可能在更上层初始化
        from src.config.config import Config
        return getattr(Config, 'LANGUAGE', 'zh')
    except Exception:
        # 异常时回退到中文，保证系统不会因配置问题崩溃
        return 'zh'


def is_english():
    """检查当前是否为英文模式

    对 get_language() 的便捷封装，避免在业务代码中重复写比较逻辑。

    Returns:
        bool: True 表示英文模式，False 表示中文模式
    """
    return get_language() == 'en'


def load_task_text(task_name):
    """从 YAML 文件中加载任务文本

    根据当前语言设置，从 locales 目录下加载对应语言的任务描述文件。
    任务文本包括 description（任务描述）、expected_output（期望输出格式）、
    user_requirement_prefix（用户需求前缀）等字段，用于动态构建任务提示。

    加载优先级：
    1. 当前语言对应的 YAML 文件
    2. 回退到中文（zh）的 YAML 文件
    3. 如果两者都不存在，返回空字典

    Args:
        task_name: 任务名称，如 'design_task'、'evaluation_task'
                   应与 locales/<lang>/tasks/ 目录下的文件名（不含扩展名）对应

    Returns:
        dict: 包含 description、expected_output、user_requirement_prefix 等字段的字典
              如果文件不存在或解析失败，返回空字典
    """
    lang = get_language()
    # 获取当前文件所在目录的绝对路径，用于构建 locales 目录路径
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # 构建当前语言对应的 YAML 文件路径
    # 路径形如：src/locales/<lang>/tasks/<task_name>.yaml
    yaml_path = os.path.join(current_dir, '..', 'locales', lang, 'tasks', f'{task_name}.yaml')

    # 如果当前语言的 YAML 文件不存在，回退到中文版本
    # 这确保了即使翻译不完整，任务也能正常运行
    if not os.path.exists(yaml_path):
        yaml_path = os.path.join(current_dir, '..', 'locales', 'zh', 'tasks', f'{task_name}.yaml')

    # 如果中文版本也不存在（理论上不应该发生），返回空字典
    # 上层调用者需要处理空字典的情况
    if not os.path.exists(yaml_path):
        return {}

    try:
        # 使用 UTF-8 编码打开文件，确保中文字符正常读取
        with open(yaml_path, 'r', encoding='utf-8') as f:
            # yaml.safe_load 相比 yaml.load 更安全，不会执行任意 Python 代码
            return yaml.safe_load(f)
    except Exception as e:
        # 解析失败时打印警告但不抛出异常 —— 允许系统降级运行
        print(f"Warning: Failed to load task text from {yaml_path}: {e}")
        return {}


class BaseTask:
    """所有任务的基类

    封装了 CrewAI Task 的基本属性（agent、expected_output、description），
    提供 create_task() 方法创建 CrewAI Task 实例。
    子类可以覆盖 create_task() 以添加额外的逻辑（如上下文依赖、反馈信息等）。
    """

    def __init__(self, agent, expected_output, description):
        """初始化基础任务

        设置任务的核心三要素：
        - agent: 执行该任务的 AI Agent，决定了任务的执行风格和专业领域
        - expected_output: 期望的任务输出格式和内容说明
        - description: 详细的任务描述，引导 Agent 完成工作

        Args:
            agent: 负责执行该任务的 CrewAI Agent 实例
            expected_output: 期望输出格式的文本描述
            description: 任务描述文本
        """
        self.agent = agent
        self.expected_output = expected_output
        self.description = description

    def create_task(self):
        """创建并返回 CrewAI Task 实例

        使用当前对象的属性构建 Task 对象。
        CrewAI 框架会基于这个 Task 对象调度 Agent 执行任务。
        子类通常需要覆盖此方法以支持 context_task、feedback 等高级特性。

        Returns:
            Task: CrewAI 框架的 Task 实例
        """
        return Task(
            agent=self.agent,
            expected_output=self.expected_output,
            description=self.description
        )
