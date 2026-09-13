# DeepResearch-KB

本项目明确是基于 [GPT Researcher](https://github.com/assafelovic/gpt-researcher) 的二次开发，
新增持久化知识层和研究编排实验；上游能力与本项目贡献边界见 [PROJECT_CHARTER.md](PROJECT_CHARTER.md)。
产品目标和贡献边界见 [PROJECT_CHARTER.md](PROJECT_CHARTER.md)。

## 当前状态

已实现：SQLite KB/document/version 持久化、统一单文件 ingest、来源 metadata、
内容 hash、重复导入幂等、版本历史与本地 CLI。默认复用 upstream DocumentLoader。

已追加：Chunk/FTS5、显式研究 Adapter，以及基于 LangChain 的本地向量快照。
Phase 1 三组收尾已完成：检索/旧数据兼容、固定报告对照、指标与可重复演示。
真实 External/Hybrid 已连通；三案例九报告对照已归档。证据充分性判断与自适应研究仍未实现。
上游已有的 Web/Local/Hybrid/Deep Research 不属于本项目新增贡献。
结果、限制和完整演示见 [Phase 1 验收](docs/deepresearch-kb/PHASE1_ACCEPTANCE.md)。
Phase 2 的来源规划验收见 [Phase 2 验收](docs/deepresearch-kb/PHASE2_ACCEPTANCE.md)。
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
保留 upstream 历史与 MIT [LICENSE](LICENSE)，基线提交 `6f998577d547b1e54ec662dac63583aa11e3b84b`。
