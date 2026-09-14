# Interview Guide

## 项目介绍

30 秒：这是一个基于 GPT Researcher 的知识增强深度研究系统，把持久化内部知识、版本治理和外部最新信息接入同一研究流程，并根据证据决定 STOP、Quick 或 Deep。

2 分钟：普通 RAG 只能回答已有资料，Deep Research 擅长外部信息但不了解项目历史。项目用 SQLite 保存带版本和 provenance 的文档，按子问题做来源规划和 current/as-of 治理；证据不足时升级 Quick/Deep，最后由上游 synthesis 生成带来源报告。ResearchEngine、Service Layer、FastAPI 和 MCP 统一这条链路。

5 分钟：按 failure cases 讲 stale version -> governance、negation false positive -> gate 修复、Quick insufficient -> Deep、conflict/unknown -> 保守 unresolved；再展示 12-case paired evaluation 和 MCP stdio smoke，强调小样本与 fallible judge 限制。

## 深挖问答

- **为什么不是普通 RAG？** RAG 不负责来源选择、时效治理或研究深度决策；核心是 orchestration。
- **为什么需要 DocumentVersion/content_hash/logical_path？** 路径定义身份，hash 提供幂等，版本保留不可变快照，避免旧事实覆盖当前事实。
- **为什么 SQLite 足够？** 当前目标是小型、可审计的单机闭环，没有伪装成高并发生产存储。
- **Evidence Sufficiency 做什么？** 用显式 required claims/source/version 约束决定证据是否足够，避免“调用完成”等于“问题已回答”。
- **为什么 Fixed Hybrid 对照？** 隔离固定一次 Quick 与自适应升级的差异；12/12 只说明本冻结 suite 命中 gold。
- **为什么 judge 不是真值？** judge 仍是模型，可能误判，因此保留人工复核和 unknown 边界。
- **为什么加 Service Layer？** REST、CLI、MCP 必须共享同一业务 contract，避免入口复制治理和研究逻辑。
- **为什么 task_id？** 研究是长任务；当前单进程 asyncio executor 快速返回，但重启会丢失内存状态。
- **MCP 与上游 MCP 有何区别？** 上游提供 client/retriever；这里暴露本项目的持久 KB、治理检索和 Research task。
- **如果生产化？** PostgreSQL/pgvector、durable queue/worker、object storage、RBAC 和 tracing 是未来路径，不是当前实现。
