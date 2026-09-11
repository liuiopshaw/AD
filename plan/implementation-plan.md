# 纳米生物评估系统 实现计划

> **面向执行者：** 请使用 subagent-driven-development 或 executing-plans 技能逐任务实现本计划。步骤使用 `- [ ]` 勾选语法跟踪进度。

**目标：** 构建一个多智能体系统，预测无机纳米材料的抗菌性能、类酶活性和生物安全性，并生成多材料横向对比报告。

**技术路线：** 7 个基于 LLaVA-1.6-13B 的智能体运行在 CrewAI 框架上。EA 提取结构化数据 → TOA 识别用户意图 → APA/EPA/BSA/MMA 四位专家并行评估 → CA 用一致性系数融合评分并生成对比报告。Neo4j 知识图谱 + 10 个领域工具 + 4 个外部 API。

**技术栈：** Python 3.11+, CrewAI 1.7.0, LLaVA-1.6-13B (AWQ 4-bit 量化), vLLM 0.6+, Neo4j 5.x, SQLite, LoRA (LLaMA-Factory)

## 全局约束

- 所有智能体通过 ContextStore（线程安全的共享字典，带可重入锁保护）传递数据
- 温度设置: EA=0.1, TOA=0.1, APA/EPA/BSA/MMA=0.3, CA=0.1
- 评分权重: APA(40/25/15/10/10), EPA(45/20/15/10/10), BSA(30/25/20/15/10)
- 一致性系数公式: Cj = 1 − (1/3)∑(Wij − W̄j)² / W̄j
- APA/EPA/BSA/MMA 必须设置 async_execution=True 并行执行
- 所有外部 API 调用超时 30 秒，重试 2 次
- 评分通过阈值: Sj ≥ 7.0

---

## 文件结构

