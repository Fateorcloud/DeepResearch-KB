# Phase 4.5a — Unified Research Execution

状态：开发中，尚未验收。不是正式 Phase 4.5 效果评测。

## 源码核对

原 Phase 2 入口是 `planned_run.run_planned`，不是 `run_planned.py`。
它连接 upstream `plan_research`、source policy、固定检索与 synthesis，未进入 Adaptive。
原 `run_adaptive_live.py` 虽然 docstring 写 governed，实际调用普通
`KnowledgeStore.retrieve`，且只保存 route，不生成 report。
`run_research.py` 支持可选治理与 synthesis，但没有自适应路由。

## 当前统一入口

`deepresearch_kb.engine.ResearchEngine.run` 调用 upstream planner 接口，复用
`RuleBasedSourcePlanner`、`GovernedKnowledge`、`AdaptiveResearchRouter`、
`UpstreamExternalResearch`、`UpstreamDeepResearch` 和 upstream `write_report`。
检索、版本选择、claim 判断与报告生成算法没有在 Engine 重写。

requirements 由调用方显式提供。支持按规划顺序提供列表，或按完整子问题文本提供映射；
映射键必须与实际计划一致。trace 记录 requirement ID 和绑定方式。
这不是自动 requirement generation；提供正确需求仍是调用方责任。
显式 `subquestions` 是回放路径，正常调用使用 upstream planner。

source policy 与 route 分开：external 不读 KB；internal 阻止外部工具调用；
hybrid 可以在内部充分时 STOP。被阻止的工具请求单独记录，不计实际调用。
internal retrieval 始终通过 GovernedKnowledge，时间策略绑定到一次运行。

路由可在内部、Quick、Deep 后复查冲突。未配置 checker 时，多份证据标记
not_evaluated/unknown；不能当成充分。未解决状态传递到 synthesis。
sources.json 保存传给 synthesis 的实际 Evidence；trace 分开保存各阶段证据。

默认 planner/synthesis/Quick/Deep 工厂接入 UsageCollector。
注入工具和 checker 的额外 usage 可能不被观测，run.json 明确记录这个范围。
实际费用为 null，不从调用次数推算费用。测试回调 token 不是实际 provider 消耗。

## 尚未完成的验收项

- planning、requirement validation、retrieval、工具异常的完整失败工件。
- 完整验证真实 adapter 接线、历史版本和跨子问题状态。
- 旧 live runner 委托统一入口，避免继续保留半套执行流程。
- 最终全量项目回归、README/CHANGELOG 状态同步和验收结论。

当前测试使用真实 SQLite/治理，但 planner、外部结果和 synthesis 有测试替身。
没有运行真实 provider 的三案例对照，也没有建立 12–20 条正式数据集。

## 独立集成案例

`tests/test_unified_engine.py::test_independent_query_to_report_case` 包含三个独立运行：
hybrid/internal sufficient → STOP（Quick=0、Deep=0）；Quick sufficient（1、0）；
Quick insufficient → Deep sufficient（1、1）。每例使用真实 SQLite ingest 和显式
as-of 版本治理，独立校验 plan、trace、sources、report、run；报告测试替身收到的
证据上下文与 sources.json 一致。三个案例是受控编排证明，不是报告质量评价。
