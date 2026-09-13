import unittest
from evals.deepresearch_kb.run_version_report_eval import evaluate
class VersionReportEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_cases(self):
        result=await evaluate(); self.assertEqual(result["passed"],result["total"])
        self.assertTrue(all(row["selection"] for row in result["rows"] if row["actual"] is not None))
