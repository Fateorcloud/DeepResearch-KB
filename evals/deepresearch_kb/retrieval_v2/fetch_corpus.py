"""Export the pinned FastAPI Chinese docs used by the retrieval benchmark.

The corpus is not committed. Two pinned commits are exported from a local
clone so that every run sees identical bytes; ``corpus_manifest.json`` records
the SHA-256 of each file and ``--check`` refuses a corpus that differs.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REPO_URL = "https://github.com/fastapi/fastapi.git"
SNAPSHOTS = {
    # FastAPI 0.100.0 (2023-07): first Pydantic v2 release, older zh tutorial.
    "v1": "f8356d9fffcc728062cc4dbfc905882969bd5123",
    # master on 2026-10-31.
    "v2": "45cb2252c737906f37544f5ba6bee0295fb81468",
}
DOCS_PREFIX = "docs/zh/docs/"
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "corpus_manifest.json"
DEFAULT_CORPUS = Path("data/evals/retrieval_v2/corpus")
DEFAULT_CLONE = Path.home() / ".cache" / "deepresearch-kb" / "fastapi"


def _git(clone, *args, text=True):
    return subprocess.run(["git", "-C", str(clone), *args], check=True,
                          capture_output=True, text=text).stdout


def ensure_clone(clone):
    if not (clone / ".git").is_dir():
        clone.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout",
                        REPO_URL, str(clone)], check=True)
    for commit in SNAPSHOTS.values():
        try:
            _git(clone, "cat-file", "-e", f"{commit}^{{commit}}")
        except subprocess.CalledProcessError:
            _git(clone, "fetch", "-q", "origin", commit)


def export(clone, corpus):
    files = {}
    for label, commit in SNAPSHOTS.items():
        names = _git(clone, "ls-tree", "-r", "--name-only", commit, DOCS_PREFIX).split()
        for name in sorted(n for n in names if n.endswith(".md")):
            data = _git(clone, "show", f"{commit}:{name}", text=False)
            relative = name[len(DOCS_PREFIX):]
            target = corpus / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            files[f"{label}/{relative}"] = hashlib.sha256(data).hexdigest()
    return {"source": REPO_URL, "license": "MIT (FastAPI documentation)",
            "snapshots": SNAPSHOTS, "files": files}


def check(corpus, manifest):
    problems = []
    for name, digest in manifest["files"].items():
        path = corpus / name
        if not path.is_file():
            problems.append(f"missing {name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append(f"changed {name}")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--clone", type=Path, default=DEFAULT_CLONE)
    parser.add_argument("--write-manifest", action="store_true",
                        help="record a new manifest instead of checking the committed one")
    args = parser.parse_args()
    ensure_clone(args.clone)
    exported = export(args.clone, args.corpus)
    if args.write_manifest:
        MANIFEST.write_text(json.dumps(exported, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {MANIFEST} ({len(exported['files'])} files)")
        return
    problems = check(args.corpus, json.loads(MANIFEST.read_text(encoding="utf-8")))
    if problems:
        raise SystemExit("corpus differs from manifest:\n" + "\n".join(problems[:20]))
    print(f"corpus ok: {len(exported['files'])} files in {args.corpus}")


if __name__ == "__main__":
    main()
