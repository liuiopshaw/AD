# -*- coding: utf-8 -*-
# Line 1: specify the source file encoding as UTF-8 to ensure proper character parsing
import os
# Line 3: import the os module for reading environment variables
from dotenv import load_dotenv
# Line 4: import the load_dotenv function from the python-dotenv library to load environment variables from a .env file

# Line 6: immediately load environment variables from the .env file into os.environ at module level
# Note: this load happens early; if main.py later loads again with override=True, the values set here may be overwritten
load_dotenv()

class Config:
    # Line 10: define the Config class; all configuration items are class attributes read from environment variables via os.getenv with default values

    # --- Qwen3 model configuration ---
    # Line 13: QWEN_API_BASE — DashScope API endpoint address
    # Defaults to the international endpoint dashscope-intl.aliyuncs.com to avoid domestic/international region mismatch errors
    QWEN_API_BASE = os.getenv("QWEN_API_BASE", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    # Line 15: QWEN_API_KEY — DashScope API key; no default value, must be set via an environment variable or the .env file
    QWEN_API_KEY = os.getenv("QWEN_API_KEY")
    # Line 17: QWEN_MODEL_NAME — model name; defaults to qwen-plus (a stable commercial model, avoiding thinking mode / streaming compatibility errors)
    QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "qwen-plus")

    # --- OpenAI-compatible configuration (required by the CrewAI framework) ---
    # Line 20: OPENAI_API_BASE — OpenAI-compatible endpoint used internally by CrewAI
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    # Line 22: OPENAI_API_KEY — API key used internally by CrewAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    # --- External scientific database API configuration ---
    # Line 25: Materials Project materials database API key (optional), used to query material properties such as crystal structures and band structures
    MATERIALS_PROJECT_API_KEY = os.getenv("MATERIALS_PROJECT_API_KEY")
    # Line 28: PubChem compound database API key (optional), used to query chemical safety, toxicity, and related information
    PUBCHEM_API_KEY = os.getenv("PUBCHEM_API_KEY")
    # DrugBank pharmacology database API key
    DRUGBANK_API_KEY = os.getenv("DRUGBANK_API_KEY", "")

    # --- LLaVA vLLM local model server endpoint ---
    LLAVA_API_BASE = os.getenv("LLAVA_API_BASE", "http://localhost:8000/v1")
    LLAVA_MODEL_NAME = os.getenv("LLAVA_MODEL_NAME", "llava-1.6-13b-awq")

    # --- Database connection ---
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

    # --- Local experiment database ---
    LOCAL_EXP_DB_PATH = os.getenv("LOCAL_EXP_DB_PATH", "data/local_experiments.db")

    # --- Model parameter configuration ---
    # Line 32: MODEL_TEMPERATURE — default temperature parameter (0.0~1.0), controls output randomness; defaults to 0.7
    MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.7"))
    # Line 33: MODEL_MAX_TOKENS — maximum number of output tokens; defaults to 2048
    MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "2048"))

    # --- Agent-specific temperature configuration ---
    # The material design expert uses a higher temperature of 0.8 to increase output diversity and encourage innovative designs
    MATERIAL_DESIGNER_TEMPERATURE = float(os.getenv("MATERIAL_DESIGNER_TEMPERATURE", "0.8"))

    # The three evaluation experts use a lower temperature of 0.3 to ensure consistency and accuracy of scoring
    EXPERT_A_TEMPERATURE = float(os.getenv("EXPERT_A_TEMPERATURE", "0.3"))
    EXPERT_B_TEMPERATURE = float(os.getenv("EXPERT_B_TEMPERATURE", "0.3"))
    EXPERT_C_TEMPERATURE = float(os.getenv("EXPERT_C_TEMPERATURE", "0.3"))

    # The final validation expert uses a moderate temperature of 0.5, balancing stability and flexibility of comprehensive judgment
    FINAL_VALIDATOR_TEMPERATURE = float(os.getenv("FINAL_VALIDATOR_TEMPERATURE", "0.5"))

    # The other experts (mechanism analysis, synthesis guidance, operation suggestion, literature processing) uniformly use the evaluation-grade temperature of 0.3
    MECHANISM_EXPERT_TEMPERATURE = float(os.getenv("MECHANISM_EXPERT_TEMPERATURE", "0.3"))
    SYNTHESIS_EXPERT_TEMPERATURE = float(os.getenv("SYNTHESIS_EXPERT_TEMPERATURE", "0.3"))
    OPERATION_SUGGESTING_TEMPERATURE = float(os.getenv("OPERATION_SUGGESTING_TEMPERATURE", "0.3"))
    LITERATURE_PROCESSOR_TEMPERATURE = float(os.getenv("LITERATURE_PROCESSOR_TEMPERATURE", "0.3"))

    # ---- Temperatures for the newly added agents in the nano-bio evaluation system ----
    APA_TEMPERATURE = float(os.getenv("APA_TEMPERATURE", "0.3"))
    EPA_TEMPERATURE = float(os.getenv("EPA_TEMPERATURE", "0.3"))
    BSA_TEMPERATURE = float(os.getenv("BSA_TEMPERATURE", "0.3"))
    MMA_TEMPERATURE = float(os.getenv("MMA_TEMPERATURE", "0.3"))
    CA_TEMPERATURE = float(os.getenv("CA_TEMPERATURE", "0.1"))

    # Backward-compatible unified evaluation temperature configuration
    EXPERT_EVALUATION_TEMPERATURE = float(os.getenv("EXPERT_EVALUATION_TEMPERATURE", "0.3"))

    # --- Iterative design configuration ---
    # Maximum number of design iterations; defaults to 3 to prevent infinite loops
    MAX_DESIGN_ITERATIONS = int(os.getenv("MAX_DESIGN_ITERATIONS", "3"))
    # Minimum acceptable score (out of 10)
    MIN_ACCEPTABLE_SCORE = float(os.getenv("MIN_ACCEPTABLE_SCORE", "7.0"))

    # ---- Nano-bio evaluation scoring weights ----
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

    # ---- Workflow ----
    SCORE_PASS_THRESHOLD = float(os.getenv("SCORE_PASS_THRESHOLD", "7.0"))
    MAX_EXTRACTION_RETRIES = int(os.getenv("MAX_EXTRACTION_RETRIES", "3"))

    # --- Consistency analysis configuration ---
    HIGH_CONSISTENCY_THRESHOLD = float(os.getenv("HIGH_CONSISTENCY_THRESHOLD", "1.0"))
    MEDIUM_CONSISTENCY_THRESHOLD = float(os.getenv("MEDIUM_CONSISTENCY_THRESHOLD", "2.0"))

    # --- Language configuration ---
    # Line 64: LANGUAGE — interface language selection; "zh" for Chinese, "en" for English
    LANGUAGE = os.getenv("LANGUAGE", "zh")

    # --- Other configuration ---
    # Line 67: VERBOSE — whether to output detailed logs; the string read from the environment variable is converted to a boolean
    VERBOSE = os.getenv("VERBOSE", "True").lower() == "true"

    # --- EAS (Elastic Algorithm Service) model configuration (optional) ---
    # Line 70: EAS_ENDPOINT — endpoint address of the self-deployed model
    EAS_ENDPOINT = os.getenv("EAS_ENDPOINT")
    # Line 71: EAS_TOKEN — authentication token of the self-deployed model
    EAS_TOKEN = os.getenv("EAS_TOKEN")
    # Line 72: EAS_MODEL_NAME — name of the self-deployed model
    EAS_MODEL_NAME = os.getenv("EAS_MODEL_NAME")

    @classmethod
    def is_api_key_valid(cls, api_key):
        # Class method that validates whether an API key is valid
        # Checks that the key is non-empty and still has content after stripping whitespace (strip() being truthy already implies length > 0)
        return bool(api_key and api_key.strip())
