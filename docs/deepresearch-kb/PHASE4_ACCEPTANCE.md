# Phase 4 验收

状态：完成最小自适应研究闭环。项目明确基于 GPT Researcher 二次开发；upstream `quick_search()` 和
`conduct_research()` 是被调用的 Adapter，不是本项目重实现。

## 路由语义

- Internal evidence 达到阈值：`STOP`，不调用 Quick/Deep。
- Internal evidence 不足：调用 `Quick`；证据达到阈值后停止。
- Quick 仍不足：调用 `Deep`，沿用 upstream Deep Research。
- 已检测 conflict：直接进入 `Deep`；unknown 不自动当作无冲突。

## 验收证据

- 固定四路由案例：4/4。
- 63 项 Phase 3 前回归加 Phase 4 测试，当前全量相关测试通过。
- 真实 DeepSeek/Tavily Adapter：
  - `adaptive-live-v1`：SQLite 内部证据足够，STOP，Quick=0、Deep=0，约 0.001 秒，无 token。
  - `adaptive-live-v2`：内部不足，Quick=1、Deep=0，最终 Quick 路由，约 3.04 秒；产生外部检索/模型 token。
- Deep 分支由 fake 执行器覆盖；真实 Deep Research 未为省成本重复运行。

## 限制

当前阈值是“证据条数”，不是事实覆盖率；它证明路由状态机成立，不证明每个问题的证据充分。
Quick 返回任意结果即可停止，仍可能包含无关证据。没有自动冲突裁决、跨子问题充分性聚合或质量优先的停止模型。
下一阶段应以这些失败案例为依据改进，而不是扩大 Agent 数量。

## 演示

```sh
.venv/bin/python -m evals.deepresearch_kb.run_adaptive_eval
.venv/bin/python -m evals.deepresearch_kb.run_adaptive_live 'What is SQLite?' --database data/smoke/kb.sqlite --kb KB_ID --output data/evals/adaptive-stop
.venv/bin/python -m evals.deepresearch_kb.run_adaptive_live 'What is the latest quantum computing policy?' --database data/smoke/kb.sqlite --kb KB_ID --output data/evals/adaptive-quick
```

每次运行保存 `route.json`，包括决策原因、证据数、Quick/Deep 调用数和耗时。
