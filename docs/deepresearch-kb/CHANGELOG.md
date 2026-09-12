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
