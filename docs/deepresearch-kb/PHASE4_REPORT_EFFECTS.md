# Phase 4 报告效果复核

## 关键案例重跑（2026-09-14）

使用修复后的回放入口，对 `internal_paraphrase`、`quick_missing`、`holdout_stale` 各重合成一次 Adaptive 报告。

| 案例 | 路由 | 报告观察 |
| --- | --- | --- |
| internal_paraphrase | Deep | 单句同义改写未被 deterministic coverage 识别，保守升级，增加成本；报告本身正确 |
| quick_missing | Deep | Deep 补足 local disk 事实，报告正确区分 Quick 缺失与 Deep 证据 |
| holdout_stale | Deep | 报告识别 superseded SQLite 与 Deep PostgreSQL 的时间/状态差异，但仍称“证据矛盾”，需要人工确认当前事实 |

三次合成共 693 input + 2483 output provider tokens；没有 Tavily 调用。该样本证明历史警告能进入上下文，
也保留了“过度保守/仍称冲突”的质量限制。不能从三例推导质量提升或成本下降。

## 当前效果结论

- 路由在冻结 12 例上为 Adaptive 10/12、Fixed Hybrid 4/12；三次重复稳定。
- 24 份原始报告的严格 judge：两组均 11/12 correct-or-unanswerable。
- Adaptive 的调用更有选择性，但 Deep 触发更多；总成本没有得到降低证明。
- 质量结论是“当前小样本持平”，不是 Adaptive 胜出。
- 下一步若继续，应修复 claim 同义覆盖或改用 judge 先于 Deep；必须防止 judge 绕过来源/版本硬约束。
