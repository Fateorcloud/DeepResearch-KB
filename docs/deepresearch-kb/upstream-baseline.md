# Upstream 基线记录（尚非实测评测基线）

- 审计提交：`6f998577d547b1e54ec662dac63583aa11e3b84b`。
- 项目声明版本：0.14.7；本机 WSL 系统 Python：3.12.3。
- 本切片不修改 `gpt_researcher/`、依赖清单或原始应用入口。
- 上游维护杂项删除属于此前清理；四个应用目录保留。
- 环境依赖锁定、真实模型运行、Web/Local/Hybrid 报告与质量/成本数据尚未冻结。
- 2026-09-12：系统 Python 未安装 langchain_community / pytest；使用标准库 unittest
  完成 8 项离线契约测试，全部通过。DocumentLoader 调用契约已测，真实解析及全量上游测试未运行。

## 后续真实解析验证

2026-09-12 使用 uv 建立项目 `.venv`（CPython 3.12.13），安装 `-e '.[test]'`。
在 `GPTR_BLOCK_NETWORK=1` 下运行项目测试，包含真实 upstream TXT 解析、上传随机文件名映射、
重启恢复以及不支持格式的失败回滚。真实 TXT 导入已验证；其余格式、向量检索与端到端研究未验证。
该环境并非完整依赖锁定；不将它描述为冻结了质量/成本 baseline。
最后一次验证：项目测试 11 项 + upstream DocumentLoader/VectorStore guard 2 项，共 13 项通过。
已有 pytest 配置项和 LangChain 弃用警告未在本次修改。

源码事实：`agent.py` → `skills/researcher.py` → `actions/query_processing.py` /
`skills/context_manager.py` → `skills/writer.py`。Local/VectorStore 的 planner 仍会搜索；
Hybrid 两路独立规划后拼接。`document/document.py` 输出 raw_content/url，url 只保留 basename；
`vector_store/vector_store.py` 接收调用者的存储对象，不管理 KB 生命周期。
因此 ingest 在外围保存稳定 provenance，不使用 loader 的 basename 作为文档 ID。

复用评测候选：`evals/simple_evals/`、`evals/hallucination_eval/`、
`deep_agents/hybrid_benchmark.py` 和 `deep_agents/benchmark_data/`。
现有仓库结果不能作为本次开发的实测结果；需冻结案例、模型/配置、原始报告/来源、失败记录与计费口径。
