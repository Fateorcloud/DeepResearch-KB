"""Offline version-governed evidence context evaluation."""
import asyncio, json, tempfile
from datetime import datetime, timezone
from pathlib import Path
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.governance import VersionGovernance
from deepresearch_kb.research import render_evidence_context

def dt(value): return datetime.fromisoformat(value)

async def evaluate():
    cases=json.loads(Path(__file__).with_name("version_cases.json").read_text())["cases"]
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        async def loader(path): return [{"raw_content":path.read_text(),"url":path.name}]
        store=KnowledgeStore(root/"db",loader=loader); kb=store.create_knowledge_base("eval")
        source=root/"a.txt"
        for text in ("current SQLite","historical SQLite","future SQLite WAL"):
            source.write_text(text); await store.ingest(kb.id,source,logical_path="architecture.txt")
        gov=VersionGovernance(store); doc=store.list_versions(kb.id,"architecture.txt")[0].document_id
        for version,year in ((1,2025),(2,2024),(3,2028)):
            gov.set_metadata(doc,version,effective_at=datetime(year,1,1,tzinfo=timezone.utc),deprecated_at=datetime(2029,1,1,tzinfo=timezone.utc) if version==3 else None)
        rows=[]
        for case in cases:
            evidence=gov.retrieve([kb.id],"SQLite",as_of=dt(case["as_of"]))
            actual=evidence[0].version if evidence else None
            context=render_evidence_context(evidence)
            rows.append({"id":case["id"],"expected":case["expected"],"actual":actual,"passed":actual==case["expected"],"selection":bool("Selection:" in context) if evidence else True})
        return {"passed":sum(r["passed"] for r in rows),"total":len(rows),"rows":rows,"scope":"offline governed context"}

if __name__ == "__main__": print(json.dumps(asyncio.run(evaluate()),indent=2))
