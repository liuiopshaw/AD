# Nano-Bio Evaluator 系统修复与优化工作总结

> 会话时间: 2026-07-17 ~ 2026-07-19
> 范围: 架构审查、工程修复、Cu 优化目标系列、工具链修复、基座对照实验、输出目录约定
> 系统文档: `E:/Cu-agent/NANO_BIO_SYSTEM.md`(随各轮修复同步更新)

---

## 一、起点与系统架构

任务起点:审查 `NANO_BIO_SYSTEM.md` 设计的智能体架构并修复问题。系统现状:

```
用户请求 → FastAPI Server (port 8000)
              ├── Qwen3-VL-8B 基座模型 (~17.5GB VRAM, bf16)
              └── 8 个 LoRA Adapter (PEFT 热切换,加载后 fp32→bf16)
                   TOA 调度 / CDA 设计 / EA 抽取 / APA 抗菌
                   EPA 酶活 / BSA 安全 / MMA 机理 / CA 汇总
              └── agent=base 通道(disable_adapter,对照实验用)
科学目标: 面向阿尔茨海默症肠脑轴干预的纳米材料虚拟筛选
         (选择性抗菌 + NADH 类酶活性 + 生物安全性 = ASA 综合目标,
          核心方向: 环糊精包覆铜纳米团簇)
```

---

## 二、工程修复清单(全部完成并验证)

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 1 | Adapter 切换 502/503、初始 apa 常驻 2.3GB | 启动未设 `current_agent`;切换失败模型无 adapter | `llava_server.py` 重写状态机:启动即记录、失败自动恢复、未知 agent 返回 400 |
| 2 | 长推理中服务器"假死"被客户端误杀 | 同步 `generate()` 阻塞事件循环,`/health` 挂起 | 推理移入 worker 线程 + 锁串行化,实测 15 分钟推理中 `/health` 0.24s 响应 |
| 3 | task_100 管道执行两遍 | 同一管道同时存在于模块级和 `__main__` | 删除模块级副本(346→232 行) |
| 4 | CDA 40+ 分钟卡死 | **显存天花板**: 基座 17.5GB + fp32 LoRA(最大 3.7GB)+ 长上下文 KV cache 顶死 24GB,分配器 thrashing,速度 40 tok/s → 近停滞(实测 1500 token=37s,4000 token>600s) | ① LoRA 加载后 fp32→bf16(显存减半)② CDA 拆 4×25、EPA/MMA 各拆 2 块 ③ timeout 2400s,ReadTimeout 不重试。修复后 4000 token **95s**,峰值 19.2GB |
| 5 | `batch_eval_100.py` 完全不可用 | 调用不存在的 `/v1/multi-agent` 端点 | 改用 `/v1/chat/completions`,补存 EPA 原始输出 |
| 6 | `discover_materials.py` 多处 | `max_tokens` 硬编码覆盖参数;加载 `.env.example`;调用不存在的 `mp.run()` | 全部修正(`mp.search_materials()`) |
| 7 | TOA 反复输出"拒绝" JSON | 提示词让它评估虚构"ASA 指标"的可行性而非做路由 | 改纯路由提示词(agent 输出未动,只改输入),立即产出正确计划 |
| 8 | 长生成结果因客户端超时丢失 | 服务器生成 40-90 min,客户端先超时,结果随死连接丢弃 | **服务器生成落盘** `outputs/server_responses/`,客户端可轮询捞取;同时启用 sdpa |
| 9 | MP 工具链从未工作 | `.env` key 是占位符(用户提供有效 32 位 key 后解决) | 用户提供 key 后 MP 启用验证成功 |

---

## 三、Cu 优化目标系列(五轮演进)

目标:榜单中 Cu 材料在"直接抗菌(direct_antibacterial)× 重塑菌群(microbiome_remodeling)"上的频率控制。全部通过**提示词工程 + 展示层机械统计**实现,未触碰任何 agent 输出与 LoRA 权重。

| 轮次 | 目标 | 手段 | 结果 |
|------|------|------|------|
| 1. 基线测量 | — | `rank_cda_outputs.py` 机械统计 | Cu 11%、Cu∩两者 **0%** |
| 2. 频率提升 | 提高 Cu∩两者 | CDA 3 批 Cu 专攻 + 标签优先规则 | Cu 73%、Cu∩两者 73%(过度) |
| 3. 精确校准 | Cu∩两者 = **20%** | 批次配额化: 20 旗舰(Cu×两标签) + 25 Cu×其他 + 55 非 Cu | **精确命中 20 个**;新增 Chemical_Formula 字段(10 字段) |
| 4. 结构完善 | 化学式可信 + 配体可见 + 类别回归 | `formula_lookup.py`(MP+PubChem);CDA 第 11 字段 Ligand;排名恢复 Material_Category | 30/31 化合物解析;配体全覆盖(PEG/GSH/citrate/CD...);Cu 为两者兼备最高频 ✅ |
| 5. 自然化 | Cu 前列但不刻意 | 旗舰批保留,第 2 批改"多元素混合、Cu 不主导",各批加多样性约束 | 全榜 **Fe×24、Cu×21**(Cu 居第二,自然);Cu 18%;Cu∩两者 20 命中 |

**当前约束集合**(排名文档自动检验): Cu∩两者兼备 ≈20%、两者兼备中 Cu 最高频、材料类别展示、配体展示、数据库查证化学式、全榜元素频率 Top8。

---

## 四、工具链与 API

