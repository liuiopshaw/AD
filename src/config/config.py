# -*- coding: utf-8 -*-
# 第1行：指定源文件编码为 UTF-8，确保中文字符正常解析
import os
# 第3行：导入 os 模块，用于读取环境变量
from dotenv import load_dotenv
# 第4行：从 python-dotenv 库导入 load_dotenv 函数，用于加载 .env 文件中的环境变量

# 第6行：在模块级别立即加载 .env 文件中的环境变量到 os.environ
# 注意：此处加载时机较早，若后续 main.py 再次以 override=True 加载，此处设置的值可能被覆盖
load_dotenv()

class Config:
    # 第10行：定义 Config 配置类，所有配置项均为类属性，通过 os.getenv 从环境变量读取并设置默认值

    # --- Qwen3 模型配置 ---
    # 第13行：QWEN_API_BASE — DashScope API 端点地址
    # 默认使用国际端点 dashscope-intl.aliyuncs.com，避免国内/国际区域不匹配错误
    QWEN_API_BASE = os.getenv("QWEN_API_BASE", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    # 第15行：QWEN_API_KEY — DashScope API 密钥，无默认值，必须通过环境变量或 .env 文件设置
    QWEN_API_KEY = os.getenv("QWEN_API_KEY")
    # 第17行：QWEN_MODEL_NAME — 模型名称，默认使用 qwen-plus（稳定的商业模型，避免 thinking mode / streaming 兼容性错误）
    QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "qwen-plus")

    # --- OpenAI 兼容配置（CrewAI 框架依赖） ---
    # 第20行：OPENAI_API_BASE — CrewAI 内部使用的 OpenAI 兼容端点
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    # 第22行：OPENAI_API_KEY — CrewAI 内部使用的 API 密钥
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    # --- 外部科学数据库 API 配置 ---
    # 第25行：Materials Project 材料数据库 API 密钥（可选），用于查询晶体结构、能带等材料属性
    MATERIALS_PROJECT_API_KEY = os.getenv("MATERIALS_PROJECT_API_KEY")
    # 第28行：PubChem 化合物数据库 API 密钥（可选），用于查询化学安全性、毒性等信息
    PUBCHEM_API_KEY = os.getenv("PUBCHEM_API_KEY")
    # DrugBank 药理学数据库 API 密钥
    DRUGBANK_API_KEY = os.getenv("DRUGBANK_API_KEY", "")

    # --- LLaVA vLLM 本地模型服务端点 ---
    LLAVA_API_BASE = os.getenv("LLAVA_API_BASE", "http://localhost:8000/v1")
    LLAVA_MODEL_NAME = os.getenv("LLAVA_MODEL_NAME", "llava-1.6-13b-awq")

    # --- 数据库连接 ---
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

    # --- 本地实验数据库 ---
    LOCAL_EXP_DB_PATH = os.getenv("LOCAL_EXP_DB_PATH", "data/local_experiments.db")

    # --- 模型参数配置 ---
    # 第32行：MODEL_TEMPERATURE — 默认温度参数（0.0~1.0），控制输出随机性，默认 0.7
    MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.7"))
    # 第33行：MODEL_MAX_TOKENS — 最大输出 token 数，默认 2048
    MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "2048"))

    # --- 各 Agent 专用温度配置 ---
    # 材料设计专家使用较高温度 0.8，提高输出多样性以激发创新设计
    MATERIAL_DESIGNER_TEMPERATURE = float(os.getenv("MATERIAL_DESIGNER_TEMPERATURE", "0.8"))

    # 三位评估专家使用较低温度 0.3，确保评分的一致性和准确性
    EXPERT_A_TEMPERATURE = float(os.getenv("EXPERT_A_TEMPERATURE", "0.3"))
    EXPERT_B_TEMPERATURE = float(os.getenv("EXPERT_B_TEMPERATURE", "0.3"))
    EXPERT_C_TEMPERATURE = float(os.getenv("EXPERT_C_TEMPERATURE", "0.3"))

    # 最终验证专家使用适中温度 0.5，平衡综合判断的稳定性与灵活性
    FINAL_VALIDATOR_TEMPERATURE = float(os.getenv("FINAL_VALIDATOR_TEMPERATURE", "0.5"))

    # 其他专家（机理分析、合成指导、操作建议、文献处理）统一使用 0.3 的评估级温度
    MECHANISM_EXPERT_TEMPERATURE = float(os.getenv("MECHANISM_EXPERT_TEMPERATURE", "0.3"))
    SYNTHESIS_EXPERT_TEMPERATURE = float(os.getenv("SYNTHESIS_EXPERT_TEMPERATURE", "0.3"))
    OPERATION_SUGGESTING_TEMPERATURE = float(os.getenv("OPERATION_SUGGESTING_TEMPERATURE", "0.3"))
    LITERATURE_PROCESSOR_TEMPERATURE = float(os.getenv("LITERATURE_PROCESSOR_TEMPERATURE", "0.3"))

    # ---- 纳米生物评估系统新增智能体温度 ----
    APA_TEMPERATURE = float(os.getenv("APA_TEMPERATURE", "0.3"))
    EPA_TEMPERATURE = float(os.getenv("EPA_TEMPERATURE", "0.3"))
    BSA_TEMPERATURE = float(os.getenv("BSA_TEMPERATURE", "0.3"))
    MMA_TEMPERATURE = float(os.getenv("MMA_TEMPERATURE", "0.3"))
    CA_TEMPERATURE = float(os.getenv("CA_TEMPERATURE", "0.1"))

    # 向后兼容的统一评估温度配置
    EXPERT_EVALUATION_TEMPERATURE = float(os.getenv("EXPERT_EVALUATION_TEMPERATURE", "0.3"))

    # --- 迭代设计配置 ---
    # 最大设计迭代次数，默认 3 次，防止无限循环
    MAX_DESIGN_ITERATIONS = int(os.getenv("MAX_DESIGN_ITERATIONS", "3"))
    # 最低可接受评分（满分 10）
    MIN_ACCEPTABLE_SCORE = float(os.getenv("MIN_ACCEPTABLE_SCORE", "7.0"))

    # ---- 纳米生物评估评分权重 ----
    APA_WEIGHTS = {
        "potency": 0.40,
        "selectivity": 0.35,
        "spectrum": 0.15,
        "resistance_risk": 0.10
    }

    EPA_WEIGHTS = {
        "activity_strength": 0.65,
        "substrate_affinity": 0.25,
        "condition_window": 0.10
    }

    BSA_WEIGHTS = {
        "cytotoxicity": 0.30,
        "organ_damage": 0.25,
        "in_vivo_toxicity": 0.20,
        "environmental_risk": 0.15,
        "structural_stability": 0.10
    }

    # ---- 工作流 ----
    SCORE_PASS_THRESHOLD = float(os.getenv("SCORE_PASS_THRESHOLD", "7.0"))
    MAX_EXTRACTION_RETRIES = int(os.getenv("MAX_EXTRACTION_RETRIES", "3"))

    # --- 一致性分析配置 ---
    HIGH_CONSISTENCY_THRESHOLD = float(os.getenv("HIGH_CONSISTENCY_THRESHOLD", "1.0"))
    MEDIUM_CONSISTENCY_THRESHOLD = float(os.getenv("MEDIUM_CONSISTENCY_THRESHOLD", "2.0"))

    # --- 语言配置 ---
    # 第64行：LANGUAGE — 界面语言选择，"zh" 为中文，"en" 为英文
    LANGUAGE = os.getenv("LANGUAGE", "zh")

    # --- 其他配置 ---
    # 第67行：VERBOSE — 是否输出详细日志，从环境变量读取字符串后转为布尔值
    VERBOSE = os.getenv("VERBOSE", "True").lower() == "true"

    # --- EAS（弹性算法服务）模型配置（可选） ---
    # 第70行：EAS_ENDPOINT — 自部署模型的端点地址
    EAS_ENDPOINT = os.getenv("EAS_ENDPOINT")
    # 第71行：EAS_TOKEN — 自部署模型的认证令牌
    EAS_TOKEN = os.getenv("EAS_TOKEN")
    # 第72行：EAS_MODEL_NAME — 自部署模型的名称
    EAS_MODEL_NAME = os.getenv("EAS_MODEL_NAME")

    @classmethod
    def is_api_key_valid(cls, api_key):
        # 类方法，校验 API 密钥是否有效
        # 检查密钥非空且去除空白后仍有内容（strip() 为真已蕴含长度 > 0）
        return bool(api_key and api_key.strip())
