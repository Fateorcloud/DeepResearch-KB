import asyncio
import mimetypes
from pathlib import Path

import httpx

SKIP = {'.git', '.venv', '.deepresearch-kb', 'node_modules', '__pycache__', 'build', 'dist'}
SUPPORTED = {'.txt', '.md', '.markdown', '.html', '.htm', '.pdf', '.docx', '.csv', '.json'}


def scan(root):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("scan root must be a directory")
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if (path.is_file() and not path.is_symlink()
                and path.suffix.lower() in SUPPORTED
                and not any(part in SKIP for part in relative.parts)
                and path.resolve(strict=True).is_relative_to(root)):
            yield path, relative.as_posix()


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


def push_dir(root, server, kb_id, *, token=None, client=None):
    """Push original files through the authenticated cloud ingest contract."""
    result = {'imported': 0, 'unchanged': 0, 'failed': 0, 'skipped': 0, 'errors': []}
    owns_client = client is None
    cloud = client or httpx.Client(
        base_url=server.rstrip('/'), timeout=120,
        headers={'Authorization': f'Bearer {token}'} if token else {})
    try:
        files = list(scan(root))
    except (OSError, ValueError):
        if owns_client:
            cloud.close()
        raise
    for path, logical in files:
        try:
            with path.open('rb') as handle:
                response = cloud.post(
                    f'/api/kbs/{kb_id}/documents', data={'logical_path': logical},
                    files={'file': (path.name, handle,
                                    mimetypes.guess_type(path.name)[0]
                                    or 'application/octet-stream')})
            response.raise_for_status()
            action = response.json().get('ingest_action', 'imported')
            result[action if action in ('imported', 'unchanged') else 'imported'] += 1
        except Exception as exc:
            result['failed'] += 1
            result['errors'].append({
                'logical_path': logical, 'error_type': type(exc).__name__})
    if owns_client:
        cloud.close()
    return result
