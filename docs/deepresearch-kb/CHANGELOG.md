# 阶段变更与验收记录

## Phase 4 关键案例重跑结果

- `internal_paraphrase`、`quick_missing`、`holdout_stale` 各重合成一次 Adaptive；三份均完成。
- 同义改写仍保守升级 Deep；quick_missing 正确由 Deep 补足；stale 报告识别 superseded 状态但仍称证据矛盾。
- 共 693 input + 2483 output tokens，无 Tavily；详见 PHASE4_REPORT_EFFECTS.md。

## Adaptive live runner consistency

- live runner 现显式注入 requirement，实际路由不再使用 count-only baseline；Deep 仍强制 report_type=deep。
- 当前 requirement 以完整 query 作为单一 claim，适合连通性演示，不代表复杂问题自动分解已解决。

## Phase 4 成本配置一致性

- `run_adaptive_live.py` 暴露 `--max-deep-calls` 并将实际值写入 route.json。
- 实验配置不再隐式依赖路由器默认值；未改变既有默认 1 次 Deep 上限。

## Phase 4 成本边界 — Deep budget

- AdaptiveResearchRouter 新增 `max_deep_calls`（默认 1）；预算为 0 时明确返回 deep/insufficient，不调用 provider。
- 冲突在预算为 0 时保留 conflict/unknown，不伪装为 STOP；避免无限或意外 Deep 消耗。
- 离线反例已加入；正式成本实验仍需报告实际 token/latency。

## Phase 4 效果稳定性 — 三次重复路由

- 新增 repeat_effect_eval.py，对冻结 v2 的 12 例重复 3 次，比较 route 和调用矩阵。
- 该实验只验证确定性状态机稳定性，不把重复 fixture 运行当成独立模型样本或质量提升。
- 无 LLM/network/token；输出 Deep trigger rate 和路由稳定性。

## Judge usage assertion fix

全量回归发现测试硬编码单次模型 token 数，重跑后合理变化导致脆弱失败；改为校验 usage 结构与正值，不把单次运行 token 当固定契约。

## Stale holdout 重合成结果

- 补齐 superseded 历史警告后，Adaptive 正确采用 Deep 的非过期 PostgreSQL 证据；Fixed Hybrid 保守回答无法确定。
- 两份报告共 410 input + 1880 output tokens；旧 24 例统计保留，单案例改善不外推为总体质量提升。

## Stale holdout 重合成（待运行）

- 只重跑 holdout_stale 的 Fixed Hybrid/Adaptive 两份报告，使用新增历史警告，不重复整批 24 例。
- 每份报告独立采集 provider usage/latency；结果写入 Git 忽略的 data/evals/stale-rerun。
- 目标是验证时效信息传递是否改善模型判断，不根据结果修改 gold。

## Stale evidence replay 修复

- effect replay 补齐 superseded evidence 的 inferred effective_at/selection reason。
- report replay 对 superseded 内部证据追加历史警告；旧真实报告工件不覆盖，需显式重跑。

## 严格报告 judge-v2 结果

- 修正内部 citation URI 归一化后重跑 24 份报告：Fixed Hybrid 与 Adaptive 均 11/12 可接受、1/12 incorrect、0 unknown。
- 质量持平，不宣称 Adaptive 优于固定 Hybrid；错误分别是 Quick 不足停留、stale 状态缺失。
- Provider usage：12941 input + 62446 output tokens；无 Tavily 调用。

## 报告质量验证 — 严格语义 judge（待运行）

- 新增 `judge_effect_reports.py`：24 份 frozen v2 报告各一次 judge，检查 required claims、证据支持、citation、过期/冲突处理和保守拒答。
- gold answerable 与 required claims 从数据集读取；judge 不能改 gold。非法输出/异常为 unknown。
- 结果与 provider usage 单独保存；不覆盖人工 review matrix，也不把 judge 结果当绝对真值。

## 效果评测补充 — 人工复核矩阵

