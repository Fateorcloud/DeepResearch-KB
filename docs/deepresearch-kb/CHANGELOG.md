# 阶段变更与验收记录

以 PROJECT_CHARTER.md 为准。历史接口步骤见 scope.md；本文件从 Phase 1.11 起记录每个子步骤。

## Phase 1.11 — 本地持久化向量索引（2026-09-12）

| 子步骤 | 状态 | 结果/验收 |
| --- | --- | --- |
| 1. 检查旧 Adapter | 完成 | 发现重复追加、top-k 后过滤及旧版本遗留；旧通用 Adapter 仍是演示接口，不推荐用于生命周期管理 |
| 2. 实现小语料快照 | 完成 | PersistentVectorIndex 使用真实 LangChain InMemoryVectorStore；JSON 原子发布，显式全量重建 |
| 3. 重复重建/恢复 | 完成 | stable chunk IDs，重新实例化后恢复向量，重复重建数量不增长 |
| 4. KB 与版本隔离 | 完成 | SQLite active chunks 为准，排序前过滤；未索引的新版本暂缺失，不返回旧版本顶替 |
| 5. 失败保护 | 完成 | embedding 失败保留旧文件，embedding_id 不匹配拒绝打开，临时文件清理 |
| 6. 回归验证 | 完成 | GPTR_BLOCK_NETWORK=1 下项目 25 项测试通过；无 API token 消耗 |

运行：`GPTR_BLOCK_NETWORK=1 .venv/bin/python -m pytest tests/deepresearch_kb -q`。

范围：本地小语料、单写者、全量重建；不是向量数据库服务。测试使用离线确定性 embedding，
不代表语义质量测试。KB 在一次 search 开始时取 active 快照，不承诺与并发 ingest 的线性一致性。
调用者必须提供准确的 provider/model/dimension 组成的 embedding_id。

## Phase 1 余下工作（未完成）

1. 真实 External/Hybrid：凭据检查、正确配置 researcher factory、空证据拒答、保存报告/来源/usage/latency。
2. 固定评测：内部/外部/Hybrid 案例与黄金事实，迁移旧数据和索引同步回归，upstream 对照及失败记录。

注意：现有 demo 的 fake external 返回空列表，reporter 只拼接文本；它没有展示真实外部证据或真实报告。
历史记录中的“接口已完成”不等于 Phase 1 端到端验收完成。

## Phase 1.12.8 — 外部与 Hybrid 真实验证（2026-09-12）

- External Quick Search + DeepSeek report synthesis succeeded for “What is SQLite?”；输出 5 条外部来源，耗时约 41.39 秒。
- 上游报告成本显示 0.12757 USD，但 DeepSeek 使用 OpenAI-compatible endpoint，旧计价不可靠；真实 token 未采集。
- Hybrid first run exposed FTS punctuation bug (`?` in natural-language query) and was stopped before report generation。
- 修复后需重新运行 Hybrid；本记录只保留失败原因，不把首次失败算作完成。
- 修复 FTS 后 Hybrid 首次完成，但内部证据未命中：自然语言 query 的 `AND` 约束过严（内部文档没有 “what/is”）。
  已改为安全 token `OR`，下一轮需确认内外部 evidence 同时落盘；这是证据覆盖失败案例，不计作最终指标。

## Phase 1.12 — 真实运行入口准备（2026-09-12）

| 子步骤 | 状态 | 结果/验收 |
| --- | --- | --- |
| 1. 凭据检查 | 完成 | WSL 环境及项目 .env 未配置 OPENAI_API_KEY / TAVILY_API_KEY；未输出密钥 |
| 2. 空证据处理 | 完成 | 无 evidence 不构造 reporter，避免 upstream 空 ext_context 回退到旧 context |
| 3. Live factory | 已实现、待真实验证 | 显式 role/agent，quick_search + write_report，不运行 conduct_research 或 Deep Research |
| 4. 归档入口 | 完成离线验证 | 每次独立目录，report.md / sources.json / run.json；失败也存状态 |
| 5. 指标口径 | 完成 | 保存 latency、上游报告 cost；未取得的 tokens/search cost 为 null，不伪装总费用 |
| 6. 测试 | 完成 | 28 项项目测试通过，包括 Hybrid 双来源归档、空证据和失败记录 |
| 7. 真实 External/Hybrid | 待凭据 | 尚未消耗 API token，尚无真实报告或引用正确性结果 |

准备本地 .env 的 OPENAI_API_KEY 和 TAVILY_API_KEY（不要写入 Git 或聊天），然后执行：

