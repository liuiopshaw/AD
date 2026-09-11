#!/usr/bin/env python3
# 第1行：Shebang 声明，指定使用 python3 解释器执行此脚本
"""
LLM Configuration Tool.
Provides EAS model instance creation and CrewAI native LLM factory.
"""
# 第2-5行：模块文档字符串，说明本模块负责 LLM 配置，提供 EAS 模型实例创建和 CrewAI 原生 LLM 工厂函数

import os
# 第7行：导入 os 模块，用于读取和设置环境变量
from dotenv import load_dotenv
# 第8行：导入 load_dotenv，用于强制加载 .env 文件
from crewai import LLM as CrewLLM
# 第9行：从 CrewAI 框架导入 LLM 类并重命名为 CrewLLM，用于创建兼容 OpenAI 接口的 LLM 实例
from ..config.config import Config
# 第10行：从上级 config 包导入 Config 配置类，获取默认模型参数


def _ensure_openai_env():
    # 第13行：内部函数，确保只设置 DashScope 相关的环境变量
    # 目的：避免 OPENAI_* 环境变量与 DashScope 国内端点产生冲突
    """Disable bridging of OPENAI_* environment variables to avoid conflicts between domestic sites and OpenAI defaults."""
    # 第14行：函数文档字符串
    # 第16行：仅当 QWEN_API_KEY 存在且 DASHSCOPE_API_KEY 未设置时，将 QWEN_API_KEY 复制到 DASHSCOPE_API_KEY
    if Config.QWEN_API_KEY and not os.getenv("DASHSCOPE_API_KEY"):
        os.environ["DASHSCOPE_API_KEY"] = Config.QWEN_API_KEY


def _resolve_base_url():
    # 第20行：内部函数，解析可用的 base_url，严格使用 QWEN_API_BASE
    # 优先读取环境变量，其次使用 Config 类默认值
    """Resolve available base_url (strictly use QWEN_API_BASE)."""
    return os.getenv("QWEN_API_BASE") or Config.QWEN_API_BASE


def _resolve_api_key():
    # 第25行：内部函数，解析可用的 API 密钥
    # 按优先级依次尝试：QWEN_API_KEY → DASHSCOPE_API_KEY → Config.QWEN_API_KEY
    """Resolve available api_key (strictly use QWEN_API_KEY or DASHSCOPE_API_KEY)."""
    return os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or Config.QWEN_API_KEY

def _force_load_env():
    # 第29行：内部函数，从项目根目录强制加载 .env 文件（override=True）
    # 解决 IDE 或终端中环境变量不一致的问题
    try:
        # 第31行：计算项目根目录路径（当前文件位于 src/utils/，向上两级到项目根目录）
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        # 第32行：构建 .env 文件完整路径
        dotenv_path = os.path.join(project_root, '.env')
        # 第33行：以覆盖模式加载 .env 文件，确保文件中的值优先于当前环境变量
        load_dotenv(dotenv_path, override=True)
    except Exception:
        # 第34-35行：加载失败时静默忽略（如 .env 文件不存在）
        pass

def create_llm(temperature=None, max_tokens=None, agent_name=None):
    # 第37行：创建 CrewAI 原生 LLM 实例的工厂函数
    # 参数 temperature：模型温度（可选），控制输出随机性
    # 参数 max_tokens：最大输出 token 数（可选）
    # 参数 agent_name：LoRA 适配器名（可选），仅在显式配置 LLAVA_API_BASE 时生效，
    #   取值需与 scripts/llava_server.py 中的适配器名一致（ea/apa/epa/bsa/mma/toa/ca/cda/base）
    # 返回：配置好的 CrewLLM 实例
    """
    Create and configure language model instance (CrewAI native).

    Args:
        temperature (float, optional): Model temperature parameter, controlling output randomness
        max_tokens (int, optional): Maximum token limit
        agent_name (str, optional): LoRA adapter name; only used when LLAVA_API_BASE
            is explicitly set, passed to llava_server via the request body `agent` field

    Returns:
        CrewLLM: Configured language model instance
    """
    # 第48-49行：首先强制加载 .env 文件，确保环境变量为最新值
    _force_load_env()
    # 第51行：设置 DashScope 专用环境变量，避免 OPENAI_* 干扰
    _ensure_openai_env()

    # ---- LoRA 路由（可选，默认不改变现有行为） ----
    # 当且仅当环境变量 LLAVA_API_BASE 被显式设置（非空）时，将请求路由到
    # scripts/llava_server.py 提供的 OpenAI 兼容端点（FastAPI + PEFT 多适配器服务），
    # 使用 LLAVA_MODEL_NAME 作为模型名。注意直接读 os.getenv 而非 Config 类属性，
    # 因为 Config 为 LLAVA_API_BASE 提供了非空默认值，只有显式配置才应触发路由。
    # 服务端按请求体中的 agent 字段切换 LoRA 适配器：CrewAI 1.7.0+ 的 LLM 类
    # 支持 additional_params（会原样合并进 chat.completions 请求体），
    # 因此 agent_name 通过 additional_params 传给服务端；若当前 CrewAI 版本
    # 不支持 additional_params，则只接 base_url/model，服务端使用其默认适配器。
    llava_base = os.getenv("LLAVA_API_BASE")
    if llava_base:
        model_name = os.getenv("LLAVA_MODEL_NAME") or Config.LLAVA_MODEL_NAME
        llm_kwargs = dict(
            model=model_name,
            base_url=llava_base,
            # llava_server.py 不校验密钥，但 litellm 要求非空，
            # 优先复用已配置的 key，否则用占位值
            api_key=_resolve_api_key() or "EMPTY",
            temperature=temperature or Config.MODEL_TEMPERATURE,
            max_tokens=max_tokens or Config.MODEL_MAX_TOKENS,
        )
        if agent_name and "additional_params" in CrewLLM.model_fields:
            llm_kwargs["additional_params"] = {"agent": agent_name}
        elif agent_name:
            # 当前 CrewAI 版本不支持 additional_params：agent 字段无法传递，
            # 服务端将使用其默认适配器（llava_server.py 中默认 "ea"）
            pass
        return CrewLLM(**llm_kwargs)

    # 第54行：获取模型名称，默认为 "qwen-plus"（稳定的商业模型）
    model_name = Config.QWEN_MODEL_NAME or "qwen-plus"
    # 第55-56行：安全检查，如果模型名称为空则抛出异常
    if not model_name:
        raise ValueError("QWEN_MODEL_NAME not set in environment variables")
    # 第58行：解析 API 密钥
    api_key = _resolve_api_key()
    # 第59-60行：安全检查，如果密钥为空则抛出异常并提示配置方法
    if not api_key:
        raise ValueError("API key not detected, please set QWEN_API_KEY in .env or export OPENAI_API_KEY/DASHSCOPE_API_KEY")
    # 第61行：解析 base_url，尊重用户配置，不做任何端点改写
    base_url = _resolve_base_url()

    # 第68-74行：使用 CrewAI 原生 LLM 类创建实例
    # 参数说明：model=模型名称, base_url=API端点, api_key=密钥,
    # temperature=温度（优先使用传入值，否则用 Config 默认值）,
    # max_tokens=最大token数（优先使用传入值，否则用 Config 默认值）
    llm = CrewLLM(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature or Config.MODEL_TEMPERATURE,
        max_tokens=max_tokens or Config.MODEL_MAX_TOKENS,
    )

    # 第76行：返回配置完成的 LLM 实例
    return llm