- **`scripts/formula_lookup.py`**(新建): 对 CDA 产出做化学式数据库查证——无机相→Materials Project、有机配体→PubChem name 端点(**混合源**);严格元素符号校验(修复了 `Tannic`→Ta、含数字化学式误杀两个分词器 bug);原始响应与映射均落盘,排名表自动附加 `DB_Formula` 列(工具数据,不覆盖 agent 原值)
- **API key 盘点结论**: 真正必需的只有 `MATERIALS_PROJECT_API_KEY`(已配);`NCBI_API_KEY` 可选提速(已给 `nanolit_search_tool` 补上 key 消费逻辑);DrugBank 付费按需;Qwen/Neo4j/PG/GDB/MolPort/EAS 均为旧 CrewAI 遗产,当前架构不需要
- **配体查证命中示例**: glutathione CID:124886、citrate CID:31348、tannic acid CID:16129778、cyclodextrin CID:320760、ZIF-8 CID:15245636

---

## 五、基座对照实验(原始 Qwen3 vs LoRA 管道)

方法: 服务器新增 `agent=base` 通道(`disable_adapter()`),单次调用、同任务提示词(去 Cu 优化);Cu 优化版任务脚本备份为 `scripts/task_100_materials.cu_optimized.bak.py`。

| 指标 | 基座(单次调用) | LoRA 管道 |
|---|---|---|
| 产出数量 | 181(超产 81%,模板循环) | 111(贴近配额) |
| 11 字段格式合规 | 99.5% | 高 |
| **direct_antibacterial 使用** | **0 个(完全没用该枚举值)** | 64-97% |
| Cu∩两者兼备 | 0 | 20(配额命中) |
| 类别均衡 | 偏斜(124 单原子模板化) | 四类覆盖 |
| 耗时 | ~72 min(2.4 tok/s) | ~25 min |

**结论**: 基座守得住表面格式,守不住约束纪律(配额、枚举、多样性)与领域判断(出现 "PEG-stabilized Zn single atoms" 类错误)。LoRA 微调+批次化管道的价值在约束遵循与领域判断。衍生工具: `rank_to_excel.py`(xlsx 导出,含去重模式——基座输出 181 行去重 105 行后仅 76 种独特材料)。

---

## 六、输出目录约定(2026-07-19 起)

每次测试的所有产出保存到独立文件夹 `outputs/run_<时间戳>/`:

- `scripts/output_utils.py`: `run_dir()`(生产脚本建目录)、`find_run_dir()`(消费脚本读取,自动回退旧平铺布局)
- 已接入 8 个脚本: task_100_materials、run_base_task100、formula_lookup、rank_cda_outputs、rank_to_excel、discover_materials、batch_eval_100
- 历史平铺文件原样保留;`server_responses/` 为系统级安全网保持平铺
- 约定已写入 `NANO_BIO_SYSTEM.md` 与 `CLAUDE.md`

---

## 七、日常使用流程

```powershell
cd E:\Cu-agent\scripts
python llava_server.py                    # 启动服务器(约 1 分钟)
python task_100_materials.py              # 跑管道(自动复用/启动服务器)
python formula_lookup.py                  # 数据库查证化学式(自动用 MP)
python rank_cda_outputs.py                # 生成排名 MD
python rank_to_excel.py                   # 导出 Excel(加 dedup 参数去重)
```

---

## 八、遗留问题与后续建议(按优先级)

1. **管道缺 APA(抗菌)与 BSA(安全)两个步骤** — ASA 三支柱目前只有酶活被独立验证;基础设施已稳定,可直接接入
2. **ASA 评分应确定性化** — 目前由 CDA 生成时自报;应由各专家 agent 出子维度分、代码按权重(40/25/15/10/10 等)加权 + Cj 一致性融合
3. **训练数据扩量** — BSA(50)、CA(50)、CDA(70)过薄;455 篇文献利用率低;要把 Cu 偏好固化进模型应靠 Cu 富集训练数据重训,而非长期依赖提示词
4. **评估基准** — 用 batch_eval_100 的 100 个已知材料建立带标准答案的测试集,量化 LoRA 准确率
5. **direct_antibacterial 标签占 97%** — 干预手段分布也可用批次配额思路校准
6. **推理期工具调用** — agent 生成时无法主动查证,幻觉化学式只能靠事后 lookup 暴露

---

## 九、关键文件索引

| 文件 | 作用 |
|------|------|
| `scripts/llava_server.py` | 服务器:LoRA 热切换、bf16 转换、线程化推理、生成落盘、agent=base 通道 |
| `scripts/task_100_materials.py` | 主管道(TOA→4×CDA→2×EPA→2×MMA→CA,批次配额) |
| `scripts/task_100_materials.cu_optimized.bak.py` | Cu 优化版备份 |
| `scripts/run_base_task100.py` | 基座对照(单次调用,支持落盘轮询) |
| `scripts/formula_lookup.py` | 化学式数据库查证(MP 无机 + PubChem 有机) |
| `scripts/rank_cda_outputs.py` | 排名 MD(机械排序+目标指标统计) |
| `scripts/rank_to_excel.py` | 排名 Excel(支持文件模式与 dedup) |
| `scripts/output_utils.py` | 每测试一文件夹约定 |
| `outputs/run_<TS>/` | 每次测试的全部产出 |
| `NANO_BIO_SYSTEM.md` | 系统文档(问题 2/4/5/6/7 修复记录 + 第十一节优化目标全记录) |
