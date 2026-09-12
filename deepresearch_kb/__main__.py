"""Local metadata/import CLI. Does not start any upstream application."""

import argparse
import asyncio
import json
from dataclasses import asdict

from .knowledge import KnowledgeStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/kb.sqlite")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("name")
    commands.add_parser("list")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("kb_id")
    ingest.add_argument("file")
    ingest.add_argument("--logical-path", required=True)
    ingest.add_argument("--source-type", choices=["local_import", "web_upload"], default="local_import")
    ingest.add_argument("--source-uri")
    versions = commands.add_parser("versions")
    versions.add_argument("kb_id")
    versions.add_argument("logical_path")
    retrieve = commands.add_parser("retrieve")
    retrieve.add_argument("query")
    retrieve.add_argument("--kb", action="append", required=True)
    retrieve.add_argument("--limit", type=int, default=5)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("reference")
    args = parser.parse_args()
    store = KnowledgeStore(args.database)
    try:
        if args.command == "create":
            result = asdict(store.create_knowledge_base(args.name))
        elif args.command == "list":
            result = [asdict(kb) for kb in store.list_knowledge_bases()]
        elif args.command == "ingest":
            result = asdict(asyncio.run(store.ingest(
                args.kb_id, args.file, logical_path=args.logical_path,
                source_type=args.source_type, source_uri=args.source_uri,
            )))
        elif args.command == "retrieve":
            result = [asdict(e) for e in store.retrieve(args.kb, args.query, limit=args.limit)]
        elif args.command == "resolve":
            result = asdict(store.resolve_reference(args.reference))
        else:
            result = [asdict(v) for v in store.list_versions(args.kb_id, args.logical_path)]
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
