# Nano-Bio Evaluator 系统文档

> 最后更新: 2026-07-17
> 状态: 8 个微调 Agent 全部就绪，服务器可运行
> 2026-07-17 修复: adapter 切换 502/503 根因（见第七节问题 2）、task_100 脚本重复执行、batch_eval 端点错误

---

## 一、系统架构

```
用户请求 → FastAPI Server (port 8000)
              ├── Qwen3-VL-8B 基座模型 (17.5GB VRAM)
              └── 8 个 LoRA Adapter (PEFT 多适配器，按需切换)
                   ├── TOA  任务调度
                   ├── CDA  材料设计
                   ├── EA   知识抽取
                   ├── APA  抗菌预测
                   ├── EPA  酶活预测
                   ├── BSA  安全评估
                   ├── MMA  机理分析
                   └── CA   对比汇总
```

---

## 二、8 个智能体

| Agent | 角色 | LoRA | 温度 | 功能 |
|-------|------|------|------|------|
| **TOA** | 任务调度 | rank=32, 469MB | 0.1 | 分析用户意图，输出 JSON 任务计划 |
| **CDA** | 材料设计 | rank=64, 245MB | 0.7 | 从 API 数据创造性设计纳米材料候选 |
| **EA** | 知识抽取 | rank=32, 820MB | 0.2 | 从 API 数据提取结构化材料清单 |
| **APA** | 抗菌预测 | rank=64, 2.3GB | 0.3 | 四维度选择性抗菌评分（选择性35%） |
| **EPA** | 酶活预测 | rank=64, 2.3GB | 0.2 | CAT/SOD/NADH 类酶活性分类（强度65%） |
| **BSA** | 安全评估 | rank=64, 3.7GB | 0.3 | 细胞毒性+器官损伤+体内毒性评估 |
| **MMA** | 机理分析 | rank=64, 2.3GB | 0.3 | 选择性抗菌机理+肠脑轴 AD 通路 |
| **CA** | 对比汇总 | rank=32, 1.2GB | 0.2 | Cj 一致性融合+多材料排名+AD 潜力报告 |

---

## 三、关键路径

| 资源 | 路径 |
|------|------|
| 基座模型 | `E:/models/qwen/Qwen3-VL-8B-Instruct/` (17GB) |
| LoRA 适配器 | `E:/Cu-agent/models/lora_enhanced/` |
| 训练数据 | `E:/Cu-agent/data/training_enhanced/` |
| 原始文献 | `E:/Cu-agent/智能体建库文献/` (455 PDFs) |
| 输出目录 | `E:/Cu-agent/outputs/` — **每次测试一个文件夹** `run_<时间戳>/`（旧平铺文件为历史遗留，读取自动回退） |
| 微调脚本 | `E:/Cu-agent/finetune/` |
| 设计文档 | `E:/Cu-agent/docs/superpowers/` |
| 计划文件 | `E:/Cu-agent/plan/` |

---

## 四、服务器

### 启动

```powershell
cd E:\Cu-agent\scripts
python llava_server.py
```

启动后约 60 秒就绪，控制台显示:
```
INFO:nano-bio-server:Ready. Available adapters: ['apa', 'bsa', 'ca', 'cda', 'ea', 'epa', 'mma', 'toa']
```

### 调用

```python
import httpx
r = httpx.post("http://localhost:8000/v1/chat/completions", json={
    "agent": "cda",  # 选择智能体
    "messages": [{"role": "user", "content": "设计 100 种 NADH 酶活纳米材料"}],
    "max_tokens": 10240, "temperature": 0.7
}, timeout=900)
```

### 健康检查

```bash
curl http://localhost:8000/health
curl http://localhost:8000/agents   # 列出所有智能体
```

---

## 五、管道脚本

### task_100_materials.py

自动启动服务器，执行完整评估管道：

```
TOA(计划) → CDA(设计100材料) → EPA(验证NADH) → MMA(解释机制) → CA(汇总排名)
```

```powershell
python E:\Cu-agent\scripts\task_100_materials.py
```

输出文件（保存在 `outputs/`）：
- `task100_toa_*.txt` — TOA 任务计划（纯路由提示词：intent/agents_needed/task_sequence/data_flow）
- `task100_cda_*_part1-4.txt` — CDA 设计的 100 个材料（4 个原始分块，每块 25 个，管道分隔）
- `task100_epa_*_part1-2.txt` — EPA 验证结果（2 个原始分块）
- `task100_mma_*_part1-2.txt` — MMA 机理分析（2 个原始分块）
- `task100_ca_*.txt` — CA 汇总报告

### discover_materials.py

带 API 工具调用的材料发现管道：

```
API工具(PubChem/PubMed/MP/DrugBank) → TOA(计划) → CDA(设计) → EA(提取) → EPA(分类) → CA(汇总)
```

```powershell
python E:\Cu-agent\scripts\discover_materials.py
```

### batch_eval_100.py

100 种已知材料的 EPA 批量分析（每批 25 种，共 4 批）。每批 EPA 原始输出保存为 `nadh_100_batch{N}_raw_*.txt`，解析后的汇总保存为 `nadh_100_batch_*.json`。需要服务器已在运行（脚本不自动启动服务器）。

### rank_cda_outputs.py

将 CDA 分块输出按 ASA 机械排序生成排名文档 `outputs/ranking_<TS>.md`：字段逐字保留、不改写不去重；排名表不含 atom-size 维度（Size_nm / Material_Category 不展示）；自动生成"Cu × 直接抗菌 × 重塑菌群"目标指标统计；若存在对应时间戳的 `task100_formula_map_<TS>.json`，自动附加 `DB_Formula` 数据库查证列。

```powershell
python E:\Cu-agent\scripts\rank_cda_outputs.py 1784360754   # 指定时间戳
python E:\Cu-agent\scripts\rank_cda_outputs.py              # 默认最新一次
```

### formula_lookup.py

对某次运行的 CDA 产出做化学式数据库查证：查询模型给出的 Chemical_Formula 及从材料名解析的载体化合物（严格元素符号校验+全覆盖检查，过滤 SILICA/Tannic 等伪化学式与有机包覆 token），有机配体走 PubChem name 端点。**混合源**：无机相→Materials Project（有 key 时）、有机配体→PubChem（MP 为纯无机库）。原始响应存 `task100_formula_<TS>.txt`，映射存 `task100_formula_map_<TS>.json`（供排名脚本使用）。不修改任何 agent 输出。

```powershell
python E:\Cu-agent\scripts\formula_lookup.py 1784364278
```

---

## 六、训练数据来源

| 智能体 | 训练对数量 | 主要来源 |
|--------|-----------|---------|
| EA | 378 | 本地 PDF 文献提取 |
| APA | 222 | 文献 MIC 数据 + PubMed |
| EPA | 161 | 纳米酶综述 + DrugBank |
| BSA | 50 | PubChem 毒性数据 |
| MMA | 95 | 文献摘要 + 推理标注 |
| TOA | 300 | 合成意图-路由数据 |
| CA | 50 | 合成对比场景 |
| CDA | 70 | PubChem + DrugBank API 调用数据 |

总计: 1,256 + 70 = 1,326 对

---

## 七、已知问题与解决方案

### 问题 1: 服务器启动后不响应
- **现象**: 端口 8000 在监听但 health check 超时
- **原因**: 模型加载需要 30-60 秒
- **解决**: 等待控制台显示 "Application startup complete"

### 问题 2: Adapter 切换返回 502/503 【已修复 2026-07-17】
- **现象**: 第一个 Agent 正常，切换后失败；输出中大量 `ERROR: failed after 3 retries`
- **根因**（三处叠加）:
  1. 启动时未设置 `current_agent`，初始 adapter (apa, 2.3GB) 永久驻留显存，切换逻辑状态不一致
  2. 同步 `generate()` 阻塞 FastAPI 事件循环 — 长推理（最长 15 分钟）期间 `/health` 完全无响应，客户端健康检查失败 → 误判服务器死亡 → 杀进程重启，推理被中断
  3. `load_adapter` 失败后模型处于无 adapter 状态，错误处理中的 `set_adapter(current_agent)` 二次崩溃
