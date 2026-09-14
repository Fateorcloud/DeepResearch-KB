import asyncio
import json
from types import SimpleNamespace

from evals.deepresearch_kb.run_phase45_eval import evaluate
from evals.deepresearch_kb.run_phase45_reports import run


class Reporter:
    def __init__(self):
        self.cfg = SimpleNamespace(llm_kwargs={}, smart_token_limit=0, smart_llm_model="fixture-model")

    async def write_report(self, *, ext_context, custom_prompt):
        return "REPORT\n" + ext_context


def test_phase45_report_runner_preserves_paired_inputs(tmp_path):
    routing = tmp_path / "routing"
    asyncio.run(evaluate(routing))
    output = tmp_path / "reports"
    result = asyncio.run(run(routing, output, factory=lambda query: Reporter(),
                             case_ids=["internal_architecture"]))
    assert len(result["results"]) == 2
    for arm in ("fixed_hybrid", "adaptive"):
        folder = output / "internal_architecture" / arm
        assert json.loads((folder / "metrics.json").read_text())["live_tool_calls"] == 0
        assert (folder / "report.md").read_text().startswith("REPORT\n")
        assert (folder / "sources.json").exists()


def test_phase45_judge_artifact_schema_when_present():
    from pathlib import Path
    artifact = Path("data/evals/phase45-reports-v1/judge.json")
    if not artifact.exists():
        return
    payload = json.loads(artifact.read_text())
    assert payload["scope"].endswith("fallible")
    assert len(payload["rows"]) == 24
    assert {(row["id"], row["arm"]) for row in payload["rows"]}.__len__() == 24
    assert {row["verdict"] for row in payload["rows"]} <= {
        "correct", "incorrect", "unanswerable", "unknown"
    }
