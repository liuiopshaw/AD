# 日志记录模块，用于输出加载过程中的调试和错误信息
import logging
# 操作系统接口模块，用于检查文件是否存在 (os.path.exists) 和读取环境变量 (os.getenv)
import os

# 配置本模块的日志记录器，设置日志级别为 WARNING
# 这样可以过滤掉 DEBUG/INFO 级别的日志，仅在出现警告或错误时才输出
logging.basicConfig(level=logging.WARNING)
# 获取当前模块的日志记录器，用于输出提示文件加载状态及错误信息
logger = logging.getLogger(__name__)


def get_language():
    """
    获取当前应用的语言设置。

    优先从项目的 Config 类中读取 LANGUAGE 配置项；如果 Config 不可用则回退到
    环境变量 LANGUAGE，最后默认使用 "zh"（中文）。

    Returns:
        str: 语言代码，如 "zh"（中文）或 "en"（英文）
    """
    try:
        # 尝试从项目的 Config 配置类中获取语言设定
        # 这是主配置源，用户可以通过修改 Config 来控制界面语言
        from src.config.config import Config
        return Config.LANGUAGE
    except Exception:
        # 如果 Config 不可用（例如在配置未初始化的早期阶段或测试环境中），
        # 则从操作系统的环境变量 LANGUAGE 中读取，默认值为 "zh"
        return os.getenv("LANGUAGE", "zh")


def load_prompt(file_path):
    """
    加载 Prompt 提示词文件，支持多语言。

    加载策略：
    1. 首先尝试从 `locales/{lang}/prompts/` 目录下加载当前语言版本的 Prompt 文件。
    2. 如果当前语言版本不存在且当前语言不是英文，则回退到 `locales/en/prompts/`
       加载英文版本，并记录 WARNING 日志（与 locales 模块的 en 回退策略一致）。
    3. 如果两个位置都找不到文件，则抛出 FileNotFoundError，由异常处理逻辑兜底。

    Args:
        file_path: Prompt 文件的相对路径（相对于 prompts 目录）

    Returns:
        str: Prompt 文件的文本内容；如果文件未找到则返回默认背景描述文本
    """
    try:
        # 获取当前语言设定，用于确定加载哪个语言版本的 Prompt
        lang = get_language()

        # 获取当前文件（prompt_loader.py）所在的绝对目录路径
        # 这是构建相对路径的基准点
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # 构建多语言 Prompt 文件的完整路径
        # 路径结构：src/locales/{语言}/prompts/{文件名}
        # 例如当 lang="zh" 时，路径为 src/locales/zh/prompts/{file_path}
        locale_prompt_path = os.path.join(current_dir, "..", "locales", lang, "prompts", file_path)

        # 检查多语言版本的 Prompt 文件是否存在
        if os.path.exists(locale_prompt_path):
            # 以 UTF-8 编码打开文件（确保中文字符正确处理）
            with open(locale_prompt_path, 'r', encoding='utf-8') as file:
                logger.debug(f"Loaded {lang} prompt: {file_path}")
                return file.read()  # 返回文件完整内容作为 Prompt 文本

        # 当前语言版本不存在时，回退到英文 Prompt 目录
        # 回退路径：src/locales/en/prompts/{file_path}
        # 注意：历史上此处回退到不存在的 src/prompts/ 目录，已修正为 en 目录回退
        if lang != "en":
            en_prompt_path = os.path.join(current_dir, "..", "locales", "en", "prompts", file_path)

            # 检查英文版本的 Prompt 文件是否存在
            if os.path.exists(en_prompt_path):
                with open(en_prompt_path, 'r', encoding='utf-8') as file:
                    logger.warning(
                        f"Prompt file {file_path} not found for language '{lang}', "
                        f"falling back to English version"
                    )
                    return file.read()

        # 两个位置都没有找到文件，抛出异常
        raise FileNotFoundError(f"Prompt file not found: {file_path}")

    except FileNotFoundError:
        # 文件未找到的异常处理：记录警告日志并返回默认的 Agent 背景描述
        # 这保证了即使 Prompt 文件缺失，系统仍能继续运行（优雅降级）
        logger.warning(f"Prompt file {file_path} not found, using default backstory")
        return get_default_backstory()
    except Exception as e:
        # 捕获所有其他异常（如编码错误、权限错误等），
        # 记录错误日志后返回默认背景描述，确保系统不会因加载 Prompt 失败而崩溃
        logger.error(f"Error occurred while loading Prompt file {file_path}: {str(e)}")
        return get_default_backstory()


def get_default_backstory():
    """
    获取 Agent 的默认背景描述文本。

    当 Prompt 文件加载失败时，此函数提供兜底的背景描述，使 Agent 仍能正常工作。
    目前中文和英文返回相同的文本内容——这是一个通用的专业项目协调专家角色描述。

    Returns:
        str: 默认的 Agent 背景描述文本
    """
    # 获取当前语言设定，以便未来为不同语言返回不同的默认文本
    lang = get_language()
    if lang == "en":
        # 英文版默认背景描述
        return """You are a professional project coordination expert, familiar with all aspects of material design and evaluation.
You can intelligently select and coordinate relevant experts to participate in the work according to task requirements."""
    else:
        # 中文及其他语言的默认背景描述（目前与英文相同）
        return """You are a professional project coordination expert, familiar with all aspects of material design and evaluation.
You can intelligently select and coordinate relevant experts to participate in the work according to task requirements."""