- 新增 `build_review_matrix.py`，为 24 份固定报告生成逐 claim/citation/stale 空白复核表。
- 空白标签是有意的：自动 URI/mention 诊断不替代事实蕴含判断；不把模型报告自行纠正路由错误算作 Adaptive 成功。
- 运行 `.venv/bin/python -m evals.deepresearch_kb.build_review_matrix` 可生成 Git 忽略的 review-matrix.json。

## Phase 4.5 — 报告级效果诊断（进行中）

- 新增 `score_effect_reports.py`，对固定 24 份报告计算目标 claim 字面提及、合法/非法引用 URI、保守拒答信号。
- 指标明确是诊断，不是 entailment、答案正确率或质量优越证明；人工复核清单仍保留。
- 运行前校验冻结 corpus/报告工件，失败与无法判断不被改写为通过。
- 首次运行发现旧工件的内部 `kb://` citation 与 sources.json 原始 source_uri 不是同一表示；评分器已规范化两种 URI，
  保留非法 URI 检查，不修改历史报告。

## 效果对照修复 — 否定 claim 重新评测

- 修正 `_claim_supported` 的否定匹配正则；原测试确认的错误提前停止现已不再发生。
- effect-v2 的旧 routing artifact 保留作历史，测试期望改为 holdout negation 不应 sufficient。
- 该修复只处理明确英文否定，复杂语义、双重否定和跨句关系仍需 judge/人工评估。

## 正式效果对照 — v2 真实报告合成

- 新 runner 读取已冻结路由结果，校验 dataset hash，不重做路由、不修改 gold。
- 12 例 × 固定 Hybrid/Adaptive 共 24 份真实模型短报告；交替执行两组，统一提示词和输出预算。
- 保存输入/来源/输出/usage/失败，固定材料调用不计作真实搜索成本；requirements 为显式给定而非模型生成。
- 真实质量审阅与总成本结论待报告完成后进行，不由路由准确率替代。
- runner 新增 `--case/--arm`，允许只重跑关键 holdout，避免为单个修复重复消耗 24 份报告 token。
- 24 份报告已生成；人工检查保留两项：negation 案例的 answerable gold 需复核，stale 案例需把治理状态传入 evidence。
  新增 review_effect_v2.py，只生成检查清单，不自动打分或修改冻结 gold。
- judge 首次运行发现内部 `kb://` 引用与原始 fixture URI 混淆，导致内部报告被错误判 citation error；
  已在 judge 输入中加入规范化 citation_uri，旧结果保留，需用新输出目录重跑 24 份报告评估。

## 正式效果对照 — v2 双组 fixture runner

- 固定 Hybrid 与 Adaptive 在同一 12 例上执行，分别保存证据、需求判定、终态和工具调用矩阵。
- 不将 fixture 次数当实际费用，不将字符串覆盖评分当答案正确率；gold 不传入路由判定。
- 冲突标签为本层 fixture 输入，不能据此声称冲突检测效果；后续真实模型对照需分开计费。
- 保留否定句被 substring 错误接受的留出集失败，当前仍未证明 Adaptive 质量不下降。

## 正式效果对照 — 冻结 v2 数据集

- 新建 effect_cases_v2.json：12 例，development/holdout 各 6；包括完整同义改写、否定、旧版、重复来源、来源要求、冲突及无证据。
- 与旧六例关键词 smoke test 分开；不继续改写 gold 迎合 substring 实现。
- holdout 在本轮比较中不用于调参；失败需原样报告。answerable 与 expected_route 独立标注。
- 本次只完成语料冻结及 schema 检查，尚未执行效果对照或宣称成本改善。

## 效果对照前置修复 — unknown 冲突状态

- 发现 run_with_conflict_checker 将缺少 conflict_detected 的 unknown 默认为无冲突，可能提前 STOP。
- 显式保留 unknown：执行一次 Deep 后终态仍为 unknown，不宣布充分；新增反例测试。
- 该策略可能增加调用，正式对照必须同时记录质量与成本，不把保守升级直接称为优化。