```
ECOMATS/
├── plan/
│   └── project-overview.html          # [新建] 面向领域专家的中文HTML总览
├── src/
│   ├── agents/
│   │   ├── base_agent.py              # [修改] 扩展以接受图像输入
│   │   ├── extracting_agent.py        # [修改] 纳米领域提取提示词
│   │   ├── task_organizing_agent.py   # [修改] 新增意图模式
│   │   ├── antimicrobial_agent.py     # [新建] APA 抗菌性能预测
│   │   ├── enzyme_activity_agent.py   # [新建] EPA 类酶活性预测
│   │   ├── biosafety_agent.py         # [新建] BSA 生物安全性评估
│   │   ├── mechanism_mining_agent.py  # [修改] 适配纳米-生物机理
│   │   └── comparison_agent.py        # [新建] CA 多材料横向对比
│   ├── config/
│   │   └── config.py                  # [修改] 新增智能体配置与API密钥
│   ├── tasks/
│   │   ├── extraction_task.py         # [修改] 纳米领域提取任务
│   │   ├── antimicrobial_task.py      # [新建] APA 任务定义
│   │   ├── enzyme_activity_task.py    # [新建] EPA 任务定义
│   │   ├── biosafety_task.py          # [新建] BSA 任务定义
│   │   ├── mechanism_analysis_task.py # [修改] 适配纳米酶机理
│   │   └── comparison_task.py         # [新建] CA 对比任务
│   ├── tools/
│   │   ├── pubchem_tool.py            # [修改] 扩展纳米-生物端点查询
│   │   ├── drugbank_tool.py           # [新建] DrugBank REST API 封装
│   │   ├── materials_project_tool.py  # [复用] 从 ECOMATS 扩展纳米查询
│   │   ├── nanolit_search_tool.py     # [新建] PubMed + 本地文献检索
│   │   ├── local_expdb_tool.py        # [新建] SQLite 本地实验数据库查询
│   │   ├── pnec_retriever.py          # [新建] 预测无效应浓度检索
│   │   ├── ecosar_predictor.py        # [新建] ECOSAR 毒性估算
│   │   ├── enzyme_classifier.py       # [新建] 结构→酶活性规则引擎
│   │   ├── material_compare.py        # [新建] 多材料对比矩阵
│   │   └── kg_browser.py              # [修改] 扩展KG模式适配纳米-生物
│   ├── prompts/
│   │   ├── antimicrobial_agent_prompt.md     # [新建]
│   │   ├── enzyme_activity_agent_prompt.md   # [新建]
│   │   ├── biosafety_agent_prompt.md         # [新建]
│   │   └── comparison_agent_prompt.md        # [新建]
│   ├── utils/
│   │   ├── context_store.py           # [复用] 线程安全共享字典（不改）
│   │   ├── assessment_scoring_logic.py # [修改] 实现Cj公式与新权重
│   │   └── llm_config.py              # [修改] 切换到 vLLM 本地端点
│   └── locales/
│       └── texts.py                   # [修改] 新增界面文本
├── scripts/
│   ├── main.py                        # [修改] 新增纳米-生物工作流模式
│   ├── main_async.py                  # [修改] 新增纳米-生物异步工作流
│   └── workflow/
│       ├── embeddings.py              # [复用]
│       ├── callback_factory.py        # [复用]
│       └── patches.py                 # [复用] CrewAI 兼容性补丁
├── data/
│   ├── knowledge_graph/
│   │   └── schema.cypher              # [新建] 纳米-生物领域Neo4j模式
│   ├── training/
│   │   ├── ea_training_data.jsonl     # [新建] 提取训练数据
│   │   ├── apa_training_data.jsonl    # [新建] 抗菌预测训练数据
│   │   ├── epa_training_data.jsonl    # [新建] 酶活分类训练数据
│   │   ├── bsa_training_data.jsonl    # [新建] 安全评估训练数据
│   │   ├── mma_training_data.jsonl    # [新建] 机理推理训练数据
│   │   ├── toa_training_data.jsonl    # [新建] 意图识别训练数据
│   │   └── ca_training_data.jsonl     # [新建] 对比汇总训练数据
│   ├── literature/
│   │   └── curated_nano_bio.json      # [新建] 预提取文献记录
│   ├── local_experiments_db_init.py   # [新建] 本地实验库建表
│   └── enzyme_classification_rules.json # [新建] 酶活性分类规则
├── finetune/
│   ├── train_lora.py                  # [新建] LoRA 微调主脚本
│   ├── configs/
│   │   ├── ea_config.yaml             # [新建] EA 训练配置
│   │   ├── apa_config.yaml            # [新建] APA 训练配置
│   │   ├── epa_config.yaml            # [新建] EPA 训练配置
│   │   ├── bsa_config.yaml            # [新建] BSA 训练配置
│   │   ├── mma_config.yaml            # [新建] MMA 训练配置
│   │   ├── toa_config.yaml            # [新建] TOA 训练配置
│   │   └── ca_config.yaml             # [新建] CA 训练配置
│   └── prepare_data.py                # [新建] 训练数据准备流水线
└── requirements.txt                   # [修改] 新增依赖
```

---

## 阶段 0：环境搭建

### 任务 0.1：安装项目依赖

**涉及文件：**
- 修改: `requirements.txt`

**接口：**
- 产出: 通过 `pip install -r requirements.txt` 一键安装所有依赖

```text
# 核心框架
crewai>=1.7.0
litellm>=1.40.0
dashscope>=1.14.0

# 模型服务
vllm>=0.6.0
autoawq>=0.2.0

# 数据库
neo4j>=5.20.0
psycopg2-binary>=2.9.9

# 微调 (LLaMA-Factory)
llamafactory>=0.9.0
peft>=0.11.0
bitsandbytes>=0.43.0

# API 客户端
httpx>=0.27.0
requests>=2.31.0

# 数据处理
pandas>=2.2.0
numpy>=1.26.0
pydantic>=2.7.0

# 分子与化学
pubchempy>=1.0.4
rdkit>=2024.03.0

# 可视化
matplotlib>=3.8.0

# 通用工具
python-dotenv>=1.0.0
PyYAML>=6.0
```

---

### 任务 0.2：配置模块扩展

**涉及文件：**
- 修改: `src/config/config.py`

**新增配置项：**

