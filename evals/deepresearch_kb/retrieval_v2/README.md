# Retrieval benchmark v2: versioned Chinese technical docs

Retrieval-only benchmark for `KnowledgeStore` (no LLM, web search or report
scoring). It replaces nothing: the 6-case regression set in `../cases.json`
is unchanged.

## Data

- Corpus: FastAPI Chinese docs (MIT), pinned at 0.100.0 (`v1`) and master
  45cb225 (`v2`); 127 documents, 59 of which have a superseded v1. Fetched,
  not committed: `python -m evals.deepresearch_kb.retrieval_v2.fetch_corpus`
  exports into `data/` and checks every file against `corpus_manifest.json`.
- `cases.json`: 85 questions — fact 42, paraphrase 27 (avoids the page's
  wording), version 8 (answer changed between v1 and v2), no_answer 8.
- Labels are page + answer span, not chunk ids, so chunking changes do not
  require relabelling. The runner refuses to start if any span is missing
  from its v2 page.
- Split: dev/test by gold-page hash (44/41 cases), so one page never appears
  in both.

## Metrics

`span_recall@k` (a top-k chunk is from the gold page and contains the span),
`doc_recall@k`, `span_mrr@10`, `empty_rate` (answerable query returns
nothing), `stale_rate` (returned chunk from a superseded version),
`no_answer_nonempty_rate`, latency. All candidates read the product's active
chunks, so version filtering is identical across them.

## Running

```
python -m evals.deepresearch_kb.retrieval_v2.run --split dev --retriever all
```

`vector`, `hybrid`, `rerank` and `*_c400` need `fastembed`; `jieba` needs
`jieba`. Both are optional and not project dependencies. Models:
`BAAI/bge-small-zh-v1.5` (embedding), `BAAI/bge-reranker-base` (rerank),
CPU only.

## Dev results (40 answerable cases, 2026-10-31)

| retriever | R@1 | R@5 | R@10 | MRR@10 | empty | paraphrase R@5 | p50 ms |
|---|---|---|---|---|---|---|---|
| fts5 (current) | 0.225 | 0.325 | 0.350 | 0.263 | 0.500 | 0.000 | 0.4 |
| trigram | 0.475 | 0.725 | 0.775 | 0.583 | 0.025 | 0.357 | 0.3 |
| **bigram** | 0.625 | **0.800** | 0.850 | 0.700 | 0.000 | 0.500 | 0.3 |
| jieba | 0.625 | 0.775 | 0.825 | 0.704 | 0.000 | 0.357 | 0.4 |
| vector | 0.200 | 0.525 | 0.600 | 0.351 | 0.000 | 0.429 | 3.1 |
| hybrid (bigram+vector RRF) | 0.425 | 0.675 | 0.750 | 0.538 | 0.000 | 0.571 | 3.7 |
| rerank (hybrid top 20) | 0.700 | 0.825 | 0.875 | 0.763 | 0.000 | 0.571 | 4157 |
| bigram_c400 | 0.500 | 0.725 | 0.825 | 0.592 | 0.000 | 0.429 | 0.4 |
| vector_c400 | 0.300 | 0.500 | 0.650 | 0.404 | 0.000 | 0.357 | 20.2 |
| hybrid_c400 | 0.400 | 0.725 | 0.775 | 0.511 | 0.000 | 0.500 | 13.6 |

Findings:

- Root cause of the baseline: SQLite's default `unicode61` tokenizer keeps a
  whole run of Chinese between punctuation as one token, so a query for
  "依赖注入" cannot match "依赖注入指的是……". Half of answerable queries return
  nothing, and paraphrased questions are almost never found.
- Character bigrams fix this without dependencies; trigram cannot match
  two-character words.
- The small embedding model is weaker than bigram on this mixed Chinese/code
  corpus and pulls RRF down. 1000-character chunks do hit the 512-token
  limit, but 400-character windows did not improve vector recall, so
  truncation is not the main cause.
- Rerank gains one case over bigram at ~4 s per query on CPU.
- No candidate abstains: every no-answer query returns results. Abstention
  needs a score threshold, which is not evaluated here.
- 40 cases: one case is 2.5 points, so bigram vs jieba is a tie.

## Selection (fixed before the test run)

Chosen on dev only: **bigram** — best R@5, sub-millisecond, no dependency;
tied with jieba on quality and needs no dictionary. Rerank is not chosen
because its one-case gain costs four orders of magnitude in latency. The
test split is run once for all candidates after this commit; no parameter is
changed afterwards.