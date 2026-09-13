"""Run upstream sub-query planning once and record project policy annotations."""
import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from gpt_researcher import GPTResearcher
from deepresearch_kb.planning import plan_from_upstream_subqueries


async def run(query: str, output: str):
    load_dotenv()
    required = ["OPENAI_API_KEY", "TAVILY_API_KEY"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError("missing local credentials: " + ", ".join(missing))
    started = time.perf_counter()
    researcher = GPTResearcher(query=query, report_source="web", verbose=False,
                               mcp_strategy="disabled")
    outline = await researcher.research_conductor.plan_research(query)
    plan = plan_from_upstream_subqueries(query, outline)
    result = {"query": query, "subqueries": list(outline),
              "planned": [{"question": item.question, "source_policy": item.source_policy,
                           "rationale": item.rationale} for item in plan.questions],
              "latency_seconds": time.perf_counter() - started,
              "upstream_cost_estimate_usd": researcher.get_costs(),
              "scope": "one upstream planner call; no evidence collection/report",
              "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.query, args.output))
