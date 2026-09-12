import unittest
from deepresearch_kb.demo import run_demo

class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_demo_is_offline_and_contains_provenance(self):
        output = await run_demo()
        self.assertIn("Internal Source", output)
        self.assertIn("architecture/current.txt", output)
        self.assertIn("Evidence count: 1", output)