```sh
.venv/bin/python -m deepresearch_kb.run_research 'SQLite' --mode hybrid --kb KB_ID
```

该命令按当前 upstream 配置使用模型，默认输出 data/runs/<run_id>。
第一轮建议一个明确问题、一次 quick_search 和一次报告合成，不运行 Deep Research。
还需完善普通问句的 FTS 输入处理、旧数据库回填、真实 usage 回调和固定评测；不能宣称 Phase 1 已完成。

## Phase 1.12.7 — 首次真实 Internal 合成验证（2026-09-12）

- DeepSeek 模型与 API Key 配置有效；TAVILY_API_KEY 仍为空，未执行 External/Hybrid。
- 导入无敏感信息的合成 TXT 文档，查询 SQLite，命中 1 条内部证据并调用真实报告合成。
- run ID：00b7cf7e29ea4db8b9444373f80b6051；本地 data/smoke/runs/ 下保存报告、sources.json、run.json。
- 耗时 15.42 秒，报告包含内部文件 URI 引用。仅完成连通性与引用存在检查，非引用正确性评测。
- 上游显示费用 0.044475 USD，但本路径使用 OpenAI-compatible DeepSeek，旧计价可能不适用；
  不作为真实费用，真实 token 数未采集。已消耗模型 API token，未运行搜索/embedding/Deep Research。
- 发现记录问题：run.json 的 research_path 固定写 quick_search，Internal 实际没有搜索；后续修正。
- 保留烟雾测试输入与数据库用于复查；均在 Git 忽略的 data/ 内。下一步等待搜索凭据或选择仅内部评测。

## Phase 1.12.8 — External/Hybrid 真实验证（2026-09-12）

- TAVILY_API_KEY 已配置；External Quick Search + DeepSeek synthesis 成功，5 条 external evidence，约 41.39 秒。
- 首次 Hybrid 暴露 FTS `?` 语法错误；随后暴露自然语言 `AND` 过严导致内部 evidence 丢失。
- 改为安全 token `OR` 后 Hybrid 重跑成功：run `55d106ebf2f94420a4ec90314117d9da`，1 条 internal + 5 条 external，约 34.62 秒。
- 上游估算费用 0.11491 USD，不代表 DeepSeek 实际账单；准确 token 数仍为 null。未运行 Deep Research。

## Phase 1.13 — 固定检索评测准备

| 子步骤 | 状态 | 验收/结果 |
| --- | --- | --- |
| 1. 固定语料与 gold | 完成 | 2 个 KB、当前/历史文档、干扰文档，6 个固定查询 |
| 2. 可复现 runner | 完成 | 重建临时 DB、重开后检索；记录输入 hash、commit、dirty 状态，失败返回非零 |
| 3. 独立评分 | 完成 | precision/recall 与精确集合匹配；未知分母为 null |
| 4. 首次运行 | 已运行，有失败 | 5/6 通过；自然语言问题被公共词 is 污染，precision 0.5 |
| 5. 报告级对照 | 未开始 | 仍需 upstream/KB-only/Hybrid 固定输入、引用支持检查和可信 usage |

本轮无 API 调用。失败保存在 data/evals/retrieval.json。下一步按失败驱动改善词法查询，
同时增加保留关键词/专名的反例，避免只针对单个问题调参。

## Phase 1 三组收尾 — 最终验收

| 子步骤 | 状态 | 结果 |
| --- | --- | --- |
| A1 公共词噪声修复 | 完成 | 原 gold 不变，5/6 → 6/6；引号短语与大写缩写保留 |
| A2 旧版本数据库回填 | 完成 | 缺 Chunk/缺 FTS 两种旧结构均恢复；失败回滚可重试；版本历史不丢 |
| A3 索引同步 | 完成 | 向量快照重建幂等，检索前用当前 SQLite 版本过滤；新内容显式 rebuild |
| A4 不可变引用回查 | 完成 | kb:// 指向 document/version/chunk；CLI resolve 支持已被替代版本 |
| B1 固定输入与 gold | 完成 | 3 个研究问题、当前/废弃方案/干扰文档、2 个已核对官方摘录 |
| B2 真实三组运行 | 完成 | upstream Hybrid 回放、KB-only、项目 Hybrid 各 3 份报告，无 Deep Research |
| B3 事实/引用支持核对 | 完成 | 目标事实支持 9/9、4/9、9/9；KB-only 缺 5 条外部事实时明确不可答 |
| B4 留档 | 完成 | 9 份 report/context/sources/metrics，语料 hash、依赖快照、Codex 人工 review 均保存 |
| C1 指标口径 | 完成 | provider usage、调用数、延迟；actual cost 未知为 null，旧估算不作为账单 |
| C2 执行路径与失败 | 完成 | Internal 不再标为 quick_search；失败留存已收集来源；空证据不调用模型 |
| C3 演示与文档 | 完成 | 离线双来源 fixture、真实网络命令、报告对照回放、引用回查均有说明 |

