# DeepResearch-KB

本项目明确是基于 [GPT Researcher](https://github.com/assafelovic/gpt-researcher) 的二次开发，
新增持久化知识层和研究编排实验；上游能力与本项目贡献边界见 [PROJECT_CHARTER.md](PROJECT_CHARTER.md)。
产品目标和贡献边界见 [PROJECT_CHARTER.md](PROJECT_CHARTER.md)。

## 项目定位

在 GPT Researcher 的外部深度研究能力之上，增加持久化内部知识、版本治理与证据驱动的自适应研究，让已有资料与最新外部信息共同支持可追溯研究结论。

Deep Research 擅长最新外部信息，但不了解项目历史和内部约束；普通 KB/RAG 能查已有资料，却不会主动判断何时需要外部研究，也容易受到旧版本污染。DeepResearch-KB 将 Persistent KB、Version Governance、Adaptive Research 和 Traceable Evidence 组合成统一执行链。上游 Web/Local/Hybrid/Deep Research 不属于本项目新增贡献。

当前验证：111 tests passed；Phase 4.5 使用 12 个冻结案例完成 paired evaluation；Phase 5B 通过官方 MCP ClientSession 的真实 stdio smoke。

## 主架构

```text
Local Folder / Repo -- ingest / push --┐
Web Upload ----------------------------+--> KnowledgeService
                                             |
                              SQLite KnowledgeBase
                         Document / Version / Chunk
                                             |
User Query --> ResearchEngine --> planning / governed retrieval
                                  --> sufficiency / STOP / Quick / Deep
                                  --> evidence synthesis
                                             |
                                  report / sources / trace / metrics

CLI ---------┐
REST --------+--> Service Layer
MCP ---------┘

Quick / Deep / DocumentLoader / synthesis / provider abstraction
are reused from GPT Researcher upstream.
```

已追加：Chunk/FTS5、显式研究 Adapter，以及基于 LangChain 的本地向量快照。
Phase 1 三组收尾已完成：检索/旧数据兼容、固定报告对照、指标与可重复演示。
上游已有的 Web/Local/Hybrid/Deep Research 不属于本项目新增贡献。
结果、限制和完整演示见 [Phase 1 验收](docs/deepresearch-kb/PHASE1_ACCEPTANCE.md)。
Phase 2 的来源规划验收见 [Phase 2 验收](docs/deepresearch-kb/PHASE2_ACCEPTANCE.md)。
Phase 3 的版本治理验收见 [Phase 3 验收](docs/deepresearch-kb/PHASE3_ACCEPTANCE.md)。
Phase 4 的自适应路由验收见 [Phase 4 验收](docs/deepresearch-kb/PHASE4_ACCEPTANCE.md)。
每阶段子步骤见 [变更记录](docs/deepresearch-kb/CHANGELOG.md)。

## 本地运行（WSL，Python 3.12）

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/python -m deepresearch_kb create '项目资料'
.venv/bin/python -m deepresearch_kb list
# 使用 create 返回的 id；请替换文件路径
.venv/bin/python -m deepresearch_kb ingest KB_ID /path/to/design.txt --logical-path architecture/design.txt
.venv/bin/python -m deepresearch_kb versions KB_ID architecture/design.txt
GPTR_BLOCK_NETWORK=1 .venv/bin/python -m pytest tests/deepresearch_kb -q
.venv/bin/python -m deepresearch_kb.demo
.venv/bin/python -m evals.deepresearch_kb.run_retrieval
.venv/bin/python -m evals.deepresearch_kb.summarize_reports
```

默认数据库为 `data/kb.sqlite`（不提交 Git），可用 `--database` 指定。
不需要 LLM/Search API key 即可运行本地导入；各格式仍需 upstream 对应解析依赖。

## 保留与停用

`backend/`、`frontend/`、`multi_agents/`、`deep_agents/` 保留作上游参考，默认不启用。
Compose 的应用服务仅在显式选择 `--profile upstream` 时启动。没有改写这些应用的直接启动脚本。
Terraform、插件分发、Discord/npm 集成、根目录旧译版 README 和上游 Issue/PR 工作材料已裁剪。
`docs/docs/`、`docs/blog/` 仍是上游资料，非本项目已实现能力说明。

项目契约：[scope](docs/deepresearch-kb/scope.md)；基线状态：[baseline](docs/deepresearch-kb/upstream-baseline.md)。
当前项目状态：[PROJECT_STATUS](docs/deepresearch-kb/PROJECT_STATUS.md)。

统一执行入口 `deepresearch_kb.engine.ResearchEngine` 已完成受控集成验证；详见 [Phase 4.5a execution](docs/deepresearch-kb/PHASE4_5A_EXECUTION.md)。
Phase 4.5 real-project evaluation 已完成 12 案例双臂对照与 24 份真实模型报告；详见 [Phase 4.5 验收](docs/deepresearch-kb/PHASE4_5_ACCEPTANCE.md)。
Phase 5A 已提供独立 FastAPI、Web Upload、`ingest-dir` 与 `push-dir`；详见 [Phase 5A 验收](docs/deepresearch-kb/PHASE5A_ACCEPTANCE.md)。

## MCP Integration

Phase 5B 提供五个薄 MCP tools，复用现有 Service Layer；详见 [Phase 5B 验收](docs/deepresearch-kb/PHASE5B_ACCEPTANCE.md)。
保留 upstream 历史与 MIT [LICENSE](LICENSE)，基线提交 `6f998577d547b1e54ec662dac63583aa11e3b84b`。