## 效果对照前置修复 — Deep 后状态

- Deep 返回证据后重新执行 requirement 判断；terminal_status 区分 sufficient/insufficient。
- 未解除的冲突保留 conflict，不因 Deep 调用结束自动视为已解决。
- 新增“Deep 返回无关证据”和“Deep 补齐关键事实”反例测试。
- 本轮仍不消耗 API token；正式对照尚待建立与运行。

## 效果对照前置修复 — 真正的 Deep Adapter

- 源码确认旧 run_adaptive_live 使用默认 research_report 且 return []，并非可用的 Deep 证据升级。
- 新增 UpstreamDeepResearch，强制 report_type=deep；返回带 URL 的实际 source records，不把生成的报告当事实。
- live 脚本已接线；离线测试验证 mode guard、来源归一化及丢弃无内容记录。
- 尚需 Deep 后再次评估、固定 Hybrid/Adaptive 对照和质量指标；不由本测试宣称效果提升。

## 效果对照前置修复 — judge 硬约束

- 核实旧 Router 只检查 judge.status，允许语义 judge 绕过版本/来源数等硬约束。
- 新增 grounded_judge_sufficient：必须有有效 claim IDs、无 missing claims，且所引用证据满足来源/时效/去重要求。
- Router 和 judge 校验层同时执行；补缺外部来源、废弃证据、同 URI 重复来源与空支持反例。
- 这是正式效果实验前的必要修复；尚未跑四路质量/成本对照，不宣称效果已经提升。

## Phase 4.4 — 效果评测数据集设计（进行中）

- 新增 `effect_dataset.json`：6 个可控案例，覆盖 STOP、Quick、Hybrid、Deep、Conflict、无证据。
- 新增 `EFFECT_EVALUATION_PLAN.md`：四路对照、数据分层、指标和隐私边界。
- 当前先跑合成 fixture；不把路由通过当作答案质量通过，不消耗 API token。
- 新增 `run_effect_eval.py` 与测试，按六个 gold case 验证 requirements 驱动路由；待运行。
- 首次运行 4/6：gold 使用整句自然语言改写，确定性 claim 匹配无法支持同义覆盖；已改为 evidence 中明确短 claim，
  保留语义改写作为后续 SufficiencyJudge 的输入，不放宽 deterministic 评分。
- 修正后效果路由 6/6；完整结论与限制见 PHASE4_EFFECTS.md。无 API token 消耗。
- 否定检测修复：明确 `not/no/false` 结构不再满足正向 claim；effect-v2 结果保持 Fixed Hybrid 4/12、Adaptive 9/12。
  holdout negation 的错误提前停止已消除；其余长语义/同义覆盖仍需 judge 或人工核对。

## Phase 4.3 — Claim coverage 与语义 judge 兜底（进行中）

- `EvidenceRequirement` 检查 required claims、source types、独立来源和 current version。
- `extract_claims` 为句子生成可追溯 claim/evidence IDs；不做隐式事实推断。
- `SufficiencyJudge` 仅在确定性检查不足时可注入 Router，严格校验 JSON 和 grounded claim IDs；失败为 unknown。
- Router 已支持 requirements + judge，fake judge 测试通过；真实 judge 和完整 Phase 4 对照仍待验证。

## Phase 4.3 — Requirement-based Evidence Sufficiency（进行中）

- 新增 EvidenceRequirement/RequirementResult：逐项检查 required claims、source types、独立来源数和 current version。
- `extract_claims()` 只暴露可审计 evidence，不做隐式语义推断；`assess_requirements()` 未满足即明确列出缺失原因。
- 默认 AdaptiveResearchRouter 行为暂不改变；本切片先建立确定性 coverage baseline，测试无 token。
- 结构化 claims 按句拆分并保留 claim/evidence IDs；新增可注入 SufficiencyJudge，严格校验 JSON、claim grounding，失败为 unknown。
- 三步增强中的 deterministic coverage 与 claim extraction 已完成；LLM judge 仅提供 fallback 接口，尚未接入自适应路由。
- 真实 judge runner 已加入：仅使用合成 evidence，分别验证 sufficient/insufficient；结果保存 data/evals，未调用搜索。
- 真实 judge 运行通过 2/2：sufficient 与 insufficient 各 1/1，386 input + 515 output tokens；无 Tavily 调用。