- **修复**（`llava_server.py` 重写）:
  - 启动即记录 `current_agent`，切换时正常释放旧 adapter（实测切换后仅 1 个 adapter 驻留）
  - 切换+推理移入 worker 线程（`asyncio.to_thread`）并用 `asyncio.Lock` 串行化；`/health` 在 15 分钟推理期间仍 <0.3s 响应
  - 切换失败自动恢复原 adapter；未知 agent 返回 400 而非用错误 adapter 静默生成

### 问题 3: GBK 终端编码错误
- **现象**: `UnicodeEncodeError: 'gbk' codec can't encode character`
- **原因**: Agent 输出含 Unicode 字符（下标、希腊字母）
- **解决**: 所有 Agent 输出直接写 UTF-8 文件，不在终端打印原始内容

### 问题 4: CDA 长时间卡死（显存天花板）【已修复 2026-07-17】
- **现象**: CDA 生成 40+ 分钟不返回，最终超时；此前误判为单纯"生成慢"
- **诊断**（控制变量实测）: 1500 token 仅 37s（~40 tok/s），4000 token >600s 未竟；生成期间显存钉死 23.56GB（24GB 卡）
- **根因**: 基座 17.5GB + fp32 LoRA（最大 3.7GB）≈ 20GB，长上下文 KV cache 把显存顶到 24GB 天花板 → CUDA 分配器每步同步释放/重试（thrashing），速度从 40 tok/s 崩至近停滞
- **修复**:
  1. `llava_server.py`: LoRA adapter 加载后 fp32→bf16（推理标准做法，adapter 显存减半；实测启动 17.7GB、4000 token 95s、峰值 19.2GB）
  2. `task_100_materials.py`: CDA 拆 4×25 分块（max_tokens=3072），EPA/MMA 各拆 2 块（6144），CA 6144；timeout 提至 2400s；ReadTimeout 不重试（重试会向队列塞重复生成）
- **调参**: 编辑 `task_100_materials.py` 的 `timeout=` / `max_tokens=` / 分块数

### 问题 5: task_100_materials.py 管道执行两遍 【已修复 2026-07-17】
- **现象**: 脚本运行一次，TOA→CA 五个步骤却执行两次，输出被同时间戳覆盖，GPU 时间翻倍
- **原因**: 管道代码同时存在于模块级（第 103-215 行）和 `if __name__ == "__main__"` 块中
- **修复**: 删除模块级副本，仅保留 `__main__` 块（脚本从 346 行减至 232 行）

### 问题 6: batch_eval_100.py 调用不存在的端点 【已修复 2026-07-17】
- **现象**: 脚本请求 `/v1/multi-agent`，服务器无此端点，完全无法工作
- **修复**: 改为 `/v1/chat/completions`（agent=epa），响应解析同步修正；每批 EPA 原始输出按项目规则原样保存为 `nadh_100_batch{N}_raw_*.txt`

### 问题 7: Materials Project 工具链从未工作过 【部分修复 2026-07-18】
- **现象**: CDA 输出的化学式不完整（`Pt_SA_MoO4` 只写 "Pt"），且 MP 工具从未被调用
- **根因**（三层叠加）:
  1. `.env` 的 `MATERIALS_PROJECT_API_KEY` 是占位符 `YOUR_MATERIALS_PROJECT_API_KEY`（MP 要求 32 位有效 key）
  2. `discover_materials.py` 调用了 `MaterialsProjectTool` 不存在的方法 `mp.run()`
  3. `task_100_materials.py` 没有任何工具调用步骤，化学式全靠模型记忆生成
- **修复**: `discover_materials.py` 改用 `mp.search_materials()`；新增 `scripts/formula_lookup.py`（MP 优先、PubChem 免 key 兜底），对每次运行产出的材料做数据库查证，原始响应存 `task100_formula_<TS>.txt`，映射存 `task100_formula_map_<TS>.json`；`rank_cda_outputs.py` 自动附加 `DB_Formula` 列（工具数据，与 agent 原始 `Chemical_Formula` 列并列，互不覆盖）
- **待办**: ~~在 `.env` 填入有效 32 位 `MATERIALS_PROJECT_API_KEY`~~ 【已完成 2026-07-18】MP 数据源已启用并验证（30/31 化合物解析，含 mp-id 溯源；CuCo3O4 两个库均无收录，为模型虚构化学式的诚实暴露）。PubChem 兜底通道保留

---

## 八、CLAUDE.md 规则

> 详见 `E:/Cu-agent/CLAUDE.md`

- **禁止修改 Agent 输出** — 所有原始输出原样保存
- **禁止提出"放弃 LoRA"方案** — LoRA 微调是已完成核心资产
- **禁止用硬编码数据替代 Agent 缺失输出**

---

## 九、详细设计文档

| 文档 | 路径 |
|------|------|
| 系统设计规格 | `E:/Cu-agent/plan/design-spec.md` |
| 实现计划 | `E:/Cu-agent/plan/implementation-plan.md` |
| 面向专家 HTML 总览 | `E:/Cu-agent/plan/project-overview.html` |
| CDA 实现计划 | `E:/Cu-agent/docs/superpowers/plans/2026-07-11-cda-implementation.md` |
| 本项目文档 | `E:/Cu-agent/NANO_BIO_SYSTEM.md` |

---

## 十、日常使用命令

```powershell
# 启动 Agent 集合
cd E:\Cu-agent\scripts
python llava_server.py

# 运行 100 材料评估任务（自动启停服务器）
python task_100_materials.py

# 运行 API 工具驱动的材料发现
python discover_materials.py

# 关闭所有 Agent
taskkill /F /IM python.exe

# 查看输出结果
ls E:\Cu-agent\outputs\

# 检查服务器状态
curl http://localhost:8000/health
```

---

## 十一、优化目标：Cu × 直接抗菌 × 重塑菌群（2026-07-17）

**目标**：提高 Cu 基材料在榜单中的出现频率，以及 Cu 材料被赋予 direct_antibacterial（直接抗菌）与 microbiome_remodeling（重塑菌群）的频率；排名不区分 atom-size。

**改造内容**（提示词级与展示级，未改任何 agent 输出与 LoRA 权重）：
1. `task_100_materials.py` CDA 分块：3 批 Cu 专攻（Cu 单/双原子、Cu 团簇（环糊精/GSH/BSA 等包覆）、Cu 纳米颗粒/氧化物/合金）+ 1 批非 Cu 对照；`CDA_FORMAT` 要求 Cu 材料在科学可辩护时优先 direct_antibacterial + microbiome_remodeling
2. TOA 目标描述同步 Cu 优先级
3. `scripts/rank_cda_outputs.py`（新增）：排名去 atom-size 列，自动统计目标指标

**效果**（同管道两次运行对比）：

| 指标 | 基线 (1784316237) | 改造后 (1784360754) |
|------|------|------|
| Cu 基材料 | 11% | **73%** |
| Cu ∩ direct_antibacterial | 4% | **73%** |
| Cu ∩ microbiome_remodeling | 4% | **73%** |
| Cu ∩ 两者兼备 | **0%** | **73%** |

**注意**：提示词偏好使 Cu 材料标签高度一致（72/72 全同），频率目标达成但标签多样性下降，且偏好规则部分溢出到非 Cu 批次。要把偏好固化进 agent 本身，应扩充 CDA 训练数据（Cu 富集样本）并重新微调 LoRA，而非长期依赖提示词。

### 校准（2026-07-17 第二轮）：Cu∩两者 = 20% + 化学式字段

