"""Run an upstream-generated plan through the project source-policy seam."""
import json
from dataclasses import asdict
from pathlib import Path
from .planning import plan_from_upstream_subqueries
from .research import ResearchOrchestrator, render_planned_context


async def run_planned(query, *, store, researcher, knowledge_base_ids, output_dir):
    """Use the caller's upstream researcher for planning and synthesis.

    The researcher must expose ``research_conductor.plan_research`` and
    ``write_report``. No duplicate sub-query generation is performed here.
    """
    subqueries = await researcher.research_conductor.plan_research(query)
    plan = plan_from_upstream_subqueries(query, subqueries)
    # External adapter is intentionally the same researcher factory seam; the
    # caller decides how to construct per-question upstream instances.
    external = researcher.external_adapter
    orchestrator = ResearchOrchestrator(store, external)
    planned = await orchestrator.execute_plan(plan, knowledge_base_ids=knowledge_base_ids)
    report = await researcher.write_report(ext_context=render_planned_context(planned)) if planned else "No source evidence was retrieved; report generation skipped."
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    (output / "plan.json").write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=2, default=str))
    (output / "evidence.json").write_text(json.dumps([asdict(item) for item in planned], ensure_ascii=False, indent=2))
    (output / "report.md").write_text(report, encoding="utf-8")
    return report, planned
