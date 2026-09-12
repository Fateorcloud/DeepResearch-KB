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