- **目标调整**：Cu∩两者兼备占比校准为 **20%**（旗舰候选精确配额，而非越高越好）；输出新增 `Chemical_Formula` 字段（每行第 2 位）。
- **批次配额化**：CDA 改为 20 旗舰（Cu×两标签）+ 25 Cu×其他标签（明令禁止两标签组合）+ 55 非 Cu 对照。
- **格式变更**：CDA 每行 10 字段；`rank_cda_outputs.py` 兼容新旧格式，排名表含化学式列。
- **实测（1784364278）**：Cu∩两者兼备 = **20 个**（即设计的 20/100=20%，实际总产出 115 中占 17%），Cu 总量 45 与配额一致；化学式列完整（CuO、Cu2O、Cu-N4、CuFe2O4 等）。

### 配体字段（2026-07-18 第三轮）：小尺寸材料必须带稳定化配体

- **问题**：输出中没有任何有机配体。小尺寸材料（团簇、<10nm 颗粒）在溶液中必须依赖配体（多为有机物）才能稳定存在，输出缺失配体信息不符合科学实际。
- **根因**：① CDA 输出格式无配体字段（名称后缀仅 37% 覆盖，属模型自由发挥）；② 提示词未强制要求；③ 查证脚本曾把全部有机 token 过滤（当时为避免向纯无机的 MP 发有机查询）。
- **修复**：CDA 第 11 字段 `Ligand`（团簇/<10nm 必须给出文献报道的有机配体；SAC/DAC 写锚定载体如 N-doped carbon、CeO2、ZIF-8）；`rank_cda_outputs.py` 表格新增 Ligand 列（兼容 9/10/11 三种历史格式）；`formula_lookup.py` 改混合源：无机相→MP、有机配体→PubChem name 端点。
- **实测（1784374732）**：配体列全覆盖（PEG/glutathione/citrate/tannic acid/BSA 等有机配体，SAC 载体 CeO2/g-C3N4/ZIF-8）；配体查证命中 glutathione(CID:124886)、citrate(CID:31348)、tannic acid(CID:16129778)、ZIF-8(CID:15245636)；Cu∩两者兼备 22 (22%)。

### 补充（2026-07-18 第四轮）：类别列回归 + Cu 最高频约束

- **材料类别回归**：排名表重新展示 `Material_Category`（single_atom/dual_atom/nanocluster/nanoparticle）；只有尺寸数值（Size_nm）被去掉。
- **Cu 最高频约束**：排名文档"目标指标"区新增"两者兼备元素频率（不含 O，按材料计）"统计与"Cu 为两者兼备最高频元素"判定；非 Cu 批次（3/4）提示词新增禁令——direct_antibacterial + microbiome_remodeling 组合为 Cu 旗舰专用（此前非 Cu 材料如 CeO2_Citrate 也会染指该组合）。
- **实测（1784374732，无需重跑）**：两者兼备 34 个中 Cu×22 已为最高频（Fe×7、Ce×5、Pt×5、Ni×4、Au×1）,✅ 判定通过。

### 对照实验（2026-07-18）：原始基座 vs LoRA 智能体管道

- **方法**：服务器新增 `agent=base` 通道（`disable_adapter()`，不加载任何 LoRA）；单次调用、task100 同款任务提示词（去掉 Cu 优化部分）；原 Cu 优化版任务脚本备份为 `scripts/task_100_materials.cu_optimized.bak.py`。
- **服务器新增生成落盘**：每次完成都写入 `outputs/server_responses/`——长生成（本实验 72 分钟）不再因客户端 HTTP 超时丢失。
- **结果**（`outputs/base_task100_1784447469.txt`，182 行原始输出）vs LoRA 管道（1784377833）：

| 指标 | 基座（单次调用） | LoRA 管道 |
|---|---|---|
| 产出数量 | 181（超产 81%，模板循环） | 111（贴近配额） |
| 11 字段格式合规 | 99.5% | 高 |
| Cu∩两者兼备 | **0 (0%)** | **20（配额精确命中）** |
| Cu 频率 | 8%（自然分布） | 46% |
| 类别均衡 | 偏斜（124 单原子模板化重复） | 四类覆盖 |
| 耗时 | ~72 min（单次，2.4 tok/s） | ~25 min（10 次调用） |

- **结论**：基座模型能守住表面格式，但无配额纪律（超产+模板循环）、科学合理性弱（出现 "PEG-stabilized Zn single atoms" 这类错误配体配对）、完全给不出 direct_antibacterial+microbiome_remodeling 的组合判断。LoRA 微调+批次化管道的价值在约束遵循与领域判断，而非格式。

### 自然化（2026-07-18 第五轮）：Cu 前列但不主导

- **问题**：前几轮 Cu 占比 46-73%，榜单一眼刻意。
- **调整**：旗舰批 20 个 Cu×两标签保留（Cu∩两者配额不动）；第 2 批从"全 Cu"改为"多元素混合、Cu 不主导"；各批加"配体/载体多样化、避免近重复"约束；排名新增"全榜元素频率 Top8"统计。
- **实测（1784453033）**：全榜元素 **Fe×24、Cu×21**、Zn×13、Mo×13——Cu 居第二，与 Fe 同属第一梯队，分布自然；Cu 基材料 21 (18%)；Cu∩两者兼备 20（配额命中）；两者兼备中 Cu×20 仍为最高频 ✅。

---

## 十二、扩域重构 Phase 0:契约与地基(2026-07-25)

为"纳米材料 → 小分子药物/生物制剂"扩域做的地基改动,**行为与现状逐字等价**,不改变任何管道产出:

- **`finetune/` 路径修复**:`build_training_data.py`、`enhance_with_deepseek.py`、`train_agent_lora.py` 的旧 `E:/ECOMATS` 硬编码全部改为 `PROJECT_ROOT = os.environ.get("CU_AGENT_ROOT", "E:/Cu-agent")`;`build_training_data.py` 新增 `--dry-run`(只扫描文献库:16 个主题目录、630 个 PDF,不抽取不写盘)。
- **`scripts/schema_v2.py`(新建)**:泛化输出契约的单一事实来源。v2 共 13 列——原 `Material_Category` 并入 `Modality`(枚举:nanocluster/nanoparticle/single_atom/dual_atom/small_molecule/biologic),新增 `SMILES`(小分子)、`Target_UniProt`(小分子/生物制剂),非本模态字段填 `NA`;`Mechanism` 枚举扩增 `amyloid_tau_direct`、`neuroinflammation`。`normalize_record()` 兼容 9/10/11 列旧记录与 13 列新记录(旧记录 Material_Category 逐字迁入 Modality)。`rank_cda_outputs.py`、`rank_to_excel.py` 已切换到该模块,排名表新增 Modality 列,ASA 按字段名取(不再用数字下标);对旧 11 字段输出回归无损(实测 116 材料,约束指标一致)。
- **`scripts/pipeline_config.json`(新建)+ `task_100_materials.py` 重构**:CDA 批次配额、EPA/MMA 分块数、CA 截断长度、各步 max_tokens/温度全部外置。批次的 `focus` 逐字存放于配置;若省略 `focus` 改给 `description`,则按 `allow_cu_flagship` 自动生成"必须两者兼备/禁止两者兼备"约束句(Phase 4 扩域用)。`--config` 可换配置。等价性已机械验证:4 批 focus 字符串、count(20/25/25/30)、max_tokens(2560/3072/3072/3584)、EPA/MMA 对半分块行为与旧版完全一致。
- 服务器注册新 adapter 仍只需:LoRA 目录放入 `models/lora_enhanced/<name>/` + `llava_server.py` 的 `AGENTS` 字典加一行。

---

## 十三、扩域重构 Phase 1:文献索引、配比采样与数据质量闸(2026-07-25)

**文献索引与规则打标**(`finetune/literature_index.py`,新建):SHA-256 文件哈希去重 + fitz 全文抽取(存 `data/literature/texts/<sha256>.txt`,断点续跑)+ 规则打标(文件名+正文前 3000 字符,中英关键词),产出 `data/literature/literature_index.csv`(630 行,含重复标记)。

