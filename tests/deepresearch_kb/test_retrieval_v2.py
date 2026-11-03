import json
import tempfile
import unittest
from pathlib import Path

from evals.deepresearch_kb.retrieval_v2.fetch_corpus import DEFAULT_CORPUS
from evals.deepresearch_kb.retrieval_v2.run import (
    TYPES, grade_case, load_cases, normalize, split_of, summarize, validate_labels)


def _row(type_, doc_rank=None, span_rank=None, returned=10, stale=0, split="dev"):
    return {"type": type_, "doc_rank": doc_rank, "span_rank": span_rank, "returned": returned,
            "stale": stale, "split": split, "latency_ms": 1.0}


class RetrievalV2Tests(unittest.TestCase):
    def test_normalize_ignores_markdown_emphasis_and_spacing(self):
        self.assertEqual(normalize("安装 `PyJWT`，**校验** JWT"), "安装PyJWT，校验JWT")

    def test_span_hit_requires_gold_page_and_span(self):
        case = {"type": "fact", "gold": [{"path": "a.md", "span": "答案 片段"}]}
        evidence = [("b.md", 1, "答案片段"), ("a.md", 1, "无关"), ("a.md", 1, "前文`答案`片段后文")]
        graded = grade_case(case, evidence, {"a.md": 1, "b.md": 1})
        self.assertEqual((graded["doc_rank"], graded["span_rank"]), (2, 3))

    def test_superseded_versions_count_as_stale(self):
        case = {"type": "no_answer", "gold": []}
        graded = grade_case(case, [("a.md", 1, "x"), ("a.md", 2, "y")], {"a.md": 2})
        self.assertEqual((graded["returned"], graded["stale"]), (2, 1))

    def test_summary_recall_and_mrr(self):
        rows = [_row("fact", 1, 1), _row("fact", 2, 4), _row("fact"), _row("no_answer", returned=0)]
        summary = summarize(rows)
        self.assertEqual(summary["span_recall@1"], round(1 / 3, 4))
        self.assertEqual(summary["span_recall@5"], round(2 / 3, 4))
        self.assertEqual(summary["span_mrr@10"], round((1 + 0.25) / 3, 4))
        self.assertEqual(summary["no_answer_nonempty_rate"], 0)

    def test_split_is_deterministic(self):
        self.assertEqual(split_of("tutorial/cors.md"), split_of("tutorial/cors.md"))
        self.assertIn(split_of("x.md"), {"dev", "test"})

    def test_validate_labels_reports_missing_spans(self):
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "v2" / "a.md"
            page.parent.mkdir(parents=True)
            page.write_text("使用 `Depends` 声明依赖", encoding="utf-8")
            cases = [{"id": "ok", "gold": [{"path": "a.md", "span": "使用Depends"}]},
                     {"id": "bad", "gold": [{"path": "a.md", "span": "不存在"}]},
                     {"id": "gone", "gold": [{"path": "b.md", "span": "x"}]}]
            problems = validate_labels(cases, directory)
        self.assertEqual([p.split(":")[0] for p in problems], ["bad", "gone"])

    def test_committed_dataset_is_well_formed(self):
        data, digest = load_cases()
        types = {case["type"] for case in data["cases"]}
        self.assertEqual(types, set(TYPES))
        self.assertGreaterEqual(len(data["cases"]), 80)
        self.assertEqual(len(digest), 64)

    @unittest.skipUnless(Path(DEFAULT_CORPUS, "v2").is_dir(), "corpus not fetched")
    def test_gold_spans_exist_in_fetched_corpus(self):
        data, _ = load_cases()
        self.assertEqual(validate_labels(data["cases"], DEFAULT_CORPUS), [])


class AllVersionsControlTests(unittest.TestCase):
    def test_control_index_keeps_superseded_chunks_that_product_set_excludes(self):
        import asyncio
        import tempfile
        from pathlib import Path

        from deepresearch_kb.knowledge import KnowledgeStore
        from evals.deepresearch_kb.retrieval_v2.retrievers import Workbench

        async def build(root):
            pages = {}

            async def loader(file):
                return [{"raw_content": pages[file.name], "url": file.name}]

            store = KnowledgeStore(Path(root) / "kb.sqlite", loader=loader)
            kb = store.create_knowledge_base("control").id
            for text in ("依赖注入旧版说明。", "依赖注入新版说明。"):
                page = Path(root) / "page.md"
                pages[page.name] = text
                page.write_text(text, encoding="utf-8")
                await store.ingest(kb, page, logical_path="page.md")
            return store, kb

        with tempfile.TemporaryDirectory() as root:
            store, kb = asyncio.run(build(root))
            bench = Workbench(store, kb, Path(root) / "cache")
            self.assertEqual({hit.version for hit in bench.chunks}, {2})
            self.assertEqual({hit.version for hit in bench.all_version_chunks}, {1, 2})
            found = bench.bigram_all_versions().search("依赖注入", 10)
            self.assertEqual({hit.version for hit in found}, {1, 2})

