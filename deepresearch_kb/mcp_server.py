"""Thin MCP integration over application services.

The optional SDK binding is deliberately isolated; this module contains no
retrieval, governance, or research implementation.
"""
import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

def _dto(value):
    return asdict(value) if hasattr(value, "__dataclass_fields__") else dict(vars(value))

from .api import create_app
from .knowledge import KnowledgeStore
from .services.knowledge import KnowledgeService
from .services.research import ResearchService
from .services.tasks import TaskService


class MCPFacade:
    def __init__(self, knowledge, tasks):
        self.knowledge, self.tasks = knowledge, tasks

    def list_knowledge_bases(self):
        return [_dto(kb) for kb in self.knowledge.list()]

    def search_knowledge_base(self, query, knowledge_base_ids, limit=5, as_of=None):
        try:
            stamp = datetime.fromisoformat(as_of) if as_of else None
            return [_dto(e) for e in self.knowledge.search(query, knowledge_base_ids, limit=limit, as_of=stamp)]
        except (ValueError, KeyError) as exc:
            raise ValueError(str(exc)) from None

    def research(self, query, knowledge_base_ids):
        task = self.tasks.create(query, knowledge_base_ids)
        return {"task_id": task.id, "status": task.status}

    def get_research_status(self, task_id):
        try: return _dto(self.tasks.get(task_id))
        except KeyError: raise ValueError("unknown task_id") from None

    def get_research_result(self, task_id):
        status = self.get_research_status(task_id)
        if status["status"] != "completed":
            raise ValueError("task is not completed")
        root = Path(status["artifact_path"])
        import json
        return {"report": (root / "report.md").read_text(),
                "sources": json.loads((root / "sources.json").read_text()),
                "trace": json.loads((root / "trace.json").read_text()),
                "metrics": json.loads((root / "run.json").read_text())}


def build_facade(database="data/kb.sqlite", artifact_root="data/tasks", *, research=None):
    store = KnowledgeStore(database)
    knowledge = KnowledgeService(store)
    return MCPFacade(knowledge, TaskService(research, artifact_root))


def create_mcp_server(facade):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("MCP SDK is not installed; install project MCP dependencies") from exc
    server = FastMCP("deepresearch-kb")
    server.tool()(facade.list_knowledge_bases)
    server.tool()(facade.search_knowledge_base)
    server.tool()(facade.research)
    server.tool()(facade.get_research_status)
    server.tool()(facade.get_research_result)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--database", default="data/kb.sqlite"); parser.add_argument("--artifacts", default="data/tasks")
    args = parser.parse_args()
    raise SystemExit("Research service wiring is required to start MCP server; use create_mcp_server(facade) from an application entry point")