```python
# ---- LLaVA vLLM 服务端点 ----
LLAVA_API_BASE = os.getenv('LLAVA_API_BASE', 'http://localhost:8000/v1')
LLAVA_MODEL_NAME = os.getenv('LLAVA_MODEL_NAME', 'llava-1.6-13b-awq')

# ---- 外部数据库 ----
NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.getenv('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '')
DRUGBANK_API_KEY = os.getenv('DRUGBANK_API_KEY', '')

# ---- 本地实验数据库 ----
LOCAL_EXP_DB_PATH = os.getenv('LOCAL_EXP_DB_PATH', 'data/local_experiments.db')

# ---- 智能体温度参数 ----
APA_TEMPERATURE = 0.3
EPA_TEMPERATURE = 0.3
BSA_TEMPERATURE = 0.3
MMA_TEMPERATURE = 0.3
CA_TEMPERATURE = 0.1

# ---- 评估权重 ----
APA_WEIGHTS = {
    'potency': 0.40,      # 杀菌效力
    'selectivity': 0.25,  # 杀-益选择性
    'spectrum': 0.15,     # 广谱性
    'speed': 0.10,        # 作用速度
    'resistance_risk': 0.10  # 抗药性风险
}

EPA_WEIGHTS = {
    'activity_strength': 0.45,       # 活性强度
    'multi_function': 0.20,          # 多酶功能数量
    'substrate_affinity': 0.15,      # 底物亲和性
    'condition_window': 0.10,        # 条件适用窗口
    'literature_corroboration': 0.10 # 文献佐证
}

BSA_WEIGHTS = {
    'cytotoxicity': 0.30,        # 细胞毒性
    'gut_safety': 0.25,          # 肠道安全性
    'in_vivo_toxicity': 0.20,    # 体内毒性
    'environmental_risk': 0.15,  # 环境风险
    'structural_stability': 0.10 # 结构稳定性
}

# ---- 工作流 ----
SCORE_PASS_THRESHOLD = 7.0
MAX_EXTRACTION_RETRIES = 3
```

---

### 任务 0.3：Neo4j 知识图谱建表

**涉及文件：**
- 新建: `data/knowledge_graph/schema.cypher`

**核心节点与关系：**

```cypher
// 节点约束（保证唯一性）
CREATE CONSTRAINT material_name IF NOT EXISTS
FOR (m:Material) REQUIRE m.name IS UNIQUE;

CREATE CONSTRAINT bacterium_name IF NOT EXISTS
FOR (b:Bacterium) REQUIRE b.name IS UNIQUE;

CREATE CONSTRAINT enzyme_class_name IF NOT EXISTS
FOR (e:EnzymeClass) REQUIRE e.name IS UNIQUE;

CREATE CONSTRAINT source_id IF NOT EXISTS
FOR (s:ExperimentalSource) REQUIRE s.source_id IS UNIQUE;

// Material 节点属性:
//   name, type(metal_np/metal_oxide/carbon/qd),
//   size_nm, zeta_potential_mv, shape, coating, characterization_methods

// Bacterium 节点属性:
//   name, gram_stain, genus, is_probiotic, is_pathogen

// EnzymeClass 节点属性:
//   name(OXD_like/POD_like/CAT_like/SOD_like),
//   natural_benchmark_enzyme, typical_km_range

// ToxicityEndpoint 节点属性:
//   name, endpoint_type, unit, species, cell_line

// 关系类型: HAS_COMPOSITION, INHIBITS, PROMOTES,
//           EXHIBITS, GENERATES_ROS, HAS_TOXICITY, CITED_IN

// 关系属性示例:
// INHIBITS { MIC_value, MBC_value, pH, temperature }
// EXHIBITS { activity_level, Km, Vmax, pH_optimal }
// GENERATES_ROS { ROS_type, detection_method }
// HAS_TOXICITY { value, unit, cell_line }

CREATE INDEX inhibits_mic IF NOT EXISTS
FOR ()-[r:INHIBITS]-() ON (r.MIC_value);

CREATE INDEX exhibits_level IF NOT EXISTS
FOR ()-[r:EXHIBITS]-() ON (r.activity_level);
```

---

## 阶段 1：领域工具（自底向上构建）

### 任务 1.1：PubChem 工具扩展

**涉及文件：** 修改 `src/tools/pubchem_tool.py`

**新增方法签名：**
- `query_toxicity_endpoints(cid: int) → dict` — 查询急性毒性、细胞毒性、生态毒性
- `query_bioactivity(cid: int) → dict` — 查询生物活性测定结果
- `query_element_properties(element_symbol: str) → dict` — 查询元素基本化学属性

