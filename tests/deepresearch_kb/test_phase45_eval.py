import asyncio
import json

from evals.deepresearch_kb.run_phase45_eval import evaluate


def test_phase45_dataset_and_paired_artifacts(tmp_path):
    result = asyncio.run(evaluate(tmp_path / "phase45"))
    assert len(result["rows"]) == 24
    adaptive = [row for row in result["rows"] if row["arm"] == "adaptive"]
    assert len(adaptive) == 12
    assert all(row["metrics"]["route_matches_gold"] for row in adaptive)
    fixed = [row for row in result["rows"] if row["arm"] == "fixed_hybrid"]
    assert all(row["metrics"]["quick_calls"] == 1 for row in fixed)
    assert all(row["metrics"]["deep_calls"] == 0 for row in fixed)
    for row in result["rows"]:
        folder = tmp_path / "phase45" / row["id"] / row["arm"]
        assert {path.name for path in folder.iterdir()} == {
            "run.json", "plan.json", "trace.json", "sources.json", "report.md"
        }
    manifest = json.loads((tmp_path / "phase45" / "manifest.json").read_text())
    assert len(manifest["dataset_sha256"]) == 64
    assert json.loads((tmp_path / "phase45" / "dataset.json").read_text())["schema"] == 1