## Phase 4 最终验收（2026-09-13）

- Phase 4.1 固定路由 4/4，冲突直接 Deep；真实 STOP 与 Quick 路由工件已保存。
- Phase 4.3 deterministic claim/source/version coverage、结构化 claims、可选 semantic judge 已完成；真实 judge 2/2。
- 项目测试最终回归通过；路由记录调用、证据、原因和耗时。
- 仍明确限制：coverage 规则和 judge 不是通用事实充分性证明；unknown/缺失证据继续保守升级。
- Phase 4 完成后不自动进入 MCP 或多 Agent 扩展；下一阶段需先由实际失败决定是否优化 coverage/成本。

## Phase 4.1 — Evidence Sufficiency 路由状态机（进行中）

- 新增 `EvidenceSufficiency` 与 `AdaptiveResearchRouter`：足够→STOP，不足→Quick，Quick 不足→Deep，Conflict→Deep。
- 支持注入 Phase 3 conflict checker；不创建模型客户端、不修改 upstream。
- 固定路由评测已修复冲突顺序问题并达到 4/4；本轮无 token。
- 尚未接入真实 upstream Quick/Deep、route trace 或最终对照验收。

## Phase 4.2 — 真实 Quick/Deep Adapter（待运行）

- 新增 `run_adaptive_live.py`，使用已有 GPTResearcher quick_search/conduct_research 作为 Adapter。
- 保存 route.json：最终路由、决策原因、evidence 数、Quick/Deep 调用数和耗时。
- 运行前需凭据；限制为单问题，不自动重试循环；尚未执行，不能宣称真实路由闭环成立。

## Phase 4 最终验收

- 固定路由 4/4；冲突顺序失败已修复为直接 Deep。
- 真实运行：内部充分案例 STOP（无 Quick/Deep）；内部不足案例 Quick=1 后停止；route.json 已归档。
- 相关测试与 Phase 3 回归通过；项目仍不宣称事实充分性已解决，阈值与质量评估限制见 PHASE4_ACCEPTANCE.md。

## Phase 4.1.1 — 路由顺序失败修复

- 首次固定评测 3/4：冲突案例错误先走 Quick，违反 conflict→Deep 要求。
- 修正状态机为冲突直接 Deep；保留失败记录，不调整 gold。

## Phase 3.9 — 版本治理报告层验收（进行中）

- 固定 current/history/future/deprecated 四时点案例，验证 governed evidence context 的版本与 Selection 字段。
- 离线 runner 与测试已加入；无 LLM、无 token。冲突真实评测另行归档。

## Phase 3 最终验收（2026-09-13）

版本治理固定对照 6/6，报告 provenance 4/4，真实冲突 reviewer 5/5；Phase 3 专项与全量项目回归通过。
已完成 effective time/status/authority、current/as-of、向量/词法一致、CLI/研究入口、冲突 unknown 契约。
Phase 4 的充分性判断、自适应 Quick→Deep 仍未实现，不能把本阶段描述为自适应研究系统。

## Phase 3.8.5 — 固定语义反例集（待真实运行）

- 固定五对合成内部/外部证据：同时间矛盾、跨时间变化、不同主体、同义表述、范围不明。
- gold 在运行前写入 conflict_cases.json；评测区分 valid unknown 与解析失败 unknown。
- runner 每完成一对就保存结果和 provider usage，不覆盖旧结果。
- 尚未执行模型调用；不能据接口测试宣称 conflict recall 达标。

