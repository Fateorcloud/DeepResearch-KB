# Phase 3 验收

状态：完成。范围是版本/时效/状态/权威选择和结构化冲突提示；不包含 Phase 4 的 evidence sufficiency 或自适应升级。

## 已完成

- `version_governance` 附属表：`effective_at`、`deprecated_at`、`authority`、推断标记；旧数据可回填，原文/Chunk/引用不变。
- `current`、`as_of`、`include_superseded`、`include_deprecated` 选择语义；选择先于 FTS/向量相关性。
- 词法与 PersistentVectorIndex 都使用同一时间选择和 authority 排序；向量缺历史版本时显式要求全版本 rebuild。
- Evidence/context 包含 effective time、status、authority、选择理由、是否推断。
- CLI `govern` 与 `retrieve --as-of/--governed`；研究入口 `run_research` 保存 version policy。
- 同文档多版本共选结构提示；语义 reviewer 要求逐 pair、原文 grounded quotes、完整覆盖；无效输出为 unknown。
- 固定时间选择对照：Phase 2 baseline 2/6，Phase 3 governed 6/6。
- 真实冲突 reviewer：5/5 固定案例通过，覆盖 conflict、compatible、unknown；1350 input + 1708 output tokens。

## 明确限制

- authority 只排序时间合格的证据，不能把权威等级当事实裁决。
- 语义 reviewer 是可调用检查器，不等同完备 conflict recall；unknown 保留不确定性。
- 当前没有 as-of 的实时外部世界回溯；Hybrid 的 external 仍是 live evidence，manifest 会标明这一点。
- 旧数据缺 effective time 时使用 ingested_at，并带 `effective_at_inferred=true`；不能声称历史事实时间已知。
- 评测是小型合成案例，证明工程语义和固定反例，不证明通用研究质量。

## 验证

```sh
GPTR_BLOCK_NETWORK=1 .venv/bin/python -m pytest --forked tests/deepresearch_kb -q
.venv/bin/python -m evals.deepresearch_kb.run_version_governance
.venv/bin/python -m evals.deepresearch_kb.run_version_report_eval
```

Phase 3 交付物：`deepresearch_kb/version_policy.py`、`governance.py`、`conflicts.py`、
CLI/研究入口治理参数、固定评测脚本和本验收文档。所有变更按 CHANGELOG 子步骤记录。
