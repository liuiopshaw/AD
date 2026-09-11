"""
ECOMATS
Multilingual support module for ECOMATS

ECOMATS 多语言支持模块。
负责管理系统的多语言功能，包括文本获取、提示词加载和语言切换。
通过语言代码（zh/en）动态路由到对应语言的数据。

Supported languages:
- zh: (Chinese)
- en: English

Usage:
    from src.locales import get_text, get_prompt_path, set_language

    Set language
    set_language("zh")  # or "en"

    Get text
    text = get_text("tasks", "design_task", "description")

    Get prompt file path
    path = get_prompt_path("material_designer_prompt.md")
"""

import os
# 导入 os 模块，用于处理文件路径和检测文件是否存在
from typing import Optional
# 导入 Optional 类型提示（当前模块未直接使用，但为未来扩展保留）

# Default language
# 默认语言设置为中文（zh），因为项目主要面向中文用户
_current_language = "zh"

# Supported languages
# 支持的语言列表：中文和英文
SUPPORTED_LANGUAGES = ["zh", "en"]

# Module root directory
# 获取当前模块所在目录的绝对路径
# 此路径用于后续定位各语言的提示词文件和文本数据
LOCALES_DIR = os.path.dirname(os.path.abspath(__file__))


def set_language(lang: str) -> None:
    """
    Set current language
    设置当前使用的语言。

    切换语言后，所有 get_text() 调用将从新语言的字典中取文本。

    Args:
        lang: Language code ("zh" or "en")
        lang: 语言代码（"zh" 表示中文, "en" 表示英文）
    """
    global _current_language  # 声明修改模块级全局变量
    # 验证语言代码是否在支持列表中，无效代码抛出异常阻止设置
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {lang}. Supported: {SUPPORTED_LANGUAGES}")
    _current_language = lang  # 更新当前语言设置


def get_language() -> str:
    """
    Get current language
    获取当前设置的语言代码。

    Returns:
        Current language code
        str: 当前语言代码（"zh" 或 "en"）
    """
    return _current_language


def get_prompt_path(prompt_name: str) -> str:
    """
    Get prompt file path
    获取提示词文件路径。

    优先从当前语言目录下查找提示词文件，若不存在则回退到默认的 prompts 目录。
    这种回退机制保证了某些提示词未翻译时仍能找到默认版本。

    Args:
        prompt_name: Prompt filename
        prompt_name: 提示词文件名（如 "material_designer_prompt.md"）

    Returns:
        Full path to prompt file
        str: 提示词文件的完整路径
    """
    # 按当前语言构建路径，例如：locales/zh/prompts/material_designer_prompt.md
    path = os.path.join(LOCALES_DIR, _current_language, "prompts", prompt_name)

    # Fallback to default prompts directory if not found
    # 如果当前语言的提示词文件不存在，回退到 src/prompts/ 默认目录
    if not os.path.exists(path):
        fallback_path = os.path.join(os.path.dirname(LOCALES_DIR), "prompts", prompt_name)
        if os.path.exists(fallback_path):
            return fallback_path  # 返回默认路径

    # 返回当前语言路径（即使不存在也返回，由调用方处理缺失问题）
    return path


def get_text(category: str, key: str, field: str) -> str:
    """
    Get localized text
    获取本地化文本。

    根据当前语言从 TEXTS 字典的三级结构（category -> key -> field）中查找对应文本。
    查找失败时依次回退：当前语言 -> 中文（默认语言） -> 占位符字符串。

    Args:
        category: Text category
        category: 文本类别（如 "agents", "tasks", "ui"）
        key: Text key
        key: 文本键（如 "design_task", "material_designer"）
        field: Field name
        field: 字段名（如 "description", "role", "goal"）

    Returns:
        Localized text
        str: 本地化后的文本字符串
    """
    # 延迟导入 TEXTS 字典，避免循环导入（texts.py 可能引用此模块）
    from src.locales.texts import TEXTS

    lang = _current_language  # 获取当前语言
    try:
        # 尝试从当前语言的三级字典中查找文本
        return TEXTS[lang][category][key][field]
    except KeyError:
        # 当前语言未找到，尝试回退到中文（zh）作为默认语言
        try:
            return TEXTS["zh"][category][key][field]
        except KeyError:
            # 中文也找不到时返回占位符，帮助开发者快速定位缺失的文本条目
            return f"[Missing text: {category}.{key}.{field}]"


def load_prompt(prompt_name: str) -> str:
    """
    Load prompt file content.
    Delegates to utils.prompt_loader for unified implementation.
    加载提示词文件内容。
    委托给 utils.prompt_loader 模块进行统一实现，避免多语言模块与工具模块重复编写文件读取逻辑。

    Args:
        prompt_name: prompt filename
        prompt_name: 提示词文件名

    Returns:
        prompt content
        str: 提示词文件的完整文本内容
    """
    # 延迟导入并调用统一的提示词加载函数
    from src.utils.prompt_loader import load_prompt as _load_prompt
    return _load_prompt(prompt_name)