**实现要点：**
1. 使用 PubChem PUG REST API 的 `pug_view/data/compound/{cid}/JSON` 端点
2. 递归遍历返回 JSON 的 Section 树，匹配已知的毒性数据标题模式（LD50、IC50、EC50等）
3. 当 API 超时或返回错误时返回空字典，不阻断主流程

**测试：**
```python
def test_query_toxicity_endpoints():
    tool = PubChemTool()
    # Aspirin CID 2244 有丰富的毒性数据
    result = tool.query_toxicity_endpoints(2244)
    assert isinstance(result, dict)
    assert 'ld50_oral_rat' in result
```

---

### 任务 1.2：DrugBank API 工具

**涉及文件：** 新建 `src/tools/drugbank_tool.py`

**方法签名：**
- `run(query: str, query_type: str) → dict`
  - `query_type='gut_metabolism'` → 查询肠道菌群代谢通路
  - `query_type='enzyme_benchmark'` → 查询天然酶动力学参数（Km, kcat, 最优pH/温度）
  - `query_type='drug_microbiome'` → 查询已知药物-菌群互作记录

**实现要点：**
1. 使用 Bearer Token 认证，请求头: `Authorization: Bearer {DRUGBANK_API_KEY}`
2. 两步查询：先 `/search?q={query}&type=compound` 找 drugbank_id，再 `/compounds/{id}` 取详情
3. 肠道菌群代谢数据从 `metabolism.pathways[].enzymes[]` 中筛选 location 含 "gut" 或 "microbiota" 的条目
4. 天然酶参照数据从 `/search?q={enzyme_name}&type=enzyme` → `/enzymes/{id}` 获取 kinetic_parameters

**测试：**
```python
def test_query_enzyme_benchmark_structure():
    tool = DrugBankTool()
    # 无API key时 _make_request 返回 None → 优雅降级
    result = tool.query_enzyme_benchmark("Catalase")
    assert result["enzyme"] == "Catalase"
    assert "km_value" in result
    assert result["source"] == "DrugBank"
```

---

### 任务 1.3：本地实验数据库工具

**涉及文件：** 新建 `src/tools/local_expdb_tool.py`, `data/local_experiments_db_init.py`

**数据库表结构（SQLite）：**

```sql
-- 材料信息表
CREATE TABLE materials (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,       -- metal_np, metal_oxide, carbon, qd
    core_element TEXT,
    coating TEXT,
    size_mean_nm REAL,
    zeta_potential_mv REAL,
    shape TEXT,
    synthesis_method TEXT
);

-- 抗菌测定表
CREATE TABLE antibacterial_assays (
    id INTEGER PRIMARY KEY,
    material_id INTEGER REFERENCES materials(id),
    bacterium_name TEXT NOT NULL,
    is_probiotic INTEGER DEFAULT 0,
    MIC_ug_ml REAL,
    MBC_ug_ml REAL,
    log_reduction REAL,
    time_to_99pct_kill_min REAL,
    pH REAL, temperature_C REAL,
    assay_method TEXT,
    biological_replicates INTEGER DEFAULT 3
);

-- 类酶活性测定表
CREATE TABLE enzyme_activity_assays (
    id INTEGER PRIMARY KEY,
    material_id INTEGER REFERENCES materials(id),
    enzyme_type TEXT NOT NULL,  -- OXD_like, POD_like, CAT_like, SOD_like
    activity_level TEXT,        -- Strong, Moderate, Weak, None
    km_value REAL, vmax_value REAL,
    substrate TEXT,
    pH_optimal REAL, temp_optimal_C REAL,
    ros_type_detected TEXT,
    detection_method TEXT
);

-- 毒性/安全性测定表
CREATE TABLE toxicity_assays (
    id INTEGER PRIMARY KEY,
    material_id INTEGER REFERENCES materials(id),
    endpoint_type TEXT NOT NULL,  -- cytotoxicity, hemolysis, in_vivo, eco
    cell_line_or_organism TEXT,
    ic50_ug_ml REAL,
    ld50_mg_kg REAL,
    hemolysis_rate_pct REAL,
    assay_method TEXT
);
```

