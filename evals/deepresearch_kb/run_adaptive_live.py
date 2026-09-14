"""Live unified execution with explicitly supplied evidence requirements."""
import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
from deepresearch_kb.engine import ResearchEngine
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.sufficiency import EvidenceRequirement


async def main(query, database, kb, output, max_deep_calls=1, requirements_path=None):
    if requirements_path is None:
        raise ValueError("Explicit --requirements is required")
    raw = json.loads(Path(requirements_path).read_text(encoding="utf-8"))

    def parse(item):
        return EvidenceRequirement(item["id"], tuple(item["required_claims"]),
            tuple(item.get("required_source_types", [])),
            item.get("minimum_distinct_sources", 1), item.get("require_current_version", False))

    requirements = parse(raw) if "required_claims" in raw else {q: parse(r) for q, r in raw.items()}
    load_dotenv()
    engine = ResearchEngine(store=KnowledgeStore(database), max_deep_calls=max_deep_calls)
    result = await engine.run(query, knowledge_base_ids=[kb], requirements=requirements, output_dir=output)
    print(output)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--database", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--max-deep-calls", type=int, default=1)
    args = parser.parse_args()
    result = asyncio.run(main(args.query, args.database, args.kb, args.output,
                              args.max_deep_calls, args.requirements))
    raise SystemExit(0 if result["metrics"]["status"] == "completed" else 1)
