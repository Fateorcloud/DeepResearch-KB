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
