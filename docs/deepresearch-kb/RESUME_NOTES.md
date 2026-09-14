# Resume Notes

## Project One-liner

Knowledge-enhanced deep research system built on GPT Researcher, adding persistent internal knowledge, version governance, evidence-driven adaptive routing, and traceable artifacts.

## Verified Results

- 111 automated tests passed; Phase 3 version selection baseline 2/6, governed 6/6.
- Phase 4.5: 12 frozen cases, Adaptive route 12/12; 24 paired reports with fallible judge Adaptive 10/2/0 and Fixed Hybrid 7/2/3 (correct/unanswerable/incorrect).
- Official MCP ClientSession over stdio completed the tool chain and preserved source URI/version metadata.

## Safe Claims

Implemented the orchestration and product boundary around GPT Researcher. Demonstrated favorable results only on the small frozen evaluation.

## Claims Not Allowed

Do not claim production-ready, general benchmark superiority, universal routing accuracy, cost reduction, or implementation of Deep Research/GPT Researcher/MCP from scratch.

## Resume Bullets

- 针对深度研究无法理解项目内部历史与约束的问题，在 GPT Researcher 之上设计 SQLite 持久化知识层，建立 DocumentVersion、content hash 和 provenance 生命周期；版本选择案例由 baseline 2/6 提升至 governed 6/6。
- 将来源规划、版本治理、证据充分性和冲突安全策略接入统一 `ResearchEngine`，实现 STOP/Quick/Deep 自适应执行；12 个冻结案例中 Adaptive 路由命中 12/12。
- 构建 Fixed Hybrid vs Adaptive 可复现实验与报告审查链路，完成 24 份 paired reports；明确标注 fallible judge 与不能外推的限制。
- 以 Service Layer 复用同一 KnowledgeStore 和 Research Core，提供 FastAPI、目录导入、远程 push 和 5-tool MCP facade，并通过官方 ClientSession stdio smoke 验证 task/report/sources 链路。
