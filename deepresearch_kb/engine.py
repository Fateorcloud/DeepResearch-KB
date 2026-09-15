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


RESEARCH_DEPTHS = {
    "low": {"reasoning_effort": "low", "breadth": 2, "depth": 1,
            "iterations": 1, "subtopics": 2, "search_results": 3},
    "medium": {"reasoning_effort": "medium", "breadth": 3, "depth": 2,
               "iterations": 3, "subtopics": 3, "search_results": 5},
    "high": {"reasoning_effort": "high", "breadth": 4, "depth": 3,
             "iterations": 5, "subtopics": 5, "search_results": 8},
}
RESEARCH_DEPTH_ALIASES = {"quick": "low", "standard": "medium", "deep": "high"}


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
                  subquestions=None, output_dir=None, limit=5, as_of=None,
                  max_deep_calls=None, progress=None,
                  output_language="Chinese", research_depth="medium"):
        started = time.perf_counter()
        usage = UsageCollector()
        if output_language not in {"Chinese", "English"}:
            raise ValueError("output_language must be Chinese or English")
        research_depth = RESEARCH_DEPTH_ALIASES.get(research_depth, research_depth)
        if research_depth not in RESEARCH_DEPTHS:
            raise ValueError("research_depth must be low, medium, or high")
        depth_config = RESEARCH_DEPTHS[research_depth]
        observed_evidence = {}

        def emit_progress(phase, progress_percent, evidence=()):
            for item in evidence:
                key = getattr(item, "chunk_id", None) or getattr(
                    item, "source_uri", None) or id(item)
                observed_evidence[key] = item
            if progress is not None:
                try:
                    progress({
                        "phase": phase,
                        "progress_percent": progress_percent,
                        "evidence_count": len(observed_evidence),
                    })
                except Exception:
                    # Progress reporting is observational and must not alter Research.
                    pass

        emit_progress("planning", 5)
        task_as_of = self.as_of if as_of is None else as_of
        task_max_deep_calls = self.max_deep_calls if max_deep_calls is None else max_deep_calls
        if type(task_max_deep_calls) is not int or task_max_deep_calls < 0:
            raise ValueError("max_deep_calls must be a non-negative task budget")
        folder = Path(output_dir) if output_dir is not None else None
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=False)

        def tracked_factory(question, factory=self.researcher_factory):
            researcher = factory(question)
            if hasattr(researcher, "cfg"):
                attach_usage(researcher, usage)
                researcher.cfg.language = output_language
                researcher.cfg.reasoning_effort = depth_config["reasoning_effort"]
                researcher.cfg.max_iterations = depth_config["iterations"]
                researcher.cfg.max_subtopics = depth_config["subtopics"]
                researcher.cfg.max_search_results_per_query = depth_config["search_results"]
            if getattr(researcher, "deep_researcher", None) is not None:
                researcher.deep_researcher.breadth = depth_config["breadth"]
                researcher.deep_researcher.depth = depth_config["depth"]
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
        emit_progress("retrieval", 15)
        governed = GovernedKnowledge(self.store, as_of=task_as_of,
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
            question_start = 20 + round(50 * index / max(1, len(plan.questions)))
            question_done = 20 + round(50 * (index + 1) / max(1, len(plan.questions)))
            req = requirements[index]
            quick_evidence, deep_evidence = [], []
            blocked_calls = []
            source_types = set(req.required_source_types)
            internal_allowed = not source_types or bool(
                source_types & {"local_import", "web_upload"})
            external_allowed = not source_types or "external_web" in source_types
            use_internal = internal_allowed and (
                planned.source_policy != "external" or not external_allowed)
            internal = governed.retrieve(
                knowledge_base_ids, planned.question, limit=limit) if use_internal else []
            emit_progress("retrieval", question_start, internal)
            async def quick(question, _q=quick_search):
                nonlocal quick_calls
                if planned.source_policy == "internal" or not external_allowed:
                    blocked_calls.append("quick")
                    return []
                quick_calls += 1
                entries = list(await _q(question))
                quick_evidence.extend(entries)
                emit_progress("quick_research", min(question_done - 1, question_start + 12), entries)
                return entries
            async def deep(question, _d=deep_research):
                nonlocal deep_calls
                if planned.source_policy == "internal" or not external_allowed:
                    blocked_calls.append("deep")
                    return []
                deep_calls += 1
                entries = list(await _d(question))
                deep_evidence.extend(entries)
                emit_progress("deep_research", min(question_done - 1, question_start + 24), entries)
                return entries
            router = AdaptiveResearchRouter(quick_search=quick, deep_research=deep,
                requirements=[req], max_deep_calls=max(0, task_max_deep_calls - deep_calls))
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
            emit_progress("sufficiency", question_done, evidence)
            traces.append({"question": planned.question, "source_policy": planned.source_policy,
                "rationale": planned.rationale, "requirement": asdict(req) if req else None,
                "source_constraint": {
                    "internal_allowed": internal_allowed,
                    "external_allowed": external_allowed,
                },
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
            emit_progress("synthesis", 85, final_evidence)
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
            "max_deep_calls": task_max_deep_calls,
            "output_language": output_language,
            "research_depth": research_depth,
            "reasoning_effort": depth_config["reasoning_effort"],
            "deep_research_breadth": depth_config["breadth"],
            "deep_research_depth": depth_config["depth"],
            "planning_iterations": depth_config["iterations"],
            "max_subtopics": depth_config["subtopics"],
            "max_search_results_per_query": depth_config["search_results"],
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
        emit_progress("finalizing", 95, final_evidence)
        if folder is not None:
            (folder / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            (folder / "plan.json").write_text(json.dumps(asdict(plan), indent=2), encoding="utf-8")
            (folder / "trace.json").write_text(json.dumps(traces, indent=2), encoding="utf-8")
            (folder / "sources.json").write_text(json.dumps([asdict(e) for e in final_evidence], indent=2), encoding="utf-8")
            (folder / "report.md").write_text(report, encoding="utf-8")
        return {"report": report, "plan": plan, "trace": traces,
                "sources": final_evidence, "metrics": result}
