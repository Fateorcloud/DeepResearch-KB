import unittest
from evals.deepresearch_kb.run_retrieval import evaluate, grade


class RetrievalEvalTests(unittest.IsolatedAsyncioTestCase):
    def test_grader_counts_extra_sources_as_failure(self):
        score = grade([["a", 1]], [["a", 1], ["b", 1]])
        self.assertFalse(score["passed"])
        self.assertEqual(score["recall"], 1)
        self.assertEqual(score["precision"], 0.5)

    async def test_dataset_keeps_failures_visible(self):
        result = await evaluate()
        self.assertEqual(result["total"], 6)
        self.assertEqual(result["passed"], sum(row["passed"] for row in result["results"]))
        self.assertEqual(len(result["dataset_sha256"]), 64)
        self.assertEqual(result["passed"], 6)