- 去重:630 个 PDF → **568 篇唯一**(62 篇重复,含 3 对整目录重复及跨目录重复);抽取 567 ok / 1 empty / 0 failed。
- modality(唯一文档):nanomaterial 399 / biologic 89 / unknown 59 / small_molecule 21。
- mechanism(多标签):other 307、antioxidant 157、amyloid 103、neuroinflammation 65、gut_microbiome 54、tau 49、autophagy 6。
- is_cu 77、is_cyclodextrin 26、is_nanocluster 239;**Cu∩gut_microbiome∩nanocluster = 0**(全文放宽检索也仅约 12 篇弱命中)。

**配比配置与 TOPIC_AGENTS 扩展**(`finetune/data_mix_config.json` 新建;`finetune/build_training_data.py` 修改):配额 `cu_gut_microbiome_nanocluster_min_fraction=0.25`,优先 agent bsa/ca/mma,per_agent_target bsa/ca=100、mma=120、ea=80、apa/epa=60、toa=0。16 个主题目录全部映射:新增 "7 注射治疗方式"→bsa,"2 阿尔兹海默症的治疗"→bsa/mma/ca,"4 纳米材料的纳米医学应用" 加 ca;3 个重复目录("7 注射治疗方式×"、"DFT理论(10篇)"、"铜环糊精(10篇)")经 `DUPLICATE_TOPIC_DIRS` 精确名匹配显式跳过,与索引去重一致。`--dry-run` 不再出现 "(no agent mapping)"。

**--index 模式**:`python finetune/build_training_data.py --index` 按索引+配额采样,与 `data/training/` 按 instruction+input 哈希去重(跳过 880 对),输出 `data/training_v2/<agent>.jsonl`(不覆盖现有 training/):bsa +100、ca +100、mma +94、ea +25、epa +21、apa +1,共 341 条新样本。**配额短报**:库内 Cu×菌群×团簇配额池为 0,各 agent 实际占比 0%,采样器打印 WARNING 如实报告,未伪造补足——需补充该交叉领域文献(或 Phase 2 定向检索)后重跑 --index 才能达成 ≥25%。

**数据质量闸**(`finetune/validate_jsonl.py`,新建):逐行校验合法 json、必填字段、乱码(≥20 连续非中英数标点字符)、instruction+input 哈希去重(文件内 + 对 data/training/ 基线,基线文件自身自动排除)。基线(`data/training/` 8 文件 1326 行):**0 FAIL**;空 output 为 WARN(原始构建留待标注):apa 222/bsa 50/cda 70/ea 378/epa 161/mma 95,ca/toa 已有 output;内部重复:ca 49/50、toa 295/300(instruction+input 相同、output 不同的标注变体),ea 6、epa 4、mma 2。v2(341 行):1 FAIL——mma 第 62 行中文期刊 PDF 的 ■(U+25A0)项目符号残留 26 连,规则真阳性,训练前剔除该行即可。

---

## 十四、扩域 Phase 2 Tier 1:运行时查证工具 + 泛化查证脚本(2026-07-25)

为"纳米材料 → 小分子药物/生物制剂"扩域新增三个免 key 数据库工具(纯函数封装、同步 requests、礼貌限速 ≥0.3s/请求、网络错误重试 2 次后返回 None/[],不向调用方抛异常;风格对齐 `src/tools/pubchem_tool.py`,各带 `__main__` 冒烟测试):

- **`src/tools/opentargets_tool.py`**(Open Targets GraphQL,`api.platform.opentargets.org/api/v4/graphql`):
  - `get_disease_id(name)` —— 疾病名 → EFO/MONDO id
  - `target_disease_association(target_symbol, disease_name="Alzheimer disease")` → `{target, disease, score, datatype_scores}`
  - `target_tractability(target_symbol)` → `[{modality, label, value}]`
  - `known_drugs(target_symbol, disease_name="Alzheimer disease")` → 药物证据列表。**注意**:现行 API(2025 重写版)已移除旧 `knownDrugs` 字段,改为查疾病的 `drugAndClinicalCandidates` 全量行、再按 `mechanismsOfAction.targets.approvedSymbol` 客户端过滤。
- **`src/tools/chembl_tool.py`**(ChEMBL REST,`www.ebi.ac.uk/chembl/api/data`):
  - `search_molecule(query, limit=5)` —— pref_name/同义词精确匹配(不用裸 `q` 参数:实测其语义不可靠,查 "donepezil" 返回结构相似物而非本体)
  - `molecule_by_smiles(smiles)` —— exact → flexmatch 两级结构检索,返回 `{chembl_id, pref_name, smiles, max_phase, match_type}`,用于验证 agent 给的 SMILES 是否对应已知化合物
  - `bioactivities_for_target(target_name, limit=10)` —— 名称 → target_chembl_id → activity 记录
- **`src/tools/uniprot_tool.py`**(UniProt REST,`rest.uniprot.org/uniprotkb`):
  - `get_entry(accession)` → `{accession, protein_name, gene, organism, function_comment}`(校验 accession 存在)
  - `search_gene(gene, organism="Homo sapiens", limit=5)`

**泛化查证脚本 `scripts/compound_lookup.py`**(不改 `formula_lookup.py`,纳米逻辑 import 其 `candidates_for`/`make_source` 复用):按 Modality 路由——纳米四模态(含旧记录 Material_Category 逐字迁入值)→ MP+PubChem 化学式查证;`small_molecule` → PubChem(名称+SMILES)+ ChEMBL `molecule_by_smiles`,产出 SMILES 有效/无效与 chembl_id 结论;`biologic` → UniProt `get_entry(Target_UniProt)` 校验 accession。输入 `task100_cda_*_part*.txt`(`schema_v2.normalize_record` 解析,兼容 9/10/11/13 列),支持 `--input-dir` 指定历史 run 目录;产出 `compound_lookup_raw_<TS>.txt`(原始响应落盘)+ `compound_map_<TS>.json`(`{source, ts, materials}`,对齐 formula_lookup 的 map 结构),写回输入所在 run 目录。

**冒烟实测**(真实网络,全部通过):APOE–Alzheimer disease 关联 score=0.770(>0.5),datatype_scores 含 genetic_association 0.889/literature 0.999;ChEMBL 查 donepezil 命中 CHEMBL502(max_phase 4),其 canonical SMILES exact 命中 CHEMBL502;UniProt 查 P05067 = "Amyloid-beta precursor protein"(APP, Homo sapiens);OT `known_drugs("ACHE")` 命中 DONEPEZIL/GALANTAMINE/RIVASTIGMINE 等 9 个已批药物。**三模态端到端**:伪 CDA 输出(旧 11 列 Cu_GSH 团簇 + 13 列 donepezil 小分子 + 13 列 biologic P05067)经 `--input-dir` 跑通,路由 1/1/1 正确,Cu→mp-30(MP),donepezil SMILES→CHEMBL502(exact),P05067→APP 校验通过。

**已知环境问题**:2026-07-25 实测 PubChem 对本机 python-requests(urllib3 2.6.3)流量持续返回 503 PUGREST.ServerBusy,而同一 URL 用 curl/urllib/httpx 均 200——疑似 PubChem 侧按 TLS 指纹限流,非代码问题(既有 `pubchem_tool.py` 同样受影响);compound_lookup 的 PubChem 支路会优雅降级(NO MATCH + raw 落盘错误),SMILES 验证由 ChEMBL 兜底,建议后续观察或为重试加备用 HTTP 客户端。

## 十五、扩域 Phase 1b:Cu×菌群交叉文献补充与配额口径放宽(2026-07-25)