## Phase 3.8.6 — 真实语义冲突评测（2026-09-13）

- 五对固定证据使用已配置 DeepSeek reviewer，覆盖 conflict、跨时间 compatible、不同主体、paraphrase、unknown。
- 5/5 valid review 且 prediction 与 gold 一致；每对均有 grounded quotes/references。
- Provider usage：1350 input + 1708 output tokens；无 Tavily 调用；结果在 Git 忽略的 data/evals/phase3-conflicts-v1.json。
- 这是固定小样本的冲突契约验证，不代表通用 conflict recall；unknown 仍是合法不确定结果。

## Phase 3.8.4 — 显式真实 reviewer 入口（进行中）

- configured_conflict_checker 复用 upstream Config/GenericLLMProvider，不另建模型客户端。
- run_research --check-conflicts 显式开启附加模型检查，usage 与报告合成共用采集器。
- 默认关闭，未执行真实调用；后续固定矛盾/兼容/时间不同案例需验证模型输出与引用。

## Phase 3.8.3 — 冲突结果进入报告

- run 接受显式 conflict_checker，保存 conflicts.json 并把结构化结论传入 synthesis context。
- reviewer 的 unknown 状态进入 manifest/context，明确不能视为无冲突；不自动裁决来源真假。
- 离线测试验证 unknown 归档及报告委托；真实模型 reviewer 工厂和固定反例仍待完成。

## Phase 3.8.2 — 语义冲突检查契约（进行中）

- 新增可注入异步 reviewer 的 SemanticConflictChecker，逐证据对返回 conflict/compatible/unknown。
- 强制引用原文子串、有效证据编号、完整 pair 覆盖和理由；无效输出归为 unknown，不冒充无冲突。
- 提示词要求比较同主体、时间和适用范围；不裁决真伪、不因 authority 隐藏矛盾。
- 本轮只验证契约，真实模型反例、报告接入和冲突 recall 评测尚未完成。

## Phase 3.8 — 冲突检查基础（进行中，非完整冲突检测）

- 新增同文档多版本共选提示，保留所有版本引用；同版本多个 chunk 不误报。
- run_research 保存 conflicts.json，并把结构提示传给报告，不作事实裁决。
- semantic_conflict_status 明确为 not_evaluated；不能将不同文本/不同版本直接算作事实矛盾。
- 尚需语义冲突 Adapter、内外部矛盾/非矛盾案例、报告层对照与全阶段验收。

## Phase 3.7 — 固定版本选择对照（进行中）

- 同一文件按“当前→历史→未来”导入，固定六个时点/状态预期，不根据实现调整 gold。
- 比较原 KnowledgeStore.retrieve 与治理 retrieve；重开数据库后执行。
- 只评版本选择，不把通过数写成报告正确率、冲突检测效果或通用 stale error 改善。
- 全阶段仍需冲突提示、报告层比较及逐项完成审计。

## Phase 3.6 补充 — 排序与来源一致性

- 修复治理向量结果遗漏 effective_at_inferred 的问题，避免将推断时间展示成明确时间。
- authority 排序增加反例：未来高权威文档、无关高权威文档均不能挤掉有效相关来源。
- 版本标识拒绝 bool/非整数，避免 Python bool 被当作版本 1。
- 本轮仍为工程验证，不宣称语义冲突检测或 Phase 3 对照已完成。

## Phase 3.6 — 向量时间选择统一（进行中）

- chunk 导出与向量重建新增 include_all_versions；保留原默认 active 快照供 Phase 2 对照。
- search_governed 复用 VersionGovernance.select，再做向量相似度与 authority 排序。
- 历史所需 chunk 缺失时明确要求全版本重建，不以空结果冒充没有历史证据。
- 测试涵盖重开、迟到版本、历史时点与无需重新 embedding 的 metadata 选择。
- 冲突提示、固定对照和最终验收尚未完成。

## Phase 3.5 — 研究入口治理策略（进行中）