验证命令及最终结果见 PHASE1_ACCEPTANCE.md。合并上游测试时曾出现 sys.modules stub 串扰，
使用上游 CI 同样的 --forked 隔离后相关测试通过；没有为此改 upstream。
最终验证：38 项项目测试 + 3 项相关 upstream 回归，共 41 passed；原固定检索集 6/6。
真实对照消耗 8285 input + 21078 output = 29363 provider tokens；没有 Tavily 付费调用。
主张限制：upstream 和项目 Hybrid 在本组 gold 均正确；不宣称质量超越上游或完成自适应研究。
仍有长问句/项目名召回干扰文档、英文 FTS 分词边界，作为 Phase 2 的问题输入保留。

## Phase 2.1 — 结构化来源规划基线（2026-09-13）

| 子步骤 | 状态 | 结果 |
| --- | --- | --- |
| 1. 定义计划模型 | 完成 | `ResearchPlan` / `PlannedQuestion`；每个子问题有 source_policy 与 rationale |
| 2. 实现规划器 | 完成 | RuleBasedSourcePlanner，规则透明、无 LLM、未修改 upstream |
| 3. 固定 gold | 完成 | 5 个 internal/external/hybrid/约束/一般问题案例 |
| 4. 离线评测 | 完成 | 首次 4/5；`current project` 被误判 Hybrid；修正规则后 5/5，gold 未调整 |

当前只验证来源策略表达和可归因分类，不证明 LLM planner 质量，不执行检索或报告生成。
失败记录：将“current”同时当作项目状态和外部时效会造成不必要 External 路径；已拆分语义并保留该反例。

## Phase 2.2 — 按计划执行来源（2026-09-13）

| 子步骤 | 状态 | 结果 |
| --- | --- | --- |
| 1. 子问题执行接口 | 完成 | `ResearchOrchestrator.execute_plan()` 逐题使用声明的 source_policy |
| 2. 归属结果模型 | 完成 | `PlannedEvidence` 保留 question、policy 和 Evidence provenance |
| 3. 来源隔离测试 | 完成 | internal 题不调用 external；external 题不调用 KB；混合计划逐题分流 |
| 4. 失败边界 | 完成 | internal/hybrid 缺少显式 KB ID 直接报错，避免隐式全库查询 |

本轮仍不接 upstream planner/LLM；计划由透明规则或未来人工/LLM Adapter 产生。

## Phase 2.4 — 来源策略执行评测（2026-09-13）

| 子步骤 | 状态 | 结果 |
| --- | --- | --- |
| 1. Adapter 调用计数 | 完成 | fake internal/external Adapter 统计每道子问题的实际调用 |
| 2. policy-call gold | 完成 | internal=KB only、external=Web only、hybrid=两者 |
| 3. 路由评测 | 完成 | 5/5 案例调用矩阵通过；无 LLM、无网络、无 token 消耗 |
| 4. 研究级接入 | 未开始 | 仍需把 upstream 生成的 sub-query 映射到计划，保留原始 query planner |

当前已证明 source_policy 会改变 Adapter 调用，但尚未证明规划器能正确分解真实复杂任务；
下一步接入 upstream sub-query 作为计划输入，再评估 source policy 对证据覆盖和无关调用的影响。

## Phase 2.3 — 按子问题归属渲染报告上下文（2026-09-13）

| 子步骤 | 状态 | 结果 |
| --- | --- | --- |
| 1. 计划上下文渲染 | 完成 | `render_planned_context()` 按子问题分组，保留 Source Policy 与 provenance |
| 2. 上游报告委托 | 完成 | `write_planned_report()` 只传 `ext_context`，不修改 upstream writer |
| 3. 空证据处理 | 完成 | 无命中时不构造 reporter，返回明确 skipped 结果 |
| 4. 离线验证 | 完成 | 覆盖 question/policy 不丢失、空上下文和报告委托 |

当前仍是透明规则 planner；尚未让 upstream planner 自动决定来源策略。