**工具类 LocalExpDBTool 方法：**
- `run(query: str, query_type: str) → dict`
  - `query_type='material_info'` → 按名称模糊匹配材料信息
  - `query_type='antibacterial'` → 查询材料的抗菌测定数据
  - `query_type='enzyme_activity'` → 查询材料的类酶活性数据
  - `query_type='toxicity'` → 查询材料的毒性/安全性数据

---

### 任务 1.4：酶活性分类规则引擎

**涉及文件：** 新建 `src/tools/enzyme_classifier.py`, `data/enzyme_classification_rules.json`

**实现原理：** 基于文献提取的结构-活性关系（SAR, Structure-Activity Relationship）构建规则引擎，而非机器学习模型——完全可解释、可审计。

**规则结构（JSON）：**
```json
{
  "rules": [
    {
      "rule_id": "POD_001",
      "enzyme_type": "POD_like",
      "conditions": {
        "core_elements": ["Fe", "Cu", "Co", "Mn", "V", "Ru", "Ir", "Pt"],
        "band_gap_ev": {"min": 0.3, "max": 3.0},
        "size_nm": {"max": 200},
        "requires_h2o2": true
      },
      "confidence_boosters": [
        "Fenton or Fenton-like activity",
        "Fe3+/Fe2+ redox couple",
        "peroxidase substrate oxidation observed"
      ],
      "reference_pmids": ["34031467", "34819556"]
    },
    // ... OXD_like, CAT_like, SOD_like 规则
  ],
  "element_toxicity_flags": {
    "Ag": "ion_leaching_risk",
    "Cu": "moderate_ion_leaching",
    "Fe": "generally_biocompatible",
    "Ce": "low_biosolubility"
  }
}
```

**Classifier.run(material_properties: dict) → dict** 逻辑：
1. 遍历每条规则，按条件逐项匹配（核心元素 → 带隙 → 粒径）
2. 对每条匹配计算置信度 = 匹配分 / 总分
3. 置信度 ≥ 0.3 的酶类型纳入预测结果
4. 附加元素毒性标签（Ag → 离子溶出风险, Fe → 通常生物相容等）

---

## 阶段 2：智能体实现

### 任务 2.1：抗菌性能预测智能体（APA）

**涉及文件：** 新建 `src/agents/antimicrobial_agent.py`, `src/prompts/antimicrobial_agent_prompt.md`, `src/tasks/antimicrobial_task.py`

**关键代码：**
```python
class AntimicrobialAgent(BaseAgent):
    def __init__(self, llm):
        super().__init__(
            llm=llm,
            role="Antimicrobial_Prediction_Agent",
            goal="Predict antibacterial performance of nanomaterials against gut microbiota, including MIC, selectivity, spectrum, and resistance risk",
            prompt_file="antimicrobial_agent_prompt.md",
            temperature=Config.APA_TEMPERATURE,
            max_iter=1
        )

    def create_agent(self):
        agent = super().create_agent()
        # 绑定工具
        agent.tools = [
            ToolFactory.create("pubchem_query"),
            ToolFactory.create("materials_project_query"),
            ToolFactory.create("nanolit_search"),
            ToolFactory.create("local_expdb"),
            ToolFactory.create("kg_browser")
        ]
        return agent
```

**提示词关键段落：**
```
你是一位纳米抗菌材料评估专家。你的任务是分析某种纳米材料对肠道菌群的抗菌性能。

请按以下五个维度评估，每个维度给出 1-10 分的评分和理由：

1. **杀菌效力**（40%）：MIC50、MBC、对数减少值。评分标准：
   - 9-10 分: MIC < 10 μg/mL
   - 7-8 分: MIC 10-50 μg/mL
   - 5-6 分: MIC 50-200 μg/mL
   - 3-4 分: MIC 200-1000 μg/mL
   - 1-2 分: MIC > 1000 μg/mL

2. **病原菌-益生菌选择性**（25%）：MIC(致病菌)/MIC(益生菌) 比值
3. **抗菌谱广度**（15%）：覆盖的G+和G-菌种数量
4. **作用速度**（10%）：达到99%杀菌所需时间
5. **耐药性风险**（10%）：是否诱导耐药基因表达的证据

最终输出 JSON 格式的评分表。
```

---

### 任务 2.2：类酶活性预测智能体（EPA）