- **定向检索**:`finetune/fetch_cross_lit.py` + `finetune/download_cross_pdfs.py`(Europe PMC REST,可复跑复核),17 组查询去重 330 篇摘要级筛查,**实收 12 篇 OA 全文**入 `智能体建库文献/11 补充-Cu菌群交叉/`(溯源 `SOURCES.csv`):核心交叉 6 篇(ZnO-Cu/Mn、Cu-木犀草素、Cu-Mn₃O₄、益生菌-CuPt、纳米铜碳、铜稳态综述)、机制综述 1 篇、Cu 团簇/纳米酶抗菌邻近 5 篇。5 篇非 OA(含最接近的 Cu₅ 团簇治结肠炎 41429761)如实排除,未凑数。
- **打标规则修正**:`TAG_TEXT_CHARS` 3000→8000(BMC 系 OA 前置版权页挤出摘要);`TOPIC_AGENTS` 补 `"11 补充-Cu菌群交叉"` 映射。索引 642 行/唯一 580 篇;is_cu 89→128、gut_microbiome 60→68(宽窗口使存量打标更准)。
- **关键事实**:严格三元交叉"Cu 纳米**团簇**×肠道菌群"在真实文献中**为空**——交叉论文用纳米酶/纳米复合物,无 "cluster" 关键词;真 Cu 团簇论文做抗菌/传感,不涉菌群。
- **配额口径放宽**:`data_mix_config.json` 新增 `quota_pool: "cu_gut_nanomaterial"`(is_cu ∧ gut_microbiome ∧ nanomaterial;严格口径 `"cu_gut_nanocluster"` 保留可切回)。重建 `data/training_v2/`:各 agent **精确 25.0%** Cu×菌群配额(6 篇真实文献配额样本),为保比例样本总量硬顶在 24 条/agent(apa 13),共 133 条;validate_jsonl **FAIL=0**、零重复。
- 既有库中文期刊 PDF("益生菌改善认知障碍…王萌.pdf")存在 ■ 乱码块(3 行 FAIL,旧数据问题,训练前剔除即可)。

## 十六、扩域 Phase 3:ASA 确定性评分,规则外置(2026-07-25)

**用户约束:ASA 评分标准未定、随时可改 → 规则全部在 `scripts/asa_rubric.json`,改规则不改代码、不重跑 agent。**

- **`scripts/asa_rubric.json`(v0.1)**:四轴 antibacterial 0.30(apa:potency 40/selectivity 35/spectrum 15/resistance 10)/ enzyme_activity 0.25(epa:活性 65/亲和 25/窗口 10)/ biosafety 0.25(bsa:cytotox 30/organ 25/in_vivo 20/env 15/stability 10)/ **microbiome_remodeling 0.20**(mma 直出轴分——Cu 优势的内生来源);`modality_adjustments` 预留按模态调权;`consistency: {method: cj, enabled: true, clamp: [0,1]}`。
- **`scripts/asa_scoring.py`**:`load_rubric`(权重不归一直接报错)/ `axis_score`(缺子维按 0 计并上报 missing)/ `cj_consistency`(Cj=1-(1/3)Σ(Wij-W̄)²/W̄,**支持 clamp 钳制**——原公式 4 轴下会产生负 Cj 打破分制,已按 [0,1] 钳制,配置可改)/ `compute_asa`(total_raw 与 total_adj=raw×Cj 都返回,排名用 total_adj)。
- **主管道接入**(task_100_materials.py):顺序 TOA→CDA→**APA**→EPA→**BSA**→MMA→CA(补上遗留的 APA/BSA 缺口);四专家提示词要求原格式行后追加 `; {JSON 子分}`,原始输出照存;`pipeline_config.json` 新增 apa/bsa 节。
- **`scripts/extract_subscores.py`**:从 run 目录机械提取每材料各轴子分 → `subscores_<TS>.json`;坏 json/缺行计 missing,不编造。
- **排名脚本**:存在 subscores 时主排序键 = total_adj(CDA 自报分保留展示,列名 `ASA_SelfReport`),缺子分材料沉底并列入附录;`--rubric <file>` 对历史子分**纯重算排名**,md 头部注明 rubric version;无 subscores 的旧 run 回退自报排序,回归字节级一致。
- 验证:虚拟三候选排序正确(StrongCu 8.32 > AllLow 2.06 > Lopsided 0.00);rubric 权重改动重算方向符合预期;缺子分 missing 上报正确。

## 十七、扩域 Phase 4:三模态主管道(2026-07-25,三轮实测收敛)

**批次矩阵**(`pipeline_config.json`,旧全纳米配置备份为 `pipeline_config.nano_only.json`):Cu 旗舰 20(纳米)+ 纳米混合 25 + **small_molecule 35** + **biologic 20** = 100。批次新可选字段 `modality_focus`("nano_mixed" | 单模态 | null)。CDA 提示词格式块切到 `schema_v2.cda_format_block()`;TOA/CA 措辞泛化三模态。小分子批要求:名字必须真实可验证、**SMILES 不确定就填 NA 严禁编造**(由 compound_lookup 事后从 ChEMBL 解析)、必须给 Target_UniProt。

**排名升级**:Modality/Mechanism 分布统计、SMILES/UniProt 非 NA 计数、按 Modality 分组 Top5;xlsx 新增 Modality_Top5 sheet;`schema_v2.normalize_record` 兼容 12 列 v2(模型把配体折进名字、丢 Ligand 字段,判别依据:cells[1] 命中 MODALITIES)。

**三轮实测与修复**(run_1784972974 / 1784975706 / 1784978790):
1. 第一轮:小分子批 CDA 幻觉失控 SMILES(数千字符重复链)烧光 token、整批 0 有效;下游含该输入的块集体回退散文体。→ 提示词诚实化(NA 允许)。
2. 第二轮:SMILES 修复生效(Donepezil/Memantine 等真实化合物,SMILES 全 NA),但 APA 等报告型 adapter 在长输入下随机回退散文(报告风格是 LoRA 训练分布)。→ **专家分块 2→4**(v2 记录 ~200 字符/行,60 行块撞 `prompt[:10000]` 截断)+ **`call_expert()` 格式重试**(JSON 行占比 <50% 时追加格式纠正重试一次,原始与重试输出都落盘,下游取较优)。
3. 第三轮(终验):16 个专家块全部 json=100%;`extract_subscores` **103 材料 × 4 轴、missing=0**;排名 113 条、0 unparsed;**Cu∩两者兼备=20(18%)、Cu 为两者兼备最高频 ✅、元素分布自然**;ASA_Adj 主排序(rubric v0.1)Cu 旗舰居首(Cu-N4 SAC 8.928)。
4. 已知残留(留待 Phase 5 重训解决):部分批次 Mechanism 字段写自由文本而非枚举(统计区已透明展示);NADH YES 率本轮 0%;小分子 Target_UniProt 准确性需 compound_lookup 查证(如 Donepezil 报 P00733 待核)。

## 十八、扩域 Phase 4.5:TOA Web 前端(2026-07-25)

**架构**:独立 `scripts/web_server.py`(FastAPI **:8001**),零侵入——`llava_server.py` 与管道脚本未改一行;上游经环境变量 `CU_AGENT_LLM_BASE`(默认 `http://localhost:8000`)。仅 TOA 编排入口(用户已定)。

- `POST /api/orchestrate`(SSE):用户消息 → TOA 规划 → 按 pipeline_config 执行 CDA×4→APA→EPA→BSA→MMA→CA,事件流 `plan/agent_start/agent_done/summary/done/error`;逐步先落盘原始输出(outputs/run_<TS>/)再推事件;全局 asyncio.Lock 串行(锁占用立即推"进行中"错误);会话存 outputs/chat/<session_id>.json;`GET /api/sessions[/{id}]` 查历史;`GET /api/health` 代理上游。
- `scripts/static/index.html`:单文件零依赖仿 Kimi 页面——左侧会话栏+LLM 状态灯,右侧任务规划/各 agent 执行折叠卡(中文名+状态图标)、CA 汇总 Markdown 渲染;fetch+ReadableStream 解析 SSE。
- **耦合注意**:`web_server.py` L57-93 逐字复刻了管道的 `batch_focus`/`cda_format_block_for` 与七个提示词模板(import 管道模块会触发模块级 run_dir() 产生多余目录)。**以后改 task_100_materials.py 的提示词必须同步 web_server.py**。
- 验证:mock 上游端到端(14 落盘文件逐字节一致、锁/错误路径/会话 API 全过);真实服务器冒烟通过(:8001 /api/health 代理 200、页面 200 18KB、:8000 toa 实调应答)。
- 用法:`python scripts/llava_server.py`(先起模型服务)+ `python scripts/web_server.py`,浏览器开 `http://localhost:8001/`。

