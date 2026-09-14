# Phase 5B MCP Integration

MCP is an integration layer over the accepted application services. The five exposed tools are `list_knowledge_bases`, `search_knowledge_base`, `research`, `get_research_status`, and `get_research_result`. The adapter performs validation, delegates to `KnowledgeService`/`TaskService`, and converts DTOs; it does not connect to SQLite, retrieve, govern versions, route research, or synthesize reports itself.

GPT Researcher's upstream MCP modules are retrievers/clients that consume external MCP servers. They are upstream capability and are not represented as this project's contribution. This project exposes its persistent, governed KB and adaptive research capability to an external MCP client.

`research` returns a task ID immediately. Status and result use the same single-process `TaskService` semantics as REST. Process restart loses in-memory task state; no distributed queue, bidirectional sync, MCP resources, or extra tools are included.

The facade has unit coverage for listing, governed search delegation, task creation/status, and redacted invalid-task errors. The declared SDK is constrained to `mcp>=1.9.1,<2`.

External-client smoke used the official MCP Python `ClientSession` over a real stdio transport, launching `evals/deepresearch_kb/run_phase5b_smoke.py --server ...`. The tool sequence completed: `list_knowledge_bases` -> `search_knowledge_base` -> `research` -> `get_research_status` -> `get_research_result`. The smoke returned a task ID, reached `completed`, and retrieved report, sources, trace, and metrics. The returned source retained `source_uri=upload://smoke/docs/smoke.txt` and `version=1`. This validates protocol binding and tool dispatch, not provider or report quality. Full external-client task execution remains subject to the single-process task limitation.