**涉及文件：** 新建 `src/agents/enzyme_activity_agent.py`, `src/prompts/enzyme_activity_agent_prompt.md`, `src/tasks/enzyme_activity_task.py`

EPA 与 APA 结构相同，角色改为 "Enzyme_Activity_Prediction_Agent"，绑定 DrugBank 和 EnzymeClassifier 工具，提示词替换为五维酶活性评估（活性强度45%、多功能性20%、底物亲和性15%、条件窗口10%、文献佐证10%）。

---

### 任务 2.3：生物安全性评估智能体（BSA）

**涉及文件：** 新建 `src/agents/biosafety_agent.py`, `src/prompts/biosafety_agent_prompt.md`, `src/tasks/biosafety_task.py`

BSA 绑定 PubChem（毒性端点）、PNECRetriever、ECOSARPredictor、NanoLitSearch 工具。

---

### 任务 2.4：机理挖掘智能体适配（MMA）

**涉及文件：** 修改 `src/agents/mechanism_mining_agent.py`

将原有 ECOMATS 的 PMS 催化机理提示词替换为纳米材料-菌群-类酶机理提示词：

```
你是一位纳米生物效应机理分析专家。

请从以下角度分析材料的作用机理：

1. **抗菌机理路径：**
   - ROS 路径（•OH, O₂•⁻, ¹O₂, H₂O₂ 哪种主导？）
   - 物理损伤（膜破裂、纳米刀效应）
   - 金属离子释放毒性
   - 电子转移扰断（电子呼吸链阻断）

2. **类酶活性机理：**
   - 活性位点化学环境（配位构型、氧化态）
   - 底物结合模式（与天然酶的类比）
   - 电子转移路径（从底物到材料的电荷迁移）
   - pH/温度对活性的分子级解释

3. **构效关系总结：**
   - 粒径为什么影响活性？
   - 包覆层（如环糊精）的调控作用
   - 晶面暴露与活性的关联
```

---

### 任务 2.5：多材料对比汇总智能体（CA）

**涉及文件：** 新建 `src/agents/comparison_agent.py`, `src/prompts/comparison_agent_prompt.md`, `src/utils/assessment_scoring_logic.py`

**CA 的核心逻辑：**

1. 收集 APA、EPA、BSA 三个维度的加权评分
2. 用一致性系数融合：
   ```python
   def calculate_comprehensive_score(scores_A: list, scores_B: list, scores_C: list) -> float:
       """S_j = W̄_j × C_j"""
       avg = sum(scores_A + scores_B + scores_C) / 3
       # 计算三个专家间的方差
       variance = sum((s - avg) ** 2 for s in [sum(scores_A)/5, sum(scores_B)/5, sum(scores_C)/5]) / 3
       C_j = 1 - variance / avg if avg != 0 else 0
       W_bar = avg
       return W_bar * C_j
   ```
3. 生成对比矩阵（行=材料，列=维度+综合分）
4. 输出雷达图数据（JSON 格式，前端可用 Chart.js 渲染）
5. 给出文字结论（为什么某材料综合最优）

---

### 任务 2.6：知识抽取智能体适配（EA）

**涉及文件：** 修改 `src/agents/extracting_agent.py`

适配要点：
- 提示词从 "提取催化剂参数" 改为 "提取纳米材料理化参数、抗菌数据、酶活数据、安全性数据"
- 工具从 PMS 相关改为 PubChem + DrugBank + Materials Project + 本地实验库 + PubMed
- 输出 JSON schema 新增字段：band_gap_ev, zeta_potential_mv, hydrodynamic_diameter_nm, coating_material, enzyme_activity_type

---

### 任务 2.7：任务调度智能体适配（TOA）

**涉及文件：** 修改 `src/agents/task_organizing_agent.py`

新增意图识别模式：
```python
INTENT_PATTERNS = {
    "comparison": ["对比", "比较", "compare", "vs", "横向"],
    "single_analysis": ["分析", "评估", "analyze", "evaluate"],
    "mechanism_only": ["机理", "机制", "mechanism", "pathway"],
    "safety_only": ["安全性", "毒性", "safety", "toxicity"],
    "enzyme_only": ["类酶", "酶活", "nanozyme", "enzyme-like"]
}
```

---

## 阶段 3：模型服务与微调

