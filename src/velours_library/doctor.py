"""Read-only health audit for Velour's local Library data root."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from .catalog import Library


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class AuditFinding:
    severity: str
    code: str
    message: str
    identifier: Optional[str] = None
    path: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "identifier": self.identifier,
            "path": self.path,
        }


class LibraryDoctor:
    """Audit invariants without mutating Library state or receipts."""

    def __init__(self, library: Library) -> None:
        self.library = library

    def audit(self, *, verify_hashes: bool = True) -> Dict[str, object]:
        findings: List[AuditFinding] = []
        items = self.library.list_items()
        candidates = self.library.list_candidates()
        referenced_archive: Set[Path] = set()
        referenced_text: Set[Path] = set()
        duplicate_groups: Dict[str, List[str]] = {}

        for item in items:
            storage = Path(item.storage_path)
            referenced_archive.add(storage.resolve(strict=False))
            duplicate_groups.setdefault(item.sha256, []).append(item.item_id)
            if not storage.is_file():
                findings.append(AuditFinding("error", "archive_missing", "canonical archive payload is missing", item.item_id, str(storage)))
            elif verify_hashes:
                try:
                    actual = _sha256(storage)
                except OSError as exc:
                    findings.append(AuditFinding("error", "archive_unreadable", str(exc), item.item_id, str(storage)))
                else:
                    if actual != item.sha256:
                        findings.append(AuditFinding("error", "archive_checksum_mismatch", "canonical SHA-256 does not match catalog identity", item.item_id, str(storage)))
            if item.extracted_text_path:
                extracted = Path(item.extracted_text_path)
                referenced_text.add(extracted.resolve(strict=False))
                if not extracted.is_file():
                    findings.append(AuditFinding("warning", "extracted_text_missing", "catalog points to a missing derived text file; reindex/re-extraction is required", item.item_id, str(extracted)))

        for candidate in candidates:
            if candidate.state != "staged":
                continue
            staged = Path(candidate.staged_path)
            if not staged.is_file():
                findings.append(AuditFinding("error", "staged_payload_missing", "staged candidate has no quarantine payload", candidate.candidate_id, str(staged)))
                continue
            if verify_hashes:
                try:
                    actual = _sha256(staged)
                except OSError as exc:
                    findings.append(AuditFinding("error", "staged_unreadable", str(exc), candidate.candidate_id, str(staged)))
                else:
                    if actual != candidate.sha256:
                        findings.append(AuditFinding("error", "staged_checksum_mismatch", "staged candidate SHA-256 no longer matches", candidate.candidate_id, str(staged)))

        if self.library.archive_dir.is_dir():
            for path in self.library.archive_dir.rglob("*"):
                if path.is_file() and path.resolve(strict=False) not in referenced_archive:
                    findings.append(AuditFinding("warning", "orphan_archive_payload", "archive object is not referenced by any catalog item", path= str(path)))

        if self.library.text_dir.is_dir():
            for path in self.library.text_dir.rglob("*"):
                if path.is_file() and path.resolve(strict=False) not in referenced_text:
                    findings.append(AuditFinding("warning", "orphan_extracted_text", "derived text file is not referenced by any catalog item", path=str(path)))

        staged_paths = {
            Path(candidate.staged_path).resolve(strict=False)
            for candidate in candidates
            if candidate.state == "staged"
        }
        if self.library.incoming_dir.is_dir():
            for path in self.library.incoming_dir.iterdir():
                if path.is_file() and path.resolve(strict=False) not in staged_paths:
                    findings.append(AuditFinding("warning", "orphan_incoming_payload", "incoming file is not referenced by a staged candidate", path=str(path)))

        duplicates = [
            {"sha256": sha, "item_ids": sorted(ids), "references": len(ids)}
            for sha, ids in sorted(duplicate_groups.items())
            if len(ids) > 1
        ]
        stale = self.library.stale_items()
        errors = sum(1 for finding in findings if finding.severity == "error")
        warnings = sum(1 for finding in findings if finding.severity == "warning")
        return {
            "healthy": errors == 0,
            "errors": errors,
            "warnings": warnings,
            "items": len(items),
            "candidates": len(candidates),
            "staged_candidates": sum(1 for candidate in candidates if candidate.state == "staged"),
            "duplicate_payload_groups": duplicates,
            "stale_items": stale,
            "findings": [finding.as_dict() for finding in findings],
            "verify_hashes": bool(verify_hashes),
            "read_only": True,
            "reference_only": True,
            "canonical_receipt": False,
            "authority": "none",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour-doctor", description="Read-only Velour Library integrity audit")
    parser.add_argument("--root", default="library-data")
    parser.add_argument("--no-hash", action="store_true", help="Skip payload SHA-256 verification for a faster structural audit")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = LibraryDoctor(Library(Path(args.root))).audit(verify_hashes=not args.no_hash)
    print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
    return 0 if report["healthy"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
