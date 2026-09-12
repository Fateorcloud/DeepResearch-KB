# Phase 1 验收与演示

状态：三组收尾已完成。范围为小型本地持久化 KB + 显式研究闭环；不是 Charter 最终产品全部完成。
后续 Phase 2—5 不在此次验收内。项目始终明确基于 GPT Researcher 二次开发。

最终检查：38 项项目测试 + 3 项相关 upstream 回归，使用 --forked 共 **41 passed**。
源码比较确认 `gpt_researcher/` 与上游基线无差异。既有 pytest 配置和 LangChain 弃用警告保留。

```sh
GPTR_BLOCK_NETWORK=1 .venv/bin/python -m pytest --forked tests/deepresearch_kb tests/test_document_loader_error_message.py tests/test_vector_store_doc_guards.py tests/test_quick_search_summary_context.py -q
```

## 1. 检索与兼容性

- 统一 ingest；KB/document/version/chunk 持久化与来源 metadata。
- 原始版本数据回填 chunks，旧 chunks 重建 FTS。事务失败可重试，不覆盖版本内容。
- 查询去掉少量英文功能词，保留引号内短语和大写缩写。原固定案例 gold 不变，5/6 → 6/6。
- 向量快照复用 LangChain：重建幂等、原子替换、重开恢复、按 KB/current version 在 top-k 前过滤。
- 内部报告使用 kb:// 引用；CLI resolve 可回查指定版本/chunk，包括已被替代版本。

## 2. 固定报告对照

3 个合成问题（内部当前方案、外部 WAL、混合选型），每组 3 份真实模型报告，共 9 份。
模型：DeepSeek 官方兼容端点的 deepseek-flash；完成调用上报 input/output token。
两段 SQLite 官方摘录在评测前已核对并冻结。三组均不做实时搜索；不是 Tavily 搜索质量评测。

上游组运行原始 Hybrid 的 planner、DocumentLoader、context compressor 与 writer，仅替换外部 retriever
为固定材料回放并统一输出 prompt/预算；原源码未修改。每路 MAX_ITERATIONS=1。
项目组使用固定策略，无 LLM planner。调用数下降是流程差异，不是已证明的自适应优化。

| 三份报告合计 | 上游 Hybrid 回放 | KB-only | 项目 Hybrid |
| --- | ---: | ---: | ---: |
| 正确且有来源支持的目标事实 | 9/9 | 4/9 | 9/9 |
| 明确因无材料而无法回答的目标事实 | 0 | 5 | 0 |
| 错误目标事实 / 把旧方案当现状 | 0 / 0 | 0 / 0 | 0 / 0 |
| 完成的 LLM 调用 | 9 | 3 | 3 |
| 输入 token | 5251 | 1241 | 1793 |
| 输出 token（按 API usage，包括服务返回的推理消耗口径） | 8496 | 5240 | 7342 |
| 耗时合计（秒） | 38.10 | 24.15 | 33.29 |
| 回放 retriever 调用 | 12 | 0 | 3 |

人工核对：Codex 对照原始 context 逐份阅读，不是独立盲评。只按预声明目标事实判断覆盖与支持；
关键词命中仅是诊断，不能将“资料未提供 WAL”误判成回答了 WAL。九份报告均无引用到不存在的 Source；
这不是通用 citation benchmark。样本仅 3 个、单次运行，不报告显著性或泛化质量提升。

工件：`evals/deepresearch_kb/results/phase1-v1/` 中保存全部报告、上下文、来源、指标、手工核对、
语料 hash 与运行时提交/dirty 状态。此次是在未提交的收尾工作树上运行，manifest 如实记录 dirty=true。
依赖快照：`evals/deepresearch_kb/requirements-phase1.txt`（CPython 3.12.13）。

## 3. 指标与演示

`run_research` 区分 internal/external/hybrid 的实际路径；记录模型调用数、provider usage、search adapter
调用数、耗时、失败类型和 context。错误后保留已收集证据；空证据不调用模型。
`actual_cost_usd` 与未知 Tavily 计费为 null，旧 upstream 估算另存并警告，不当作 DeepSeek 账单。
本轮报告对照总计 15 次完成模型调用，8285 input + 21078 output = 29363 tokens；没有 Tavily 付费调用。

在 WSL 仓库根目录执行：

```sh
# 1. 零 API 成本：真实本地 ingest、更新到 v2、重开、双来源 fixture 合并
.venv/bin/python -m deepresearch_kb.demo
# 2. 零 API 成本：重跑固定检索评测
.venv/bin/python -m evals.deepresearch_kb.run_retrieval
# 3. 零 API 成本：重算已归档报告的评测摘要
.venv/bin/python -m evals.deepresearch_kb.summarize_reports
# 4. 真实模型对照（消耗模型 token，不实时搜索；输出目录必须是新的）
.venv/bin/python -m evals.deepresearch_kb.run_reports --output data/evals/my-phase1-run
```

自有文件/真实网络演示（使用 create 返回的 KB_ID）：

```sh
.venv/bin/python -m deepresearch_kb create '我的资料'
.venv/bin/python -m deepresearch_kb ingest KB_ID /path/to/design.txt --logical-path design.txt
.venv/bin/python -m deepresearch_kb retrieve 'SQLite' --kb KB_ID
.venv/bin/python -m deepresearch_kb.run_research 'What is SQLite?' --mode hybrid --kb KB_ID
# run 输出目录保存 report.md、context.txt、sources.json、run.json。
# 将报告中的 kb:// URI 传入同一数据库的 resolve，查看准确版本证据：
.venv/bin/python -m deepresearch_kb resolve 'kb://DOCUMENT_ID/versions/2/chunks/CHUNK_ID'
```

`.env` 仅在本机：DEEPSEEK_MODEL、DEEPSEEK_API_KEY 和 TAVILY_API_KEY；官方 URL 已配置。
不要把私有语料提交进 Git。离线 demo 的 external/reporter 是 fixture，不能展示成真实模型输出。

## 已知边界与 Phase 2 输入

- 本次只验证英文查询；默认 FTS 中文分词、同义改写、长复杂问题不保证效果。
- 长问句中的项目名仍会带入办公干扰文档，报告也会加入无关背景；固定六例通过不等于召回完美。
- 新 ingest 后向量快照必须显式 rebuild；旧 snapshot 不返回旧版本，但可能暂时缺少新证据。
- 旧通用 LangChainVectorIndex/Builder 仅为早期接口实验；生产式生命周期路径使用 PersistentVectorIndex。
- 单写者、小语料、全量快照；未做服务器并发压力测试或真实 embedding 质量评测。
- current 是最后导入版本，尚无 as-of/authority 治理；历史问题需显式 resolve，不自动检索旧方案。
- 评测没有证明项目 Hybrid 优于 upstream Hybrid；工程贡献是持久化/来源身份/可审查执行与评测闭环。
- Phase 2 应围绕“来源需求选择、无关背景、缺证据”设计实验，不先扩 Agent、MCP 或企业功能。
