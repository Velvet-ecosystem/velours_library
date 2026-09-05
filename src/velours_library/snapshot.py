"""Deterministic metadata snapshots for archive recovery and drift checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .catalog import Candidate, Library, LibraryItem


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _snapshot_id(core: Dict[str, object]) -> str:
    return "vls_%s" % hashlib.sha256(_canonical_bytes(core)).hexdigest()


def _relative(root: Path, value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    path = Path(value)
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return None


def _item_record(root: Path, item: LibraryItem) -> Dict[str, object]:
    return {
        "item_id": item.item_id,
        "title": item.title,
        "source": item.source,
        "source_uri": item.source_uri,
        "trust_class": item.trust_class,
        "media_type": item.media_type,
        "language": item.language,
        "sha256": item.sha256,
        "storage_path": _relative(root, item.storage_path),
        "extracted_text_path": _relative(root, item.extracted_text_path),
        "imported_at": item.imported_at,
        "published_at": item.published_at,
        "rights_note": item.rights_note,
        "tags": list(item.tags),
        "version_label": item.version_label,
        "lifecycle_state": item.lifecycle_state,
        "stale_after": item.stale_after,
        "supersedes_item_id": item.supersedes_item_id,
        "superseded_by_item_id": item.superseded_by_item_id,
    }


def _candidate_record(root: Path, candidate: Candidate) -> Dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "title": candidate.title,
        "source": candidate.source,
        "source_uri": candidate.source_uri,
        "trust_class": candidate.trust_class,
        "language": candidate.language,
        "sha256": candidate.sha256,
        "staged_path": _relative(root, candidate.staged_path),
        "staged_at": candidate.staged_at,
        "state": candidate.state,
        "published_at": candidate.published_at,
        "rights_note": candidate.rights_note,
        "tags": list(candidate.tags),
        "rejection_reason": candidate.rejection_reason,
        "version_label": candidate.version_label,
        "stale_after": candidate.stale_after,
        "supersedes_item_id": candidate.supersedes_item_id,
    }


class LibrarySnapshotManager:
    """Create self-identifying metadata snapshots without copying canonical bytes."""

    def __init__(self, library: Library) -> None:
        self.library = library
        self.snapshot_dir = self.library.catalog_dir / "snapshots"

    def create_payload(self, *, include_candidates: bool = True) -> Dict[str, object]:
        items = sorted((_item_record(self.library.root, item) for item in self.library.list_items()), key=lambda row: str(row["item_id"]))
        candidates: List[Dict[str, object]] = []
        if include_candidates:
            candidates = sorted((_candidate_record(self.library.root, candidate) for candidate in self.library.list_candidates()), key=lambda row: str(row["candidate_id"]))
        core: Dict[str, object] = {
            "schema": "velour.library-snapshot.v1",
            "items": items,
            "candidates": candidates,
            "include_candidates": bool(include_candidates),
            "canonical_bytes_embedded": False,
            "canonical_receipt": False,
            "authority": "none",
        }
        return {
            "snapshot_id": _snapshot_id(core),
            "generated_at": _utc_now(),
            "core": core,
        }

    def write(self, output: Optional[Path] = None, *, include_candidates: bool = True) -> Tuple[Path, Dict[str, object]]:
        payload = self.create_payload(include_candidates=include_candidates)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        target = output or (self.snapshot_dir / (str(payload["snapshot_id"]) + ".json"))
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
        return target, payload

    @staticmethod
    def inspect(path: Path) -> Dict[str, object]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("core"), dict):
            raise ValueError("invalid Library snapshot")
        expected = _snapshot_id(payload["core"])
        actual = payload.get("snapshot_id")
        return {
            "valid": actual == expected,
            "snapshot_id": actual,
            "expected_snapshot_id": expected,
            "generated_at": payload.get("generated_at"),
            "item_count": len(payload["core"].get("items", [])),
            "candidate_count": len(payload["core"].get("candidates", [])),
            "canonical_receipt": False,
            "authority": "none",
        }

    def compare(self, path: Path) -> Dict[str, object]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("core"), dict):
            raise ValueError("invalid Library snapshot")
        expected_id = _snapshot_id(payload["core"])
        if payload.get("snapshot_id") != expected_id:
            raise ValueError("snapshot identity mismatch")
        old_items = {str(row["item_id"]): row for row in payload["core"].get("items", []) if isinstance(row, dict) and row.get("item_id")}
        current_items = {item.item_id: _item_record(self.library.root, item) for item in self.library.list_items()}
        added = sorted(set(current_items) - set(old_items))
        removed = sorted(set(old_items) - set(current_items))
        changed = sorted(
            item_id for item_id in set(old_items) & set(current_items)
            if old_items[item_id] != current_items[item_id]
        )
        return {
            "snapshot_id": payload.get("snapshot_id"),
            "added_item_ids": added,
            "removed_item_ids": removed,
            "changed_item_ids": changed,
            "drift": bool(added or removed or changed),
            "reference_only": True,
            "canonical_receipt": False,
            "authority": "none",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour-snapshot", description="Create or compare deterministic Velour Library catalog snapshots")
    parser.add_argument("--root", default="library-data")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--output")
    create.add_argument("--published-only", action="store_true", help="Exclude quarantine candidate metadata")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("snapshot")
    compare = sub.add_parser("compare")
    compare.add_argument("snapshot")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    manager = LibrarySnapshotManager(Library(Path(args.root)))
    try:
        if args.command == "create":
            path, payload = manager.write(Path(args.output) if args.output else None, include_candidates=not args.published_only)
            print(json.dumps({"path": str(path), "snapshot_id": payload["snapshot_id"]}, indent=2, sort_keys=True)); return 0
        if args.command == "inspect":
            report = manager.inspect(Path(args.snapshot)); print(json.dumps(report, indent=2, sort_keys=True)); return 0 if report["valid"] else 3
        if args.command == "compare":
            report = manager.compare(Path(args.snapshot)); print(json.dumps(report, indent=2, sort_keys=True)); return 0 if not report["drift"] else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc)); return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