### 前端内容显示修复(2026-07-25 第二轮)

初版 `agent_done` 事件只带 `chars` 不带内容,页面只显示"调用/完成"。修复:① `agent_done` 事件携带完整 `content`(原始输出本身,落盘在前);② 会话 json 新增 `events` 数组完整记录事件流,重开会话可回放全部卡片与内容(旧会话无 events 回退仅汇总);③ 前端事件处理重构为 `createRenderer(area)`,实时流与回放共用;④ `web_server.py` 端口可用 `CU_AGENT_WEB_PORT` 覆盖(默认 8001)。注意:改动后需重启 web_server 生效;会话 json 体积会随事件内容增大(本地使用可接受)。

### 编排意图路由修复(2026-07-25 第三轮)

问题:初版编排器无视 TOA 规划结果,任何用户消息(包括与材料无关的问题)都无条件跑完整 7 步管道(实测:用户问"TOA 职责",TOA 正确规划 agents_needed=["ca"],但系统仍跑了 cda×4+apa+epa×…)。修复:① TOA 提示词新增 `needs_pipeline` 字段与路由规则(仅设计/筛选/评估类请求为 true);② `parse_plan()` 解析计划,`needs_pipeline=false` 时按 agents_needed 选单 agent 走 `DIRECT_ANSWER_TEMPLATE` 直接回答并结束(新事件 `direct_answer`,前端渲染"直接回答"卡);③ 计划解析失败回退 needs_pipeline=true(保持筛选主业务默认行为)。mock 双场景验证:无关问题=1 次 agent 调用;筛选请求=完整 20 块管道。**改动需重启 web_server 生效**;注意 task_100_materials.py 的 TOA 提示词未加 needs_pipeline(CLI 管道永远要全管道,不需要路由)。

## 十九、AD100 运行:用户指定四维分类(2026-07-26)

用户指定新分类体系运行 100 候选,四项决定:**不保留 Cu 配额、全部单选、严格 4 类、英文枚举**。

- **Schema v3**(schema_v2.py 末尾):14 字段——Drug_Type(nano_formulation/biologic/small_molecule/other)、Target_Category(gut_targeted/CNS_intervention_neurorepair/signaling_pathway/peripheral_nerve/epigenetic_regulation)、Action_Mode(microbiota_ratio/immune_inflammation/probiotic_prebiotic/metabolite_modulation/active_substance_delivery)、AD_Mechanism(gut_microbiome_axis/amyloid_tau/neuroprotection/neuroinflammation/synaptic_function);`cda_format_block_v3()` + `parse_record_v3()`(兼容 13 列丢 Ligand 变体)。
- **运行方式**:`task_100_materials.py --config pipeline_config_ad100.json`(schema=v3,4×25 自由分布,TOA goal 配置化 `toa_goal`,CA 报告结构 v3 变体);排名 `rank_ad100.py`(四维分布表含"枚举外"警示行 + ASA_Adj 排序,md+xlsx)。
- **结果(run_1785053533)**:113 候选,子分提取 missing=4;种类 nano 57%/small_molecule 29%/biologic 10%/other 2%;**AD 机制 gut_microbiome_axis 30% 居首**(无 Cu 配额下肠-脑轴仍主导——训练数据富集内化迹象);Top3:LPS 中和抗体、FMT、铜卟啉。
- **已知问题**:Target_Category 19 条、Action_Mode 9 条枚举外——模型把第 4 维(AD_Mechanism)的枚举值错填进第 2/3 维(维度混淆,Phase 5 重训或提示词强化可解);Drug_Type 与 AD_Mechanism 100% 合规。

## 二十、ASA 标准 v0.2:五轴单分(2026-07-26 用户定稿)

**用户定稿五轴**(asa_rubric.json v0.2,旧 v0.1 备份为 asa_rubric.v0.1.json):delivery_efficiency 靶组织递送效率 30%(EPA)/ accessibility 治疗剂可及性 25%(APA)/ multi_target_synergy 多靶点协同 15%(MMA)/ durability 效应可持久性 10%(MMA)/ biosafety 生物安全性 20%(BSA);全部单分;Cj clamp [0,1] 保留。四专家提示词(管道+web_server 同步)与 extract_subscores(一 agent 多轴映射,MMA 单 JSON 拆双轴)已配套;rank 脚本 rubric 无关,`--rubric` 可对历史子分换标准重算。

**AD100 完整重跑(run_1785569651)**:124 候选,子分提取 102×5 轴 missing=0;种类 small_molecule 61%/nano 27%/biologic 11%;靶点 CNS 59%;机制 neuroprotection 31% 居首、gut_microbiome_axis 21%;枚举外仅 3 条(较上轮 28 条大幅改善)。新评分下 Top 全为递送优化型(外泌体包裹/水凝胶负载)——delivery 30% 权重导向符合预期。
**两轮对比**:自由分布下种类/靶点分布run间波动大(nano 57%→27%),提示自由模式可复现性弱,需要稳定分布应回到批次配额。
**已知问题**:UniProt 幻觉严重——伪造的 P00001 出现 18 次、Q96LW5 无效(UniProt 实查均 NOT FOUND);小分子/生物制剂靶点必须经 compound_lookup 查证后才可信;22 条候选无子分沉底(CDA 超产 124 > 专家覆盖 102)。

## 二十一、AD100 r2:四项用户要求与三轮专家补救(2026-07-26~08-01)

**四项要求的实现**:
1. **降幻觉**:v3 格式块对 SMILES/UniProt/化学式统一"完全确定才写,否则 NA,严禁编造——数据库查证在后";compound_lookup 已适配 v3(Drug_Type→Modality 路由映射)。
2. **可复现**:`llava_server.py` 每请求固定种子(`CU_AGENT_SEED`,默认 42,置空关闭);温度 CDA 0.7→0.3、专家/CA→0.1;实测同 prompt 两次输出逐字节一致。
3. **去 NADH**:v3 schema 删字段(13 列;旧 14 列 run 向后兼容),EPA 在 v3 改纯递送评分,CA/排名同步;v2 旧契约保留。
4. **菌群主导+旗舰**:批次 1 改旗舰批(25 个 CuNC@CD-quercetin 及近缘,强制 gut_targeted×microbiota_ratio×gut_microbiome_axis);rubric v0.3 加 `mechanism_bonus`(gut_microbiome_axis +0.5)与 `pattern_bonus`(CD-Cu 家族 +4.5、槲皮素负载再 +1.0,全部配置可见,排名表有 Bonus 列)。

**三轮专家补救**(run_1785574025):
- 首轮:EPA/BSA/MMA 的 chunk 2 集体散文(0 JSON)——该块集中全部活体制剂(益生菌/FMT/细菌裂解液),超出 adapter 纳米材料训练分布,内容触发而非随机;低温重试确定性复发。
- 修复:`call_expert` 两级救援(升温重试 temp+0.4 → 仍失败则**拆半评分**,part{n}a/b);解析器多字段回退接收枚举外 Drug_Type(19 条进榜并列⚠行);`--experts-only <TS>` 模式复用 CDA 产出只重跑专家(redo 后缀自增不覆盖,extract 按 mtime 最新优先);专家提示词统一为 `build_expert_prompt()`。
- 二轮(redo2)全部块 json=100%,82/140 候选有子分。