def create_eas_llm(temperature=None):
    # 第78行：创建 EAS（弹性算法服务）自部署模型实例的工厂函数
    # EAS 是阿里云的模型托管服务，允许用户部署自定义模型
    # 参数 temperature：模型温度（可选）
    # 返回：配置好的 CrewLLM 实例，指向自部署的 EAS 端点
    """Create EAS model instance.

    Returns:
        CrewLLM: EAS model instance
    """
    # 第84-85行：首先强制加载 .env 文件
    _force_load_env()
    # 第87-88行：检查 EAS 必要配置是否存在，缺少任一项则抛出异常
    if not Config.EAS_ENDPOINT or not Config.EAS_TOKEN:
        raise ValueError("EAS config not set, please configure valid EAS_ENDPOINT and EAS_TOKEN in .env file")

    # 第91行：获取 EAS 模型名称
    model_name = Config.EAS_MODEL_NAME
    # 第92-93行：安全检查，模型名称不能为空
    if not model_name:
        raise ValueError("EAS_MODEL_NAME not set in environment variables")

    # 第96行：使用配置的 EAS 端点作为 base_url（不添加额外路径后缀）
    base_url = Config.EAS_ENDPOINT

    try:
        # 第101-108行：创建 EAS 模型实例
        # 使用 Config.EAS_TOKEN 作为 api_key，其余参数与 create_llm 一致
        eas_llm = CrewLLM(
            model=model_name,
            base_url=base_url,
            api_key=Config.EAS_TOKEN,
            temperature=temperature or Config.MODEL_TEMPERATURE,
            max_tokens=Config.MODEL_MAX_TOKENS,
        )
        # 第108行：返回 EAS LLM 实例
        return eas_llm
    except Exception as e:
        # 第109-111行：创建失败时打印错误信息并重新抛出异常
        print(f"Failed to create EAS model instance: {e}")
        raise

def tools_enabled() -> bool:
    # 第113行：判断是否启用工具调用的函数
    # 返回值：True 表示启用工具调用，False 表示禁用
    # 逻辑：
    # 1. 如果环境变量 ENABLE_TOOLS 已设置，直接返回其布尔值
    # 2. 如果使用 DashScope 兼容模式端点，默认禁用（因为兼容模式不支持 function calling）
    # 3. 其他情况默认启用
    """Determine whether to enable tool calls based on endpoint and environment variables.
    - If `ENABLE_TOOLS=false` is set, disable
    - If endpoint is DashScope compatible mode (contains `dashscope` and `compatible-mode`), disable by default
    - Otherwise enable by default.
    """
    # 第119行：读取 ENABLE_TOOLS 环境变量
    env = os.getenv("ENABLE_TOOLS")
    # 第120-121行：如果该变量已设置，返回其布尔值（"true" → True, 其他 → False）
    if env is not None:
        return env.lower() == "true"
    # 第122行：获取当前使用的 base_url
    base = _resolve_base_url() or ""
    # 第123-124行：如果端点 URL 同时包含 "dashscope" 和 "compatible-mode"，说明是 DashScope 兼容模式
    # 此模式不支持原生的 function calling，因此默认禁用工具调用，避免 500 错误
    if "dashscope" in base and "compatible-mode" in base:
        return False
    # 第125行：其他端点默认启用工具调用
    return True
