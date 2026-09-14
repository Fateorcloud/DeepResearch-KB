"""Thin unified execution seam for the Phase 1-4 components."""
import json, time, uuid
from dataclasses import asdict
from pathlib import Path

from .adaptive import AdaptiveResearchRouter
from .governance import GovernedKnowledge
from .planning import RuleBasedSourcePlanner
from .research import render_evidence_context
from .sufficiency import EvidenceRequirement
from .metrics import UsageCollector, attach_usage
from .research import UpstreamExternalResearch
from .deep_adapter import UpstreamDeepResearch, default_deep_factory


class ResearchEngine:
    """Orchestrate planning, governed retrieval, adaptive routing and synthesis."""
    def __init__(self, *, store, quick_search=None, deep_research=None, researcher_factory=None,
                 planner=None, as_of=None, include_superseded=False,
                 include_deprecated=False, conflict_checker=None, max_deep_calls=1):
        self.store = store
        self.quick_search = quick_search
        self.deep_research = deep_research
        if researcher_factory is None:
            from .run_research import live_factory
            researcher_factory = live_factory
        self.researcher_factory = researcher_factory
        self.planner = planner or RuleBasedSourcePlanner()
        self.as_of = as_of
        self.include_superseded = include_superseded
        self.include_deprecated = include_deprecated
        self.conflict_checker = conflict_checker
        if type(max_deep_calls) is not int or max_deep_calls < 0:
            raise ValueError("max_deep_calls must be a non-negative task budget")
        self.max_deep_calls = max_deep_calls

    async def run(self, query, *, knowledge_base_ids, requirements=None,
                  subquestions=None, output_dir=None, limit=5):
        started = time.perf_counter()
        usage = UsageCollector()
        folder = Path(output_dir) if output_dir is not None else None
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=False)

        def tracked_factory(question, factory=self.researcher_factory):
            researcher = factory(question)
            if hasattr(researcher, "cfg"):
                attach_usage(researcher, usage)
            return researcher

        quick_search = self.quick_search or UpstreamExternalResearch(tracked_factory).search
        deep_research = self.deep_research or UpstreamDeepResearch(
            lambda question: tracked_factory(question, default_deep_factory)).search
        planning_source = "explicit_subquestion_replay"
        if subquestions is None:
            planning_source = "upstream_plan_research"
            researcher = tracked_factory(query)
            subquestions = await researcher.research_conductor.plan_research(query)
        plan = self.planner.plan(query, subquestions)
        governed = GovernedKnowledge(self.store, as_of=self.as_of,
            include_superseded=self.include_superseded,
            include_deprecated=self.include_deprecated)
        requirement_origin = "caller_explicit_positional_mapping"
        if isinstance(requirements, EvidenceRequirement):
            requirement_origin = "caller_task_requirement_broadcast_unchanged"
            requirements = (requirements,) * len(plan.questions)
        elif isinstance(requirements, dict):
            requirement_origin = "caller_explicit_question_mapping"
            if set(requirements) != {p.question for p in plan.questions}:
                raise ValueError("Requirement question keys must exactly match the generated plan")
            requirements = tuple(requirements[p.question] for p in plan.questions)
        else:
            requirements = tuple(requirements or ())
        if len(requirements) != len(plan.questions) or not all(
                isinstance(req, EvidenceRequirement) for req in requirements):
            raise ValueError("An explicit EvidenceRequirement is required for every planned question")
        traces, final_evidence = [], []
        quick_calls = deep_calls = 0
        for index, planned in enumerate(plan.questions):
            req = requirements[index]
            quick_evidence, deep_evidence = [], []
            blocked_calls = []
            internal = [] if planned.source_policy == "external" else governed.retrieve(
                knowledge_base_ids, planned.question, limit=limit)
            async def quick(question, _q=quick_search):
                nonlocal quick_calls
                if planned.source_policy == "internal":
                    blocked_calls.append("quick")
                    return []
                quick_calls += 1
                entries = list(await _q(question))
                quick_evidence.extend(entries)
                return entries
            async def deep(question, _d=deep_research):
                nonlocal deep_calls
                if planned.source_policy == "internal":
                    blocked_calls.append("deep")
                    return []
                deep_calls += 1
                entries = list(await _d(question))
                deep_evidence.extend(entries)
                return entries
            router = AdaptiveResearchRouter(quick_search=quick, deep_research=deep,
                requirements=[req], max_deep_calls=max(0, self.max_deep_calls - deep_calls))
            conflict_reviews = []
            checker = self.conflict_checker
            class TracedChecker:
                async def check(self, evidence):
                    review = (await checker.check(evidence) if checker is not None else
                              {"status": "not_applicable" if len(evidence) < 2 else "not_evaluated", "pairs": []})
                    conflict_reviews.append({"evidence_ids": [e.chunk_id for e in evidence], "result": review})
                    return review
            route, evidence, decisions = await router.run(planned.question, internal=internal,
                                                          conflict_checker=TracedChecker())
            final_evidence.extend(evidence)
            traces.append({"question": planned.question, "source_policy": planned.source_policy,
                "rationale": planned.rationale, "requirement": asdict(req) if req else None,
                "internal_evidence": [asdict(e) for e in internal],
                "quick_evidence": [asdict(e) for e in quick_evidence],
                "deep_evidence": [asdict(e) for e in deep_evidence],
                "policy_blocked_calls": blocked_calls,
                "conflict_reviews": conflict_reviews,
                "requirement_propagation": {"task_requirement_index": index,
                    "requirement_id": req.id, "method": requirement_origin},
                "decisions": [asdict(d) for d in decisions], "final_route": route,
                "final_evidence": [asdict(e) for e in evidence]})
        report = "No source evidence was retrieved; report generation skipped."
        synthesis_error = None
        unresolved = [{"question": t["question"], "decision": t["decisions"][-1],
                       "conflict_reviews": t["conflict_reviews"]}
                      for t in traces if t["decisions"][-1]["terminal_status"] in
                      ("unknown", "conflict", "insufficient")]
        context = render_evidence_context(final_evidence)
        if unresolved:
            context += ("\n\nResearch limitations: these questions remain unresolved. "
                        "Do not treat tool completion as evidence sufficiency; preserve uncertainty.\n"
                        + json.dumps(unresolved, ensure_ascii=False))
        if final_evidence:
            try:
                researcher = tracked_factory(query)
                report = await researcher.write_report(ext_context=context)
                if not isinstance(report, str) or not report.strip():
                    raise ValueError("Empty report")
            except Exception as exc:
                synthesis_error = exc
                report = "Report synthesis failed; see run.json. Collected evidence is preserved."
        result = {"run_id": uuid.uuid4().hex, "query": query, "status": "completed",
            "planning_source": planning_source,
            "requirement_origin": requirement_origin,
            "knowledge_base_ids": list(knowledge_base_ids),
            "version_policy": {"as_of": governed.as_of.isoformat(),
                "include_superseded": self.include_superseded,
                "include_deprecated": self.include_deprecated},
            "final_route_summary": [t["final_route"] for t in traces],
            "quick_calls": quick_calls, "deep_calls": deep_calls,
            "max_deep_calls": self.max_deep_calls,
            "latency_seconds": time.perf_counter() - started}
        result.update(usage.summary())
        result["evidence_status"] = [
            t["decisions"][-1]["terminal_status"] or
            ("sufficient" if t["decisions"][-1]["route"] == "stop" else "insufficient")
            for t in traces]
        result["status"] = ("failed" if synthesis_error else
                            "completed" if all(s == "sufficient" for s in result["evidence_status"])
                            else "incomplete")
        result["error_type"] = type(synthesis_error).__name__ if synthesis_error else None
        result["failure_stage"] = "synthesis" if synthesis_error else None
        result["tool_execution"] = {
            "quick": "injected" if self.quick_search else "upstream_live",
            "deep": "injected" if self.deep_research else "upstream_live"}
        result["usage_scope"] = "Tracked researcher factories only; injected tools/checkers may have unobserved usage"
        result["actual_cost_usd"] = None
        if folder is not None:
            (folder / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            (folder / "plan.json").write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")
            (folder / "trace.json").write_text(json.dumps(traces, indent=2), encoding="utf-8")
            (folder / "sources.json").write_text(json.dumps([asdict(e) for e in final_evidence], indent=2), encoding="utf-8")
            (folder / "report.md").write_text(report, encoding="utf-8")
        return {"report": report, "plan": plan, "trace": traces,
                "sources": final_evidence, "metrics": result}