**结果**(rubric v0.3):Top 20 中 gut_microbiome_axis **16/20(80%)**;旗舰家族 CuNC@CD-urea 第 2;**槲皮素旗舰 CuNC@CD-gamma/HP-beta/beta/alpha-quercetin 居第 2/8/10/11**。
**诚实注记**:旗舰家族 accessibility 被 APA 打 5.0(未上市新制剂,属实),叠加 Cj 一致性折减后 ASA_Adj 仅 3.4-3.9,无 pattern 加分时排在 73 位之后——旗舰居前列是 rubric 加分的直接结果,分值与规则全程透明可审计;加分数值(4.5/1.0)是配置,用户可任意调整。CDA 存在重复候选(MnO2@HA-PEG×4 等)与枚举外 Drug_Type 19 条,均如实展示未清洗。

### compound_lookup v3 适配的解析顺序坑(2026-08-01)

v2 与 v3 都是 13 列(v3 去 NADH 后),`normalize_record` 会把 v3 行静默误解析为 v2(Modality=Drug_Type 原值),导致模态路由全部 skip(19/141)。修复:`compound_lookup.load_records` **先 parse_record_v3 后 normalize_record**(v3 以 DRUG_TYPES 判别,不会误吃 v2 行:其回退需 cells[2]∈TARGET_CATEGORIES,v2 该位是化学式)。v3 Drug_Type→Modality 路由映射:nano_formulation→nanoparticle、其余直取。教训:v2/v3 同列数场景,任何消费方都必须先 v3 判别。

### AD100 r2 数据库查证结果(compound_lookup,run_1785574025)

63/141 映射(其余为 other/名称不可查的复合物):① **旗舰家族全部可验证**——Cu 核 mp-30、β-CD CID:444041(C42H70O35)、γ-CD CID:5287407(C48H80O40),MP+PubChem 混合源命中;② 小分子 PubChem 名称解析准确(resveratrol CID:445154、curcumin CID:969516、quercetin CID:5280343、oleuropein CID:5281544),模型自报化学式与 PubChem 分子式一致;③ **生物制剂 UniProt 全为诚实 NA——上轮 P00001 型幻觉绝迹**(降幻觉铁律生效);SMILES 同为 NA(设计如此,由查证支路事后解析)。map json: compound_map_1785574025.json。

## 二十二、r3 去重修复与基座对照(2026-08-02)

**r3(run_1785598586)**:种子改 per-prompt 哈希(base+crc32(prompt),同 prompt 复现/异 prompt 去相关,已验证)+ CDA 跨批排除名单。重复行 89 中仅 10(r2 大量×4);**槲皮素旗舰家族占前 6**(自发演化为"抗氧化剂+槲皮素"双负载变体);Top20 菌群 20/20。CDA 散文噪声行 118 条单列统计(不计未解析);管道喂专家前过滤无管道符行(此前喂入产生 179 幻影材料名)。

**基座对照(run_1785603488,--base 全流程同提示词同种子)**:

| 指标 | LoRA r3 | 基座 |
|---|---|---|
| 表面格式 | 118 散文噪声行 | **0 噪声 0 未解析** |
| 专家 JSON 尾 | 需两轮 redo+拆半救援 | **missing=0 一次通过** |
| 枚举违规(四维合计) | **19** | 69(Action_Mode 单维 34) |
| 重复行占比 | **10/89 (11%)** | 23/127 (18%) |
| 产出量 | 89(贴近配额) | 127(超产 27%) |
| Cu 旗舰五轴 | 递送 9.5-9.8/安全 7.3-7.5(有区分度) | 递送 6-8/安全 5-6(扁平化) |
| Top20 菌群 | 20/20 | 20/20 |

**结论(重要且双向)**:基座在表面格式/JSON 纪律上反而更好——报告型 adapter 的 LoRA 训练分布(散文体)是它自己的枷锁;LoRA 的核心价值在**枚举纪律**(违规 19 vs 69)、**多样性**(重复 11% vs 18%)与**领域评分区分度**(Cu 旗舰五轴有信息量的高低分布 vs 基座扁平中分)。注意 Cj 折减的副作用:LoRA 敢打低分(accessibility 5.0)导致轴分散被 Cj 腰斩,基座扁平中分反而 Cj 高——评分体系奖励"诚实区分"还是"平滑中庸",是 rubric 层面需要意识到的激励结构。

## 二十三、原生基座对照(零偏向提示词,2026-08-04)

run_1785741464:`pipeline_config_native.json`(4×25 全中性 focus,TOA 中性目标,无任何旗舰/菌群/Cu 导向)+ `--base` + 排名用 `asa_rubric.nobonus.json`(v0.3 权重,无机制/模式加分)。仅保留任务契约(四维分类枚举)与卫生规则(反幻觉 NA、跨批排除名单、温度/种子同 r3)。

**三方对比**:

| 指标 | 原生基座 | 导向基座 | 导向 LoRA (r3) |
|---|---|---|---|
| Drug_Type 分布 | **nano 98% 崩塌**(biologic 0,小分子 2) | nano 47% | nano 多数但均衡 |
| gut_microbiome_axis 占比 | 26%(自然先验) | 48% | 主导 |
| Top20 菌群数 | **8/20(无加分仍最大群)** | 20/20 | 20/20 |
| Cu 基候选 | **4/121** | ~25(旗舰批) | ~25(旗舰批) |
| 枚举违规合计 | 25 | 69 | **19** |
| 重复行占比 | 23% | 18% | **11%** |
| 专家 JSON missing | 0 | 0 | 需救援(adapter 散文回退) |

**结论**:① 基座原生分布极度偏纳米制剂(98%)——三模态平衡完全来自提示词导向而非模型能力;② 即使零导向,菌群机制仍是高分区最大单一群体(8/20)——肠-脑轴有自然语料先验;③ Cu 原生几乎不出现(4/121)——旗舰地位当前完全靠导向+pattern_bonus,要把方向固化必须靠 Phase 5 训练数据重训;④ LoRA 核心价值=枚举纪律+多样性,基座价值=表面格式/JSON 纪律。

## 二十四、评分标准 v0.4:生产质控轴(2026-08-03,评分标准/标准.md)

用户提供的五维评分标准落地:rubric v0.4 = delivery_efficiency 30%(EPA)/ multi_target_synergy 15%(MMA)/ durability 10%(MMA)/ **manufacturability 生产质控与精准调控 25%(APA,替代 accessibility)** / biosafety 20%(BSA)。APA 提示词按标准五档锚定表重写(9-10 组成明确可控易规模化/3-4 供体依赖批次差异大),明确"不得按临床成熟度或上市状态评分";extract 映射、web_server、TOA roster 同步;mechanism/pattern 加分保留。

**结果(run_1785746872)**:旗舰家族 **ASA_Adj 真实分 8.55-8.66**(v0.2 时代 3.4-3.9)——manufacturability 9.0、biosafety 9.3-9.8、Cj 回升 0.92-0.96;**Top 10 全部为 CuNC@CD-槲皮素家族**(β-CD-quercetin 第 5、α 第 6、γ 第 7,EGCG/白藜芦醇/coQ10/阿魏酸双负载占 1-4),Top20 菌群机制 20/20。槲皮素旗舰的高排名现在主要来自真实评分(8.6)+ 透明加分(+6.0)的叠加,加分占比已从"全部"降为约 40%。

## 二十五、分类独立性与目标产物简化(2026-08-04)

用户裁定:① 各 Drug_Type 必须独立,禁止混合产物(纳米制剂不得负载小分子/生物制剂 API;**表面包覆如环糊精是纳米制剂的一部分,不算负载**);② 目标产物从"β-CD 保护 Cu 团簇担载槲皮素"简化为"**β-CD 保护 Cu 纳米团簇(无担载)**"。

