# Phase 4.5 Real-Project Evaluation

## Scope and protocol

This evaluation freezes 12 small real-project-style cases (6 development, 6 holdout) in `evals/deepresearch_kb/phase45_cases.json`. Dataset SHA-256: `2d1a40e15441ed1f6623a41d9600612aa19dd9affa76e7d7b730c2b8c87c356c`.

Each case is executed as a pair: Fixed Hybrid (governed internal evidence plus one frozen Quick pass) and Adaptive (the same governed evidence, then Quick and conditional Deep). Search is frozen; no MCP, UI, REST, multi-agent, GraphRAG, migration, or live search is used. Fixture calls and provider-reported model usage are recorded separately. Reports use one alternating real-model synthesis pass with the same prompt and 1,800-token budget.

## Routing result

The offline runner produced 24 complete routing artifacts. Adaptive matched the frozen expected route in 12/12 cases, with 9 Quick calls and 5 Deep calls across the suite. Fixed Hybrid made 12 Quick and 0 Deep calls. Adaptive had 2 unresolved cases; Fixed Hybrid had 4. Unresolved results are retained as failures or boundary behavior, not changed in the gold data.

## Report result

All 24 report pairs contain `report.md`, `sources.json`, `context.txt`, and `metrics.json` under `data/evals/phase45-reports-v1`. The strict model judge is fallible and is evidence for review, not absolute truth. It returned:

| arm | correct | unanswerable | incorrect |
| --- | ---: | ---: | ---: |
| Fixed Hybrid | 7 | 2 | 3 |
| Adaptive | 10 | 2 | 0 |

The judge itself completed 24/24 calls (0 failures; 19,404 input and 35,839 output tokens). Provider usage is reported usage only; no bill is inferred.

## Failure analysis

Fixed Hybrid failed on stale metadata and a Quick-insufficient deployment question by stopping before Deep, and on the long multi-requirement case. The conflicting-writer case was correctly treated as unresolved by both arms. The unknown quantum-policy case was correctly reported as unanswerable by both. Adaptive's remaining unresolved cases are intentional conflict/unknown boundaries, not silently resolved claims.

## Gates and limits

- Gate A (reproducible artifacts): **pass**. Frozen hash, paired protocol, and 24/24 complete artifacts are present.
- Gate B (routing): **pass for this frozen suite**. Adaptive is 12/12 against the explicit route gold; this is not a general routing-accuracy claim.
- Gate C (answer quality): **inconclusive but favorable**. The fallible judge found fewer incorrect reports for Adaptive (0 vs 3), while unanswerable handling was equal (2 vs 2). This small frozen suite does not establish production quality or cost savings.

Full artifacts: `data/evals/phase45-routing-v1`, `data/evals/phase45-reports-v1`, and `data/evals/phase45-reports-v1/judge.json`.