- GovernedKnowledge 为一个研究任务绑定固定查询时点，复用既有 retrieve 接口。
- run_research 支持 --governed/--as-of/历史与废弃包含开关，manifest 保存完整选择参数。
- Hybrid 历史内部证据与 live external 时间语义明确分开；不把实时网页冒充历史快照。
- 离线报告测试验证实际选择历史版本、context 中状态及 sources/run 工件。
- 尚未完成向量选择统一、冲突检测与全阶段对照，Phase 3 保持进行中。

## Phase 3.4 — CLI 治理入口（进行中）

- govern 设置指定 document/version 的 effective_at/deprecated_at/authority。
- retrieve --governed / --as-of / --include-superseded / --include-deprecated 接入治理选择。
- 未带治理参数的 retrieve 暂保留 Phase 2 行为用于对照；不静默改变既有演示。
- CLI 测试覆盖设置、历史时点、废弃时点以及显式显示废弃证据；向量和研究入口仍待接入。

## Phase 3.3 — 治理词法检索与 Evidence（进行中）

- VersionGovernance.retrieve 先确定时间有效版本，再匹配 FTS，迟到旧版不能因关键词命中进入结果。
- 合格匹配内按显式 authority、相关性排序；未用 authority 覆盖时间选择。
- Evidence/context 增加 effective_at、status、authority、选择理由及推断时间标记。
- 现有默认 KnowledgeStore.retrieve 尚保持 Phase 2 baseline；后续 CLI/研究入口需显式接线并统一向量策略。

## Phase 3.2 — 治理 metadata 持久化（进行中）

- 新增 version_governance 附属表，不重写原始 document_version/Chunk/引用身份。
- 旧版本以 ingested_at 回填生效时间并标记 effective_at_inferred=1；显式修正后设为 0。
- metadata 校验与写入使用事务，支持重开恢复、迟到历史版本和 KB 隔离测试。
- 当前只接 metadata/版本选择；现有 retrieve/向量/报告尚未切换，不能宣称时效治理已端到端生效。

## Phase 3.1 — 版本选择语义（进行中）

- 已核对 Charter 与现有 SQLite：原 active 只表示最后导入，不能表示事实生效。
- 新增 PHASE3_PLAN.md，列出全阶段验收条件；未把范围缩为 metadata 字段扩展。
- 新增独立 version_policy：带时区有效时间、历史包含开关、废弃后不回退、同时间修订选择。
- 首批测试覆盖迟到旧文档、未来文档、历史时间、废弃边界、重复身份和无时区输入。
- 尚未接 SQLite/CLI/向量/研究流程，Phase 3 未完成；不产生 API token 消耗。

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

## Phase 2.5 — 接入 upstream sub-query（2026-09-13）

| 子步骤 | 状态 | 结果 |
| --- | --- | --- |
| 1. 输入 Adapter | 完成 | `plan_from_upstream_subqueries()` 接收上游字符串列表，不重复生成 sub-query |
| 2. 策略标注 | 完成 | 项目规则只负责给上游子问题添加 source_policy/rationale |
| 3. 计划执行 | 已完成 | Phase 2.2 的 `execute_plan()` 逐题分流并保留 PlannedEvidence |
| 4. 回归测试 | 完成 | 验证原始 query 不被替换、子问题顺序和策略保持 |
| 5. 真实 upstream planner | 待运行 | 需要模型调用；运行后记录 planner 输出、策略误判与 token |

这一步的边界是“复用上游分解、扩展来源需求”；不把规则分类器包装成通用语义理解。

## Phase 2.5.5 — 真实 upstream planner 验证（2026-09-13）

