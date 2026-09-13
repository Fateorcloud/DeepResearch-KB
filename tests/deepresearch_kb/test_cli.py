import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CLITests(unittest.TestCase):
    def test_persistent_cli_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "kb.sqlite")
            source = Path(directory) / "design.txt"
            source.write_text("SQLite keeps project metadata.", encoding="utf-8")

            def run(*args):
                result = subprocess.run(
                    [sys.executable, "-m", "deepresearch_kb", "--database", database, *args],
                    capture_output=True, text=True, check=True,
                )
                return json.loads(result.stdout)

            kb = run("create", "CLI test")
            self.assertEqual(run("list"), [kb])
            version = run("ingest", kb["id"], str(source), "--logical-path", "design.txt")
            self.assertEqual(run("versions", kb["id"], "design.txt"), [version])
            hits = run("retrieve", "What is SQLite?", "--kb", kb["id"])
            self.assertEqual(len(hits), 1)
            hit = hits[0]
            reference = f"kb://{hit['document_id']}/versions/{hit['version']}/chunks/{hit['chunk_id']}"
            self.assertEqual(run("resolve", reference)["text"], hit["text"])
            run("govern", hit["document_id"], "1", "--effective-at", "2025-01-01T00:00:00Z",
                "--deprecated-at", "2026-01-01T00:00:00Z", "--authority", "75")
            history = run("retrieve", "SQLite", "--kb", kb["id"], "--as-of", "2025-06-01T00:00:00Z")
            self.assertEqual(history[0]["authority"], 75)
            self.assertEqual(history[0]["status"], "active")
            self.assertEqual(run("retrieve", "SQLite", "--kb", kb["id"], "--as-of", "2026-01-01T00:00:00Z"), [])
            deprecated = run("retrieve", "SQLite", "--kb", kb["id"], "--as-of", "2026-01-01T00:00:00Z", "--include-deprecated")
            self.assertEqual(deprecated[0]["status"], "deprecated")
