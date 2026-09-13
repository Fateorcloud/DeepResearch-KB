"""Local metadata/import CLI. Does not start any upstream application."""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime

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
    retrieve.add_argument("--governed", action="store_true")
    retrieve.add_argument("--as-of", help="ISO timestamp with timezone")
    retrieve.add_argument("--include-superseded", action="store_true")
    retrieve.add_argument("--include-deprecated", action="store_true")
    govern = commands.add_parser("govern", help="Set explicit version validity metadata")
    govern.add_argument("document_id")
    govern.add_argument("version", type=int)
    govern.add_argument("--effective-at", required=True)
    govern.add_argument("--deprecated-at")
    govern.add_argument("--authority", type=int, default=0)
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
            if args.governed or args.as_of or args.include_superseded or args.include_deprecated:
                from .governance import VersionGovernance
                hits = VersionGovernance(store).retrieve(args.kb, args.query, limit=args.limit,
                    as_of=datetime.fromisoformat(args.as_of) if args.as_of else None,
                    include_superseded=args.include_superseded, include_deprecated=args.include_deprecated)
            else:
                hits = store.retrieve(args.kb, args.query, limit=args.limit)
            result = [asdict(e) for e in hits]
        elif args.command == "govern":
            from .governance import VersionGovernance
            VersionGovernance(store).set_metadata(args.document_id, args.version,
                effective_at=datetime.fromisoformat(args.effective_at), authority=args.authority,
                deprecated_at=datetime.fromisoformat(args.deprecated_at) if args.deprecated_at else None)
            result = {"document_id": args.document_id, "version": args.version, "updated": True}
        elif args.command == "resolve":
            result = asdict(store.resolve_reference(args.reference))
        else:
            result = [asdict(v) for v in store.list_versions(args.kb_id, args.logical_path)]
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