### 任务 3.1：vLLM 模型服务部署

**目标：** 启动 LLaVA-1.6-13B (AWQ 4-bit) 的 OpenAI 兼容 API 服务

```bash
# 1. 下载模型（如果本地没有）
huggingface-cli download liuhaotian/llava-v1.6-vicuna-13b

# 2. AWQ 量化（如果预量化版本不存在）
python -m autoawq.entry --model_path liuhaotian/llava-v1.6-vicuna-13b \
    --output_path ./models/llava-1.6-13b-awq

# 3. 启动 vLLM 服务
python -m vllm.entrypoints.openai.api_server \
    --model ./models/llava-1.6-13b-awq \
    --quantization awq \
    --max-model-len 4096 \
    --enable-lora \
    --max-loras 4 \
    --max-lora-rank 64 \
    --gpu-memory-utilization 0.90 \
    --port 8000

# 4. 验证服务
curl http://localhost:8000/v1/models
# 预期返回: {"data": [{"id": "llava-1.6-13b-awq", ...}]}
```

**LLM 配置切换（src/utils/llm_config.py）：**
```python
def create_llm():
    """创建本地 vLLM 服务的 LLM 实例"""
    from crewai import LLM
    return LLM(
        model=f"openai/{Config.LLAVA_MODEL_NAME}",
        base_url=Config.LLAVA_API_BASE,
        api_key="not-needed",  # vLLM 本地服务无需认证
        temperature=0.3
    )
```

---

### 任务 3.2：训练数据准备

**涉及文件：** 新建 `finetune/prepare_data.py`

**数据格式（LLaMA-Factory 兼容的 JSONL）：**
```json
{
  "instruction": "你是一位抗菌纳米材料评估专家。请评估以下材料的抗菌性能。",
  "input": "材料: Cu_NC_CD\n粒径: 2.5 nm\nzeta电位: -15 mV\n包覆: 环糊精\n目标菌种: 大肠杆菌, 粪肠球菌, 双歧杆菌",
  "output": "{\n  \"E_coli_MIC\": \"25 μg/mL\",\n  \"E_faecalis_MIC\": \"30 μg/mL\",\n  \"B_bifidum_MIC\": \">200 μg/mL\",\n  \"selectivity_ratio\": 8.0,\n  \"potency_score\": 7,\n  ...\n}"
}
```

**数据来源优先级：**
1. 自有实验数据（最高优先级，来自 LocalExpDB）
2. 文献提取数据（来自 curated_nano_bio.json）
3. 公共数据库补充（PubChem, DrugBank, Materials Project 的结构化查询结果）

**预估各智能体训练数据量：**

| 智能体 | 训练对数量 | 主要来源 |
|--------|-----------|---------|
| EA | 2000+ | PubMed 文献标注 + 自有实验 |
| APA | 1000+ | 文献 MIC 数据提取 + 自有实验 |
| EPA | 800+ | 纳米酶综述 + DrugBank 酶参照 |
| BSA | 1000+ | PubChem 毒性 + ECOSAR 预测 |
| MMA | 500+ | 文献摘要 + 人工标注推理链 |
| TOA | 300+ | 人工构造意图-路由对 |
| CA | 500+ | 合成多材料对比场景 |

---

### 任务 3.3：LoRA 微调训练

**涉及文件：** 新建 `finetune/train_lora.py`, `finetune/configs/`

**7 个 YAML 训练配置示例（apa_config.yaml）：**
```yaml
### APA 抗菌预测智能体 LoRA 训练配置
model_name_or_path: liuhaotian/llava-v1.6-vicuna-13b
quantization_bit: 4

# LoRA 参数
lora_rank: 64
lora_alpha: 128
lora_target: q_proj,k_proj,v_proj,o_proj
lora_dropout: 0.05

# 训练参数
stage: sft
dataset: apa_training_data
template: vicuna
finetuning_type: lora
learning_rate: 5.0e-5
num_train_epochs: 5
per_device_train_batch_size: 4
gradient_accumulation_steps: 2
max_seq_length: 512
warmup_ratio: 0.03
weight_decay: 0.01
bf16: true
```