- 入口 `evals/deepresearch_kb/run_upstream_planner.py` 只执行一次 upstream `plan_research()`，不收集证据、不写报告。
- 运行前检查 DeepSeek/Tavily 凭据；输出 subqueries、规则策略标注、耗时和上游成本估算。
- 尚未运行；待本轮代码提交后执行，执行结果写入 Git 忽略的 `data/evals/`。
- 实际运行一次后发现首个子查询因“production architecture”误标 Hybrid；规则将泛化 architecture 当作内部信号。
  已收紧为明确项目归属词（our/project/team/internal/constraint），保留该失败作为 Phase 2 误标案例。
- 重跑 upstream planner 后 3 个子查询均正确标为 external；约 6.32 秒，上游成本估算 0.01746 USD。
  结果保存为 `data/evals/upstream-planner-v2.json`（Git 忽略）；这是策略标注验证，不是研究质量结果。

## Phase 2.6 — 计划驱动运行入口（2026-09-13）

| 子步骤 | 状态 | 结果 |
| --- | --- | --- |
| 1. Planner seam | 完成 | `run_planned()` 调用 upstream `research_conductor.plan_research()`，不复制 query generation |
| 2. Policy execution | 完成 | 复用 `execute_plan()`，逐子问题调用声明的 internal/external Adapter |
| 3. Artifact output | 完成 | 保存 `plan.json`、`evidence.json`、`report.md`；空 evidence 明确跳过报告 |
| 4. Offline integration | 完成 | fake upstream planner/reporter 验证计划顺序、策略和报告委托 |
| 5. Real planned run | 待运行 | 需要一次 DeepSeek/Tavily 调用；运行后记录策略误标、token 和 evidence coverage |

Phase 2 仍未完成：还需真实计划驱动运行与固定评测；不在此阶段加入 sufficiency/自适应升级。

## Phase 2.6.5 — 真实计划驱动运行（2026-09-13）

- 新增 `run_planned_live.py`，执行一次 upstream planner，再按项目 source policy 分流，最后统一合成。
- 使用 DeepSeek + Tavily，需本机凭据；不调用 Deep Research，仅 planner + quick search + synthesis。
- 本次运行结果待完成后写入 Git 忽略的 `data/evals/`；任何策略误标或外部失败原样记录。
- 首次运行已完成并写入 `data/evals/planned-live-v1/`：upstream 生成 3 个子查询并完成报告。
  发现规则缺陷：`production` 被字符串包含误判为 `project`，一个外部题误标 internal；
  已改用词边界匹配，必须重新验证后才能宣称该入口正确。
- 修正规则后再次运行 upstream planner：3 个子查询均标为 external，约 6.93 秒，上游成本估算 0.019905 USD。
  结果写入 `data/evals/upstream-planner-v3.json`；策略误标问题在该样例上已消除，但规则仍不是通用语义分类器。

## Phase 2.3 — 按子问题归属渲染报告上下文（2026-09-13）

| 子步骤 | 状态 | 结果 |
| --- | --- | --- |
| 1. 计划上下文渲染 | 完成 | `render_planned_context()` 按子问题分组，保留 Source Policy 与 provenance |
| 2. 上游报告委托 | 完成 | `write_planned_report()` 只传 `ext_context`，不修改 upstream writer |
| 3. 空证据处理 | 完成 | 无命中时不构造 reporter，返回明确 skipped 结果 |
| 4. 离线验证 | 完成 | 覆盖 question/policy 不丢失、空上下文和报告委托 |

当前仍是透明规则 planner；尚未让 upstream planner 自动决定来源策略。

## Phase 2 最终验收（2026-09-13）

Phase 2 最小目标已完成：upstream sub-query → 结构化 source policy → 按题 Adapter 执行 →
子问题归属 Evidence → upstream synthesis。固定规划 5/5、调用矩阵 5/5、项目测试 49 passed。
真实 planner 和计划驱动运行均已执行，结果和限制见 `PHASE2_ACCEPTANCE.md`。
保留失败：父任务的“我们的项目”语义可能不会传播到外部子查询；当前不宣称通用策略准确率，
也不进入 sufficiency/adaptive research。下一阶段需先解决任务级 source requirement 传播或建立人工标注评测。
