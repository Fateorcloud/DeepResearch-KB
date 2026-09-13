"""One real planner-driven run for Phase 2; no deep research."""
import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from gpt_researcher import GPTResearcher
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.planned_run import run_planned
from deepresearch_kb.research import UpstreamExternalResearch


async def main(query, database, kb, output):
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("TAVILY_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY and TAVILY_API_KEY are required locally")
    def factory(question):
        return GPTResearcher(query=question, report_source="web", verbose=False,
                             mcp_strategy="disabled", max_subtopics=2)
    planner = factory(query)
    planner.external_adapter = UpstreamExternalResearch(factory)
    # run_planned uses this adapter for each external planned question, while
    # final synthesis remains on the planner instance created above.
    return await run_planned(query, store=KnowledgeStore(database), researcher=planner,
                             knowledge_base_ids=[kb], output_dir=Path(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--database", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.query, args.database, args.kb, args.output))
