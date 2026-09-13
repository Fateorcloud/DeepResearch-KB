# Phase 2 验收

状态：完成“研究级来源规划”的最小可验证闭环；不包含 Phase 3 版本权威性、Phase 4 充分性/自适应升级。
项目明确基于 GPT Researcher 二次开发，upstream query generation 与检索能力均为复用。

## 已完成

- `ResearchPlan` / `PlannedQuestion` / `PlannedEvidence` 结构化表达问题、策略、理由和证据归属。
- `plan_from_upstream_subqueries()` 接收 upstream sub-query，不重复生成。
- `execute_plan()` 按题执行 `internal`、`external`、`hybrid`，并保持策略与 provenance。
- `render_planned_context()` / `write_planned_report()` 将子问题分组交给 upstream writer。
- 固定策略评测：来源规划 5/5；调用矩阵 5/5；相关项目测试 49 passed。
- 真实 upstream planner 单次验证：3 个生成子查询全部标为 external；一次误标已通过词边界修复并记录。
- 真实计划驱动运行已完成，工件在 Git 忽略的 `data/evals/planned-live-v1/`；未运行 Deep Research。

## 真实运行观察

真实 planner 会输出多个外部子查询；当原问题包含“我们的当前项目”时，子查询可能完全外部化，
规则不会凭父问题强行注入内部证据。这是当前明确限制：来源规划只基于子问题表面词，尚未做任务级约束传播。
因此本阶段不宣称 planner 已能正确识别所有 Internal/Hybrid 需求。

## 可重复演示

```sh
# 无 token：固定 gold 与调用矩阵
.venv/bin/python -m evals.deepresearch_kb.run_source_planning
.venv/bin/python -m evals.deepresearch_kb.run_plan_execution
# 有 token：只生成 upstream sub-query，不写报告
.venv/bin/python -m evals.deepresearch_kb.run_upstream_planner 'For our current project architecture, what is the latest SQLite WAL limitation?' --output data/evals/planner.json
# 有 token：planner -> policy -> evidence -> report，输出新目录
.venv/bin/python -m evals.deepresearch_kb.run_planned_live 'For our current project architecture, what is the latest SQLite WAL limitation?' --database data/smoke/kb.sqlite --kb KB_ID --output data/evals/planned-run
```

## 未解决问题

- 子问题与父任务的 source requirement 传播；
- LLM planner 的策略准确率和人工盲评；
- 真实 citation correctness 与 evidence sufficiency；
- 自动决定是否继续 Quick/Deep Research。

这些问题进入 Phase 3/4 前必须有失败案例，不能用当前规则分类器直接扩展成自适应 Agent。
