# Phase 4 计划与验收

目标：证明 Evidence Sufficiency 驱动 `KB → STOP`、`KB → Quick`、`Quick → Deep`，并记录调用、token、耗时和失败原因。

顺序：固定路由 gold → 注入 Quick/Deep 执行器 → 接入 Phase 3 conflict→Deep → 接入 upstream quick/deep → 固定对照 → 验收。
不重写 upstream Deep Research，不让 LLM 自由循环，不把证据条数直接当作事实充分性。

当前入口：`evals/deepresearch_kb/run_adaptive_live.py`。真实运行只记录 route trace，
Deep 分支调用 upstream `conduct_research()`，不复制其实现。
