import asyncio
from pathlib import Path
from fastapi.testclient import TestClient

from deepresearch_kb.api import create_app
from deepresearch_kb.directory import ingest_dir, scan
from deepresearch_kb.knowledge import KnowledgeStore
from tests.deepresearch_kb.auth_support import bearer_client, configured_auth


async def loader(path):
    return [{"raw_content": path.read_text()}]


def test_upload_idempotency_version_and_security(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite", loader=loader)
    auth = configured_auth(store.database)
    app = create_app(store=store, auth=auth)
    client = bearer_client(app, auth)
    kb = client.post('/api/kbs', json={'name': 'demo'}).json()['id']
    url = f'/api/kbs/{kb}/documents'
    first = client.post(url, data={'logical_path':'docs/a.txt'}, files={'file':('a.txt', b'one')})
    second = client.post(url, data={'logical_path':'docs/a.txt'}, files={'file':('a.txt', b'one')})
    third = client.post(url, data={'logical_path':'docs/a.txt'}, files={'file':('a.txt', b'two')})
    assert [first.status_code, second.status_code, third.status_code] == [200, 200, 200]
    assert second.json()['version'] == 1 and third.json()['version'] == 2
    assert client.post(url, data={'logical_path':'../x.txt'}, files={'file':('x.txt', b'x')}).status_code == 400
    assert client.post(url, data={'logical_path':'x.bin'}, files={'file':('x.bin', b'x')}).status_code == 400


def test_ingest_dir_recursive_and_idempotent(tmp_path):
    root = tmp_path / 'docs'; (root / 'nested').mkdir(parents=True); (root / '.git').mkdir()
    (root / 'a.txt').write_text('a'); (root / 'nested/b.md').write_text('b'); (root / '.git/ignored.txt').write_text('x')
    store = KnowledgeStore(tmp_path / 'kb.sqlite', loader=loader); kb = store.create_knowledge_base('x').id
    first = asyncio.run(ingest_dir(store, kb, root)); second = asyncio.run(ingest_dir(store, kb, root))
    assert first['imported'] == 2 and second['unchanged'] == 2
    assert {logical for _, logical in scan(root)} == {'a.txt', 'nested/b.md'}
