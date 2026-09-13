import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from deepresearch_kb.models import Evidence
from deepresearch_kb.planning import PlannedEvidence, RuleBasedSourcePlanner
from deepresearch_kb.research import ResearchOrchestrator, render_planned_context


class PlanExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.internal = Evidence("i", "internal", "local_import", "file:///a", "a", "d", 1, 1.0)
        self.store = SimpleNamespace(retrieve=lambda ids, query, limit: [self.internal])

    async def test_each_subquestion_uses_its_declared_policy(self):
        internal = Evidence("i", "internal", "local_import", "file:///a", "a", "d", 1, 1.0)
        external = Evidence("e", "external", "external_web", "https://x", "https://x", "", 1, 1.0)
        store = SimpleNamespace(retrieve=lambda ids, query, limit: [internal])
        adapter = SimpleNamespace(search=AsyncMock(return_value=[external]))
        planner = RuleBasedSourcePlanner()
        plan = planner.plan("overall", ["What is our architecture?", "What is the latest SQLite behavior?"])
        result = await ResearchOrchestrator(store, adapter).execute_plan(plan, knowledge_base_ids=["kb"])
        self.assertEqual([(x.source_policy, x.evidence.source_type) for x in result],
                         [("internal", "local_import"), ("external", "external_web")])
        self.assertTrue(all(isinstance(x, PlannedEvidence) for x in result))
        self.assertEqual(adapter.search.await_count, 1)

    async def test_plan_rejects_internal_without_kb(self):
        plan = RuleBasedSourcePlanner().plan("x", ["What is our architecture?"])
        with self.assertRaises(ValueError):
            await ResearchOrchestrator(SimpleNamespace(retrieve=lambda *args: [])).execute_plan(plan)

    async def test_planned_report_preserves_question_and_policy(self):
        reporter = SimpleNamespace(write_report=AsyncMock(return_value="ok"))
        plan = RuleBasedSourcePlanner().plan("overall", ["What is our architecture?"])
        report, planned = await ResearchOrchestrator(self.store).write_planned_report(
            plan, knowledge_base_ids=["kb"], researcher_factory=lambda query: reporter)
        self.assertEqual(report, "ok")
        self.assertEqual(planned[0].question, "What is our architecture?")
        context = reporter.write_report.await_args.kwargs["ext_context"]
        self.assertIn("Source Policy: internal", context)
        self.assertIn("Question: What is our architecture?", context)

    def test_empty_planned_context(self):
        self.assertEqual(render_planned_context([]), "")
