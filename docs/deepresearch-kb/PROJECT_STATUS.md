# DeepResearch-KB 当前状态

本项目是基于 GPT Researcher 的二次开发，目标是让持久化内部知识参与多步骤外部研究。上游 Web Research、Local Documents、Vector Store、Citation、Deep Research 和 MCP 均属于复用能力。

## 已完成阶段

| 阶段 | 当前证明 |
| --- | --- |
| Phase 0 | upstream 调用链、Local/Hybrid、Vector Store、成本和扩展边界完成审计 |
| Phase 1 | SQLite KB/document/version/chunk、ingest、FTS/向量快照、Internal/External/Hybrid、来源 lineage |
| Phase 2 | sub-query → source policy → 按题执行 → PlannedEvidence → upstream synthesis |
| Phase 3 | effective time、current/as-of、deprecated、authority、版本引用和冲突提示 |
| Phase 4 | requirement/claim coverage、STOP/Quick/Deep 路由、冲突升级、指标和效果对照 |

## 证据

- 92 项项目测试通过（网络阻断、forked 隔离）。
- 版本选择固定案例：Phase 2 baseline 2/6，治理后 6/6。
- 来源路由固定案例：Adaptive 10/12，Fixed Hybrid 4/12；三次重复稳定。
- 24 份真实模型报告：两组均 11/12 correct-or-unanswerable；质量持平。
- Adaptive 的 Deep 调用更多；没有总成本下降证据。

## 当前边界

- 证据充分性支持显式 claims/source/version 约束；复杂语义仍需 judge 或人工核对。
- 当前没有自动事实裁决、Graph RAG、Multi-Agent 扩展、MCP 产品层或复杂 Web UI。
- 真实效果数据是小型合成/冻结语料，不能外推为通用 benchmark。
- 评测中的 provider token 可记录；DeepSeek OpenAI-compatible 路径的实际账单仍不由系统推算。

## 下一步候选

优先扩大真实项目问题和未参与调参的 holdout，验证质量不下降前提下的成本变化；只有观察到明确集成需求后才考虑 MCP 或 Web/API 入口。

详细子步骤与失败记录见 [CHANGELOG.md](CHANGELOG.md)，阶段验收见 PHASE1/PHASE2/PHASE3/PHASE4 文档。