**训练脚本核心逻辑：**
```python
# train_lora.py
import subprocess
import yaml
from pathlib import Path

AGENTS = ["ea", "apa", "epa", "bsa", "mma", "toa", "ca"]

def train_agent(agent_name: str):
    config_path = Path(f"finetune/configs/{agent_name}_config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)

    cmd = [
        "llamafactory-cli", "train",
        "--config", str(config_path),
        "--output_dir", f"./models/lora/{agent_name}"
    ]
    subprocess.run(cmd, check=True)

if __name__ == "__main__":
    for agent in AGENTS:
        print(f"Training {agent} LoRA adapter...")
        train_agent(agent)
        print(f"{agent} adapter saved to ./models/lora/{agent}/")
```

**训练后验证：**
```python
# 测试 LoRA adapter 是否可正常加载
from vllm.lora.request import LoRARequest

lora_request = LoRARequest("apa", 1, "./models/lora/apa")
# 通过 vLLM API 调用:
# curl http://localhost:8000/v1/chat/completions \
#   -d '{"model": "llava-1.6-13b-awq", "messages": [...], "lora_request": {"lora_name": "apa", "lora_int_id": 1}}'
```

---

## 阶段 4：工作流集成

### 任务 4.1：异步工作流（main_async.py 适配）

**涉及文件：** 修改 `scripts/main_async.py`

新增 "nano_bio_comparison" 工作流模式，核心 Pipeline：

```
阶段1（串行）:
  EA 并行调用 PubChem + DrugBank + Materials Project + 本地实验库
      → 多材料的结构化 JSON → 存入 ContextStore

阶段2（4智能体全并行）:
  ├─ APA 评估抗菌性能          ← async_execution=True
  ├─ EPA 评估类酶活性           ← async_execution=True
  ├─ BSA 评估生物安全性         ← async_execution=True
  └─ MMA 推断分子机理           ← async_execution=True

阶段3（串行）:
  CA 汇总评分 + MMA 机理报告
      → Cj 一致性加权
      → 对比矩阵 + 雷达图数据 + 排名结论
```

### 任务 4.2：端到端集成测试

```python
# tests/test_e2e_nano_bio.py
def test_full_comparison_pipeline():
    """端到端测试：3材料对比，Cu NC@CD 应排名最高"""
    user_input = (
        "对比 Cu_NC_CD、Ag_NP、ZnO_NP 对肠道菌群的抗菌性能、"
        "类酶活性和生物安全性"
    )
    result = run_nano_bio_workflow(user_input, mode="comparison")

    assert "comparison_matrix" in result
    assert "rankings" in result
    assert "radar_chart_data" in result

    rankings = result["rankings"]
    cu_nc_cd = [r for r in rankings if "Cu" in r["material"]][0]
    assert cu_nc_cd["overall_score"] >= 7.0
```

---

## 阶段 5：文档与部署

### 任务 5.1：模型部署文档
详细描述 vLLM 启动命令、环境变量配置、LoRA adapter 热加载、故障排查。

### 任务 5.2：面向领域专家的 HTML 总览页
见 `plan/project-overview.html`——用通俗语言介绍系统功能、智能体角色、输入输出示例，避免大模型术语。

---

## 实现顺序总览

```
阶段0 (基础设施)
  ├── 0.1 安装依赖
  ├── 0.2 配置模块
  └── 0.3 Neo4j 建表

阶段1 (工具层)
  ├── 1.1 PubChem 扩展
  ├── 1.2 DrugBank 工具
  ├── 1.3 本地实验库
  ├── 1.4 酶活分类器
  └── 1.5 知识图谱浏览器、PNEC、ECOSAR、材料对比、文献搜索工具

阶段2 (智能体层)
  ├── 2.1 APA 抗菌预测
  ├── 2.2 EPA 酶活预测
  ├── 2.3 BSA 安全评估
  ├── 2.4 MMA 机理适配
  ├── 2.5 CA 对比汇总
  ├── 2.6 EA 知识抽取适配
  └── 2.7 TOA 调度适配

阶段3 (模型与训练)
  ├── 3.1 vLLM 部署
  ├── 3.2 训练数据准备
  └── 3.3 LoRA 微调

阶段4 (集成)
  ├── 4.1 异步工作流
  └── 4.2 端到端测试

阶段5 (文档)
  └── 5.1-5.2 部署文档 + HTML 总览
```
