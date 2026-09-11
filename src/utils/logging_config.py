"""
统一日志配置模块 (Unified Logging Configuration)
为 ECOMATS 项目提供集中化的日志管理。
通过本模块可以统一控制所有日志的输出级别、格式和目标，
避免各模块各自配置日志导致的混乱。
"""

# 导入 Python 标准库的 logging 模块，用于日志记录
import logging
# 导入 sys 模块，用于访问标准输出流 (stdout)
import sys

# 需要抑制的 Agent 日志记录器列表
# 这些 Agent 运行时会产生大量调试/信息日志，在正常使用中不需要显示，
# 因此将它们集中管理以便一键静默，减少控制台输出噪音
AGENT_LOGGERS = [
    'src.agents.Creative_Designing_agent',
    'src.agents.Assessment_Screening_agent_A',
    'src.agents.Assessment_Screening_agent_B',
    'src.agents.Assessment_Screening_agent_C',
    'src.agents.Assessment_Screening_agent_Overall',
    'src.agents.Mechanism_Mining_agent',
    'src.agents.Synthesis_Guiding_agent',
    'src.agents.Operation_Suggesting_agent',
    'src.agents.task_organizing_agent',
    'src.agents.Extracting_agent',
]

# 需要抑制的第三方库日志记录器列表
# 这些第三方库（如 httpx, openai 等）会产生大量底层网络请求和调试日志，
# 默认设置为 WARNING 级别，避免干扰应用程序的主要日志输出
THIRD_PARTY_LOGGERS = [
    'httpx',          # HTTP 客户端库，每次请求都会产生大量 DEBUG 日志
    'openai',         # OpenAI API 客户端库
    'chromadb',       # 向量数据库客户端库
    'urllib3',        # HTTP 连接池库，底层网络日志
]


def setup_logging(level: int = logging.WARNING, suppress_agents: bool = True):
    """
    配置 ECOMATS 的统一日志系统。

    该函数应在应用启动时尽早调用，以建立一致的日志行为。

    Args:
        level: 根日志记录器的日志级别，默认为 WARNING。
               这意味着默认情况下只有 WARNING 及以上级别（ERROR, CRITICAL）的日志才会被输出。
        suppress_agents: 是否抑制各个 Agent 的日志输出，默认为 True。
                        当设为 True 时，所有 Agent 日志记录器会被设置为 CRITICAL 级别（基本不输出）。
    """
    # 配置根日志记录器的基本设置
    # basicConfig 是整个日志系统的入口配置，设置日志级别、输出格式和输出目标
    # 格式说明：%(asctime)s = 时间戳, %(name)s = 日志记录器名称,
    #           %(levelname)s = 日志级别名称, %(message)s = 日志消息
    logging.basicConfig(
        level=level,                                          # 设定根日志记录器的级别阈值
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # 统一的日志输出格式
        handlers=[logging.StreamHandler(sys.stdout)]           # 将日志输出到标准输出流
    )

    if suppress_agents:
        # 将所有 Agent 日志记录器的输出级别提升至 CRITICAL
        # CRITICAL 是最高级别，通常情况下 Agent 不会输出 CRITICAL 日志，
        # 因此这等同于静默了所有 Agent 的日志输出
        for logger_name in AGENT_LOGGERS:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL)

    # 将第三方库日志记录器的级别设为 WARNING
    # 这样只会在第三方库出现警告或错误时才有日志输出，
    # 而正常的请求/响应日志（DEBUG/INFO 级别）将被过滤
    for logger_name in THIRD_PARTY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    获取一个指定名称的日志记录器实例。

    这是各模块获取日志记录器的统一入口。推荐调用方式为 get_logger(__name__)，
    这样每个模块的日志记录器名称会自动映射其模块路径。

    Args:
        name: 日志记录器名称，通常传入 __name__（当前模块的完整路径名）

    Returns:
        logging.Logger: 已配置的日志记录器实例。如果此前已调用 setup_logging()，
                        则会继承根日志记录器的配置。
    """
    # getLogger 是幂等的：相同 name 会返回同一个 Logger 实例
    # 这样保证了同一模块内的日志设置一致性
    return logging.getLogger(name)
