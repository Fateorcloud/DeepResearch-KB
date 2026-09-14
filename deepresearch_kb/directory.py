from pathlib import Path
import asyncio
import mimetypes
import urllib.request

SKIP = {'.git', '.venv', 'node_modules', '__pycache__', 'build', 'dist'}
SUPPORTED = {'.txt', '.md', '.markdown', '.html', '.htm', '.pdf', '.docx', '.csv', '.json'}

def scan(root):
    root = Path(root).resolve()
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix.lower() in SUPPORTED and not any(p in SKIP for p in path.relative_to(root).parts):
            yield path, path.relative_to(root).as_posix()

async def ingest_dir(store, kb_id, root, *, source_type='local_import'):
    result = {'imported': 0, 'unchanged': 0, 'failed': 0, 'skipped': 0, 'errors': []}
    for path, logical in scan(root):
        try:
            before = store.list_versions(kb_id, logical)
            version = await store.ingest(kb_id, path, logical_path=logical, source_type=source_type,
                                         source_uri=f'file://{path}')
            result['unchanged' if before and before[-1].version == version.version else 'imported'] += 1
        except Exception as exc:
            result['failed'] += 1; result['errors'].append({'logical_path': logical, 'error_type': type(exc).__name__})
    return result

def push_dir(root, server, kb_id):
    result = {'imported': 0, 'unchanged': 0, 'failed': 0, 'skipped': 0, 'errors': []}
    for path, logical in scan(root):
        boundary = '----deepresearchkb'
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="logical_path"\r\n\r\n{logical}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                f'Content-Type: {mimetypes.guess_type(path.name)[0] or "application/octet-stream"}\r\n\r\n').encode() + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        req = urllib.request.Request(f'{server.rstrip("/")}/api/kbs/{kb_id}/documents', data=body,
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}, method='POST')
        try:
            with urllib.request.urlopen(req) as response:
                payload = response.read()
            result['imported'] += 1
        except Exception as exc:
            result['failed'] += 1; result['errors'].append({'logical_path': logical, 'error_type': type(exc).__name__})
    return result
