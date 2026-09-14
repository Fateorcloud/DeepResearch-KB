# 5-Minute Demo

Install with `uv pip install --python .venv/bin/python -e '.[test]'`.

Run the deterministic core demo with `.venv/bin/python -m deepresearch_kb.demo`; it creates a temporary SQLite KB, ingests internal material, collects evidence through fake adapters, and delegates synthesis without provider cost.

For the product boundary, start `uvicorn deepresearch_kb.api:app --port 8000`, create a KB, upload through `POST /api/kbs/{kb_id}/documents`, and use `ingest-dir` or `push-dir --server http://localhost:8000 --kb KB_ID`. The MCP transport smoke is `.venv/bin/python evals/deepresearch_kb/run_phase5b_smoke.py`; it uses a real stdio server and official ClientSession. Phase 4.5 evaluation is separate and needs provider credentials.
