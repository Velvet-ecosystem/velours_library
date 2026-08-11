"""Command-line interface for Velour's shared offline library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .catalog import Library, LibraryItem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour", description="Velour's local-first knowledge library")
    parser.add_argument("--root", default="library-data", help="Library data root")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Archive and catalog a source file")
    add.add_argument("file")
    add.add_argument("--title", required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--source-uri")
    add.add_argument("--trust", default="unknown")
    add.add_argument("--language", default="en")
    add.add_argument("--published-at")
    add.add_argument("--rights-note")
    add.add_argument("--tag", action="append", default=[])

    inspect = sub.add_parser("inspect", help="Show one catalog record")
    inspect.add_argument("identifier")

    search = sub.add_parser("search", help="Search metadata and extracted text")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    verify = sub.add_parser("verify", help="Verify a canonical payload by SHA-256")
    verify.add_argument("identifier")

    remove = sub.add_parser("remove", help="Remove one provenance record and unreferenced derivatives")
    remove.add_argument("identifier")

    sub.add_parser("list", help="List catalog records")
    return parser


def _print_item(item: LibraryItem) -> None:
    print(json.dumps({
        "item_id": item.item_id,
        "title": item.title,
        "source": item.source,
        "source_uri": item.source_uri,
        "trust_class": item.trust_class,
        "media_type": item.media_type,
        "language": item.language,
        "sha256": item.sha256,
        "storage_path": item.storage_path,
        "extracted_text_path": item.extracted_text_path,
        "imported_at": item.imported_at,
        "published_at": item.published_at,
        "rights_note": item.rights_note,
        "tags": list(item.tags),
    }, indent=2, sort_keys=True))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    library = Library(Path(args.root))

    try:
        if args.command == "add":
            _print_item(library.add(
                args.file,
                title=args.title,
                source=args.source,
                source_uri=args.source_uri,
                trust_class=args.trust,
                language=args.language,
                published_at=args.published_at,
                rights_note=args.rights_note,
                tags=args.tag,
            ))
            return 0

        if args.command == "inspect":
            _print_item(library.inspect(args.identifier))
            return 0

        if args.command == "search":
            results = library.search(args.query, limit=args.limit)
            for result in results:
                print("[%0.3f] %s (%s)" % (result.score, result.title, result.item_id))
                print("  source=%s trust=%s sha256=%s" % (result.source, result.trust_class, result.sha256))
                if result.snippet:
                    print("  %s" % result.snippet)
            return 0 if results else 1

        if args.command == "verify":
            valid = library.verify(args.identifier)
            print("valid" if valid else "checksum mismatch")
            return 0 if valid else 3

        if args.command == "remove":
            _print_item(library.remove(args.identifier))
            return 0

        if args.command == "list":
            for item in library.list_items():
                print("%s\t%s\t%s\t%s" % (item.item_id, item.trust_class, item.source, item.title))
            return 0
    except (FileNotFoundError, ValueError, KeyError, RuntimeError) as exc:
        print(str(exc))
        return 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
