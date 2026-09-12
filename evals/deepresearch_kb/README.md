# 固定检索回归集

运行：`.venv/bin/python -m evals.deepresearch_kb.run_retrieval`。
输出 `data/evals/retrieval.json`；失败返回非零退出码，保留逐例结果、数据 hash、代码提交和 dirty 状态。
语料包含当前/旧版本、另一 KB 的同名文档和无关办公文档。解析用确定性文本 loader，SQLite/FTS 为真实实现。

指标按返回的 `(logical_path, version)` 集合计算 precision/recall；空分母为 null。
通过要求集合完全相同，因此多召回的无关文档也会失败。这不是答案、引用支持度或语义质量评测。

首次运行 5/6：`What is SQLite?` 的 precision=0.5、recall=1；OR 将 is 也作为匹配词，
误召回 operations.txt。保留作为改进前失败案例，不调整 gold 配合实现。
尚无 upstream、KB-only、Hybrid 报告对照，不能由此声明 Phase 1 全部完成。
