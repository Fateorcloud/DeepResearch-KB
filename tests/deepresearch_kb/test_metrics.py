import unittest
from types import SimpleNamespace
from uuid import uuid4

from deepresearch_kb.metrics import UsageCollector


class MetricsTests(unittest.TestCase):
    def test_provider_usage_is_counted_once_and_not_estimated(self):
        collector = UsageCollector()
        response = SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace(
            usage_metadata={"input_tokens": 12, "output_tokens": 8}))]], llm_output={})
        run_id = uuid4()
        collector.on_chat_model_start({}, [])
        collector.on_llm_end(response, run_id=run_id)
        collector.on_llm_end(response, run_id=run_id)
        summary = collector.summary()
        self.assertEqual(summary["llm_calls_completed"], 1)
        self.assertEqual(summary["llm_tokens"], {"input_tokens": 12, "output_tokens": 8})

    def test_missing_usage_remains_unknown(self):
        collector = UsageCollector()
        collector.on_llm_end(SimpleNamespace(generations=[], llm_output={}), run_id=uuid4())
        self.assertIsNone(collector.summary()["llm_tokens"])

    def test_openai_compatible_fallback(self):
        collector = UsageCollector()
        collector.on_llm_end(SimpleNamespace(generations=[], llm_output={
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 30}}), run_id=uuid4())
        self.assertEqual(collector.summary()["llm_tokens"]["input_tokens"], 100)
