"""Command-line interface for Velour's shared offline library."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .catalog import Candidate, Library, LibraryItem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour", description="Velour's local-first knowledge library")
    parser.add_argument("--root", default="library-data")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_metadata(target: argparse.ArgumentParser) -> None:
        target.add_argument("file")
        target.add_argument("--title", required=True)
        target.add_argument("--source", required=True)
        target.add_argument("--source-uri")
        target.add_argument("--trust", default="unknown")
        target.add_argument("--language", default="en")
        target.add_argument("--rights-note")
        target.add_argument("--tag", action="append", default=[])
        target.add_argument("--version")
        target.add_argument("--stale-after")
        target.add_argument("--supersedes")

    add_metadata(sub.add_parser("stage", help="Quarantine a source file for review"))
    add = sub.add_parser("add", help="Stage and immediately publish a source file")
    add_metadata(add)
    add.add_argument("--published-at")
    publish = sub.add_parser("publish"); publish.add_argument("candidate_id"); publish.add_argument("--published-at")
    reject = sub.add_parser("reject"); reject.add_argument("candidate_id"); reject.add_argument("--reason", required=True)
    candidates = sub.add_parser("candidates"); candidates.add_argument("--state")
    for name in ("inspect", "verify", "remove", "lifecycle", "stale"):
        command = sub.add_parser(name); command.add_argument("identifier")
    refresh = sub.add_parser("refresh"); refresh.add_argument("identifier"); refresh.add_argument("--stale-after")
    search = sub.add_parser("search"); search.add_argument("query"); search.add_argument("--limit", type=int, default=10)
    evidence = sub.add_parser("evidence", help="Return a machine-readable retrieval evidence bundle"); evidence.add_argument("query"); evidence.add_argument("--limit", type=int, default=10)
    reindex = sub.add_parser("reindex", help="Rebuild deterministic retrieval chunks"); reindex.add_argument("identifier", nargs="?")
    sub.add_parser("stale-list", help="List explicitly stale or freshness-expired sources")
    sub.add_parser("list")
    return parser


def _item(item: LibraryItem) -> dict:
    return {"item_id": item.item_id,"title": item.title,"source": item.source,"source_uri": item.source_uri,"trust_class": item.trust_class,"media_type": item.media_type,"language": item.language,"sha256": item.sha256,"storage_path": item.storage_path,"extracted_text_path": item.extracted_text_path,"imported_at": item.imported_at,"published_at": item.published_at,"rights_note": item.rights_note,"tags": list(item.tags),"version_label": item.version_label,"lifecycle_state": item.lifecycle_state,"stale_after": item.stale_after,"supersedes_item_id": item.supersedes_item_id,"superseded_by_item_id": item.superseded_by_item_id}


def _candidate(candidate: Candidate) -> dict:
    return {"candidate_id": candidate.candidate_id,"title": candidate.title,"source": candidate.source,"source_uri": candidate.source_uri,"trust_class": candidate.trust_class,"language": candidate.language,"sha256": candidate.sha256,"staged_path": candidate.staged_path,"staged_at": candidate.staged_at,"state": candidate.state,"published_at": candidate.published_at,"rights_note": candidate.rights_note,"tags": list(candidate.tags),"rejection_reason": candidate.rejection_reason,"version_label": candidate.version_label,"stale_after": candidate.stale_after,"supersedes_item_id": candidate.supersedes_item_id}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    library = Library(Path(args.root))
    try:
        if args.command in ("stage", "add"):
            common = {"title": args.title,"source": args.source,"source_uri": args.source_uri,"trust_class": args.trust,"language": args.language,"rights_note": args.rights_note,"tags": args.tag,"version_label": args.version,"stale_after": args.stale_after,"supersedes_item_id": args.supersedes}
            if args.command == "stage":
                print(json.dumps(_candidate(library.stage(args.file, **common)), indent=2, sort_keys=True))
            else:
                print(json.dumps(_item(library.add(args.file, published_at=args.published_at, **common)), indent=2, sort_keys=True))
            return 0
        if args.command == "publish":
            print(json.dumps(_item(library.publish(args.candidate_id, published_at=args.published_at)), indent=2, sort_keys=True)); return 0
        if args.command == "reject":
            print(json.dumps(_candidate(library.reject(args.candidate_id, args.reason)), indent=2, sort_keys=True)); return 0
        if args.command == "candidates":
            for candidate in library.list_candidates(args.state):
                print("%s\t%s\t%s\t%s" % (candidate.candidate_id, candidate.state, candidate.trust_class, candidate.title))
            return 0
        if args.command == "inspect":
            print(json.dumps(_item(library.inspect(args.identifier)), indent=2, sort_keys=True)); return 0
        if args.command == "lifecycle":
            print(json.dumps(library.lifecycle(args.identifier), indent=2, sort_keys=True)); return 0
        if args.command == "stale":
            print(json.dumps(_item(library.mark_stale(args.identifier)), indent=2, sort_keys=True)); return 0
        if args.command == "refresh":
            print(json.dumps(_item(library.refresh(args.identifier, stale_after=args.stale_after)), indent=2, sort_keys=True)); return 0
        if args.command == "stale-list":
            print(json.dumps(library.stale_items(), indent=2, sort_keys=True)); return 0
        if args.command == "search":
            results = library.search(args.query, args.limit)
            for result in results:
                print("[%0.3f] %s (%s)" % (result.score, result.title, result.item_id))
                print("  source=%s trust=%s sha256=%s" % (result.source, result.trust_class, result.sha256))
                print("  chunk=%s method=%s location=%s" % (result.chunk_id, result.retrieval_method, json.dumps(result.location, sort_keys=True)))
                print("  version=%s lifecycle=%s warnings=%s" % (result.version_label, result.lifecycle_state, ",".join(result.warnings)))
                if result.snippet:
                    print("  %s" % result.snippet)
            return 0 if results else 1
        if args.command == "evidence":
            print(json.dumps(library.evidence_bundle(args.query, args.limit), indent=2, sort_keys=True)); return 0
        if args.command == "reindex":
            print(library.reindex(args.identifier)); return 0
        if args.command == "verify":
            valid = library.verify(args.identifier); print("valid" if valid else "checksum mismatch"); return 0 if valid else 3
        if args.command == "remove":
            print(json.dumps(_item(library.remove(args.identifier)), indent=2, sort_keys=True)); return 0
        if args.command == "list":
            for item in library.list_items():
                print("%s\t%s\t%s\t%s\t%s" % (item.item_id, item.lifecycle_state, item.trust_class, item.source, item.title))
            return 0
    except (FileNotFoundError, ValueError, KeyError, RuntimeError) as exc:
        print(str(exc)); return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