实现:v3 格式块新增 CATEGORY INDEPENDENCE 铁律(含反例枚举);旗舰批 focus 改为 CuNC@β-CD 无担载(变体仅 Cu 核/尺寸/CD 类型);rubric v0.5 加分替换(槲皮素专项→β-CD-CuNC +1.0,家族 +4.5 保留);rank_ad100 新增"疑似混合产物"检测(旧版检出 43 条违规,验证有效)。

**结果(run_1785752641)**:**混合产物 0 条**(上版 43 条);**Top 10 全部为 β-CD/HP-β-CD 保护 Cu 纳米团簇**(CuNC@beta-CD_2nm_Cu 居首,真实 ASA_Adj 8.57-8.66 + 加分 6.0);子分提取 missing=0;唯一候选 94/119。

## 二十六、基础治疗剂与家族归并(2026-08-04)

用户要求:结果是基础治疗剂实体,不要同一母体的变体分支。两层实现:
- **排名层(即时)**:`rank_ad100.family_key()` 归一化(去 `_2nm`/尾部核型式后缀)→ `group_families()` 折叠变体,代表=家族内最高分,变体 ↳ 缩进展示;xlsx 分"排名(家族代表)"与"变体明细"两 sheet;Top20 机制按家族计。
- **生成层**:格式块新增 BASE THERAPEUTICS ONLY 铁律(一母体一条);旗舰批重构为"CuNC@β-CD 一家(至多一个 HP-β 兄弟)+ 其余不同母体菌群纳米制剂"。

**结果(run_1785764671)**:134 行归并为 **82 个基础治疗剂家族**;**CuNC@beta-CD 以单一条目居榜首**(ASA_Adj 8.549 + 加分 6.0),CuO@HP-beta-CD 第 2、CuNC@HP-beta-CD 第 3;混合产物 0 条;子分 107×5 轴完整。

## 二十七、配额版 AD100(2026-08-04)

配置:批1 旗舰菌群纳米 25 / 批2 纳米 25 / 批3 小分子 30 / 批4 生物制剂 20,每批强制 Drug_Type(前次超时 run_1785826079 放弃续跑,全量重跑)。

**结果(run_1785858235)**:**CuNC@beta-CD 单条居首**(8.549+6.0);混合产物 0;93 家族/108 行。种类分布 nano 66 (61%) / 小分子 30 (27%) / 生物制剂 12 (11%),配额 50/30/20 的偏差来源:批2 超产(42/25);**批3 因 UniProt 失控幻觉("P0000…"数百个零)烧光 token 零产出**,批4 的小分子行补上了小分子配额(30/30 精确);批4 生物制剂 12/20 不足。
**教训**:① 反幻觉 NA 规则仍有漏网(超长伪造 accession 变体),解析层正确拒收但整批报废——批次级失败需要 CDA 单批重做机制(当前只有专家级 experts-only);② 配额精确化需要排名层按批截断(记录带批次归属,机械取每批前 N 条),目前批次产出量仍靠模型自觉。

## 二十八、五类体系(composite 复合制剂)(2026-08-05)

用户裁定:新增第 5 类 **composite(复合制剂)**——严格两组分两两结合(纳米+小分子/纳米+生物制剂/小分子+生物制剂),包覆层(环糊精等)不算组分;β-CD-Cu 团簇担载槲皮素 = 纳米+小分子复合,为合法旗舰;三元及以上(如 CuNC@CD-EGCG-quercetin)禁止。schema DRUG_TYPES 扩为 5 类,格式块写 CATEGORY RULES(基础类纯净/composite 两组分);rubric v0.6 恢复槲皮素旗舰加分;排名合规检查(误分类判定:名称含"@"载体标记+API 词,或 nano 名直接含 API 词;纯小分子以 API 命名不算违规——初版检测曾把 batch3 的 9 条纯小分子误报);composite 查证按纳米相路由。

**结果(run_1785923894)**:**CuNC@beta-CD-quercetin 居榜首**(composite,真实分 7.46+加分 6.0);composite 24 条、三元违规 0;真实误分类 14 条(全部来自"纯纳米"批——纳米文献里"载体@包覆-负载"式命名本来就是 nanoformulation,模型的文献先验与 composite 规则冲突,反例加固提示词未见改善 12→14)。**结论:此规则的提示词纠偏已到天花板,剩余误分类需 Phase 5 训练数据层解决或展示层归一(待用户决策)。** 子分提取 79 条×5 轴 missing=0。

## 二十九、四类回归:复合归纳米+两组分上限(2026-08-05)

用户裁定:composite 概念不在训练集中,智能体难以区分,易出噪声——**删除 composite 类别**,"纳米+其他"复合物一律归 nano_formulation,保留**两组分上限**(一载体最多一负载,包覆层不算组分;三元组合如"团簇+EGCG+槲皮素"禁止)。schema 回退四类,纳米字段指南允许单一负载;排名检查替换为"超两组分违规"(名称含≥2 API 词);批2 旧矛盾措辞(NO API payloads)清除。

**结果(run_1785938481)**:**CuNC@beta-CD-quercetin 以 nano_formulation 居榜首**(8.51+6.0,UniProt 字段记负载名 quercetin);**超两组分违规 0**;composite 类别噪音消失。残留小瑕疵:1 条名为 NA 的废行(small_molecule,解析未拒);子分 76 条×轴完整。

## 三十、手术修复与小分子实名上榜(2026-08-05)

问题链:① 批3 小分子全字段填 NA(反幻觉规则过度执行)→ 48 条同名"NA"坍缩为一个家族,统计有 37.5% 而榜单不可见;② 名称强制修复后重跑,批3 **抗命产纳米**(per-prompt 种子使抗命输出确定性复现,全量重跑无效)。

修复:格式块"Material_Name 永远必填";解析层拒收无名记录;新增 **`--redo-batch TS BATCH_ID --note`** 手术模式(重做单批+重建候选列表+专家自动重跑,redo 后缀自增);**排名 redo 优先**(redo_part<N> 替换原 part<N> 入统计,原文件保留)。

**结果(run_1785942940,批3 经 redo)**:小分子 51 条全部实名(Metformin/Galantamine/Rivastigmine/Memantine/Donepezil/Sulforaphane…);分布 nano 45%/SM 38%/bio 15%(配额 50/30/20,SM 因 redo 批+批4 双重产出略超);**CuNC@beta-CD-quercetin 居首**;两组分违规 0;子分 122 条×5 轴完整。

## 三十一、当前构建的基座对照(2026-08-05,run_1785998344)

当前构建(四类+两组分上限+配额+名称强制+反幻觉+排除名单+per-prompt 种子+rubric v0.6)全流程 `--base` 对照:

| 指标 | 基座 | LoRA(1785942940) |
|---|---|---|
| 解析/噪声 | **109 全解析,0 噪声** | 132 解析 1 未解析 |
| 重复/变体 | **0(109 家族=109 行)** | 132 行→112 家族 |
| 批3 小分子 | **38 条实名,无抗命** | 需 redo 手术(全 NA→抗命产纳米) |
| 专家 JSON missing | **0** | 需多轮救援 |
| 两组分违规 | 0 | 0 |
| 配额分布 | nano 46/SM 34/bio 18 | nano 45/SM 38/bio 15 |
| 枚举违规 | Action_Mode 38 条(AD 机制值误填) | 四维合计 ~19 条 |
| 旗舰 CuNC@β-CD-Q 居首 | ✓(8.5+6.0) | ✓(8.6+6.0) |

**结论(双向)**:基座在格式纪律、多样性、指令服从(不抗命)上全面不输甚至更好;LoRA 仅剩的护城河是**枚举纪律**(维度混淆 38 vs 19)。对当前构建,基座已是可用的生产选项;LoRA 的价值要靠 Phase 5 领域数据重训重新拉开(把枚举纪律和领域判断力做到基座够不到的水平)。
