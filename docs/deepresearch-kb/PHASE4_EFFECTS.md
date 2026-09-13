# Phase 4 效果验证

使用 `evals/deepresearch_kb/effect_dataset.json` 的 6 个合成案例验证路由 gold：内部充分、外部缺失、混合需求、Quick 不足、冲突和无证据。`run_effect_eval.py` 结果为 **6/6**：internal sufficient→STOP，external/hybrid→Quick，Quick 不足或 conflict/no evidence→Deep。

Requirement-based claim coverage 解决了“证据数量足够但关键 claim 缺失”的已知问题；真实 DeepSeek judge 的 sufficient/insufficient 固定案例为 2/2。真实 `adaptive-live-v1/v2` 已验证 STOP 与 Quick 路径；Deep 分支由 fake 执行器覆盖，未重复真实 Deep Research。

结论仅证明可解释路由机制和调用选择，不证明答案质量或成本普遍优于固定 Hybrid。确定性 claim 依赖 gold 短语，同义改写交给可选 judge，judge 失败为 unknown。下一步需用真实项目问题扩大数据集，再评估质量不下降前提下的成本变化。
