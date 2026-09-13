# Phase 4 效果评测与数据集

## 数据集策略

数据分三层：

1. **Controlled synthetic**：当前 `effect_dataset.json`。事实、版本、冲突和缺失项完全可控，用来验证路由因果。
2. **Project corpus**：从项目架构文档、ADR、历史决策中抽取；只在本地运行，不把私人资料提交 Git。
3. **Frozen external**：运行前保存公开官方页面摘录、URL、抓取日期和 hash；避免开放 Web 漂移污染对照。

## 四路对照

- `upstream_baseline`：原始 GPT Researcher 流程。
- `kb_only`：只提供内部证据。
- `fixed_hybrid`：内部和外部固定都查。
- `adaptive`：按 EvidenceRequirement 决定 STOP/Quick/Deep。

每个 case 保存 query、evidence、route trace、report、sources、token、latency、失败类型。

## 主要指标

- target claim coverage / correctness
- citation source correctness
- stale knowledge error rate
- conflict detection recall
- Deep Research Trigger Rate
- Quick/Deep calls、provider tokens、latency

路由正确不等于答案正确；所有报告必须继续人工核对或独立 judge。样本先小后扩，不把合成集结果外推成生产质量。

## 当前执行顺序

1. 用合成集跑四路 fake/fixture 对照，不消耗 token。
2. 修复路由与 requirement gold 的失败案例。
3. 冻结项目 corpus 和公开 external 摘录。
4. 用真实模型跑小批量四路，明确预算和 token。
5. 汇总质量不下降前提下的成本/延迟变化，再决定是否扩展。

运行合成路由 smoke test：`.venv/bin/python -m evals.deepresearch_kb.run_effect_eval`。
