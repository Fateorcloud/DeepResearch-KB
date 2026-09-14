import asyncio
import json
from types import SimpleNamespace
from deepresearch_kb.mcp_server import MCPFacade

class K:
    def list(self): return [SimpleNamespace(id='kb1', name='Docs', created_at='now')]
    def search(self, *args, **kwargs):
        return [SimpleNamespace(chunk_id='c', text='fact', source_uri='kb://d', logical_path='a.md', document_id='d', version=2, status='active')]

class T:
    def __init__(self, root): self.root=root; self.tasks={}
    def create(self, q, ids):
        t=SimpleNamespace(id='t1', query=q, status='queued', artifact_path=str(self.root)); self.tasks[t.id]=t; return t
    def get(self, i):
        if i not in self.tasks: raise KeyError(i)
        return self.tasks[i]

def test_mcp_facade_contract_and_redacted_errors(tmp_path):
    t=T(tmp_path); f=MCPFacade(K(), t)
    assert f.list_knowledge_bases()[0]['id']=='kb1'
    assert f.search_knowledge_base('fact',['kb1'])[0]['version']==2
    assert f.research('q',['kb1'])['task_id']=='t1'
    assert f.get_research_status('t1')['status']=='queued'
    try: f.get_research_status('missing')
    except ValueError as e: assert str(e)=='unknown task_id'
    else: assert False
