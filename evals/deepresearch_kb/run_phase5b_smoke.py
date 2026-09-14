"""Real MCP stdio client/server smoke for the Phase 5B contract."""
import asyncio, json, sys, tempfile
from pathlib import Path
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.services.knowledge import KnowledgeService
from deepresearch_kb.services.tasks import TaskService
from deepresearch_kb.mcp_server import MCPFacade, create_mcp_server

class SmokeResearch:
    async def run(self, query, *, knowledge_base_ids, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        source = {"chunk_id":"smoke-c1", "text":"Smoke evidence", "source_type":"web_upload",
                  "source_uri":"upload://smoke/docs/smoke.txt", "logical_path":"docs/smoke.txt",
                  "document_id":"smoke-doc", "version":1, "score":1.0}
        (output_dir/'report.md').write_text("Smoke report")
        (output_dir/'sources.json').write_text(json.dumps([source]))
        (output_dir/'trace.json').write_text(json.dumps({"questions":[query]}))
        (output_dir/'run.json').write_text(json.dumps({"status":"completed","knowledge_base_ids":knowledge_base_ids}))

def server(db, artifacts):
    store=KnowledgeStore(db); facade=MCPFacade(KnowledgeService(store), TaskService(SmokeResearch(), artifacts))
    create_mcp_server(facade).run('stdio')

async def client(db, artifacts):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params=StdioServerParameters(command=sys.executable, args=[__file__, '--server', str(db), str(artifacts)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names=[x.name for x in (await session.list_tools()).tools]
            def text(result): return json.loads(result.content[0].text)
            kbs=text(await session.call_tool('list_knowledge_bases', {}));
            if isinstance(kbs, dict): kbs = [kbs]
            kb=kbs[0]['id']
            evidence=text(await session.call_tool('search_knowledge_base', {'query':'Smoke evidence','knowledge_base_ids':[kb]}))
            started=text(await session.call_tool('research', {'query':'smoke query','knowledge_base_ids':[kb]})); tid=started['task_id']
            status={}
            for _ in range(20):
                status=text(await session.call_tool('get_research_status', {'task_id':tid}))
                if status['status'] in ('completed','failed'): break
                await asyncio.sleep(.01)
            result=text(await session.call_tool('get_research_result', {'task_id':tid}))
            payload={'client':'official MCP Python ClientSession over stdio','tools':names,'kb_id':kb,
                     'task_id':tid,'status':status['status'],'report':bool(result['report']),
                     'sources':bool(result['sources']),'trace':bool(result['trace']),'metrics':bool(result['metrics']),
                     'provenance':result['sources'][0]['source_uri'],'version':result['sources'][0]['version'],
                     'evidence_count':len(evidence)}
            print(json.dumps(payload, indent=2))

if __name__=='__main__':
    if '--server' in sys.argv: server(sys.argv[2], sys.argv[3])
    else:
        with tempfile.TemporaryDirectory(prefix='phase5b-smoke-') as d:
            db=Path(d)/'kb.sqlite'; store=KnowledgeStore(db); kb=store.create_knowledge_base('Smoke KB');
            # Add a deterministic record discoverable through the governed service.
            p=Path(d)/'smoke.txt'; p.write_text('Smoke evidence')
            asyncio.run(store.ingest(kb.id,p,logical_path='docs/smoke.txt',source_type='web_upload',source_uri='upload://smoke/docs/smoke.txt'))
            asyncio.run(client(db, Path(d)/'artifacts'))
