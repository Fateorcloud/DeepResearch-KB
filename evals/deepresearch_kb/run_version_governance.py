"""Fixed temporal retrieval comparison; no LLM or claimed answer-quality score."""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.governance import VersionGovernance


def at(year):
    return datetime(year, 1, 1, tzinfo=timezone.utc)


async def evaluate():
    rows = []
    # Import order intentionally differs from factual effective order.
    fixtures = [("SQLite current", 2025, None),
                ("SQLite historical", 2024, None),
                ("SQLite future", 2028, 2029)]
    cases = [("current-late-import", 2026, False, [1]),
             ("historical", 2024, False, [2]),
             ("before-any-version", 2023, False, []),
             ("future-becomes-current", 2028, False, [3]),
             ("deprecated-no-fallback", 2029, False, []),
             ("explicit-deprecated", 2029, True, [3])]
    with tempfile.TemporaryDirectory(prefix="kb-version-eval-") as directory:
        root = Path(directory)
        async def loader(path):
            return [{"raw_content": path.read_text(), "url": path.name}]
        store = KnowledgeStore(root / "db.sqlite", loader=loader)
        kb = store.create_knowledge_base("fixed temporal corpus")
        governance = VersionGovernance(store)
        source = root / "input.txt"
        for text, year, deprecated in fixtures:
            source.write_text(text, encoding="utf-8")
            version = await store.ingest(kb.id, source, logical_path="architecture.txt",
                                         source_uri="fixture://architecture")
            governance.set_metadata(version.document_id, version.version, effective_at=at(year),
                deprecated_at=at(deprecated) if deprecated else None)
        # Repeat after reopen to verify persisted rules, not only in-memory data.
        store = KnowledgeStore(store.database, loader=loader)
        governance = VersionGovernance(store)
        for name, year, include_deprecated, expected in cases:
            baseline = [e.version for e in store.retrieve([kb.id], "SQLite")]
            governed = [e.version for e in governance.retrieve([kb.id], "SQLite",
                        as_of=at(year), include_deprecated=include_deprecated)]
            rows.append({"case": name, "as_of": at(year).isoformat(), "expected": expected,
                         "phase2_last_import": baseline, "phase3": governed,
                         "baseline_passed": baseline == expected, "governed_passed": governed == expected})
    return {"scope": "Fixed temporal version-selection regression, not report correctness",
            "fixtures_in_import_order": fixtures, "cases": rows,
            "baseline_passed": sum(r["baseline_passed"] for r in rows),
            "governed_passed": sum(r["governed_passed"] for r in rows), "total": len(rows)}


if __name__ == "__main__":
    result = asyncio.run(evaluate())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["governed_passed"] == result["total"] else 1)
