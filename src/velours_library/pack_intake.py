"""Verified quarantine for portable Velour knowledge packs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union
from uuid import uuid4

from .packs import KnowledgePackManager

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_STATES = {"verified", "approved", "rejected"}


@dataclass(frozen=True)
class PackIntakeCandidate:
    candidate_id: str
    pack_id: str
    name: str
    version: str
    source_label: str
    state: str
    staged_path: str
    staged_at: str
    manifest_sha256: str
    member_count: int
    payload_bytes: int
    approved_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    note: Optional[str] = None


class PackIntakeManager:
    """Quarantine and approve already-exported knowledge packs.

    Approval means only that the transferred bundle survived integrity and local
    intake policy checks. It does not install the pack, grant authority, or make
    its contents true.
    """

    def __init__(
        self,
        root: Union[str, Path],
        *,
        max_pack_bytes: int = 8 * 1024 * 1024 * 1024,
        max_members: int = 10000,
        max_manifest_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self.root = Path(root)
        self.incoming_dir = self.root / "incoming" / "packs"
        self.catalog_dir = self.root / "catalog" / "pack-intake"
        self.receipts_dir = self.root / "receipts"
        self.events_path = self.receipts_dir / "pack-intake-events.jsonl"
        self.max_pack_bytes = int(max_pack_bytes)
        self.max_members = int(max_members)
        self.max_manifest_bytes = int(max_manifest_bytes)
        for path in (self.incoming_dir, self.catalog_dir, self.receipts_dir):
            path.mkdir(parents=True, exist_ok=True)

    def stage(
        self,
        bundle_path: Union[str, Path],
        *,
        source_label: str,
        note: Optional[str] = None,
    ) -> PackIntakeCandidate:
        source = Path(bundle_path)
        if not source_label.strip():
            raise ValueError("source_label is required")
        preflight = self._preflight(source)
        verified = KnowledgePackManager.verify_export(source)
        if not verified.get("valid"):
            raise ValueError("pack verification failed: %s" % ", ".join(verified.get("errors", [])))

        manifest_sha = self._sha256_file(source / "manifest.json")
        for existing in self.list_candidates():
            if existing.state in {"verified", "approved"} and existing.pack_id == str(preflight["manifest"]["pack_id"]) and existing.manifest_sha256 == manifest_sha:
                raise ValueError("pack is already present in intake: %s" % existing.candidate_id)

        candidate_id = "pcand_%s" % uuid4().hex
        destination = self.incoming_dir / candidate_id
        temp = Path(tempfile.mkdtemp(prefix=".%s-" % candidate_id, dir=str(self.incoming_dir)))
        try:
            self._copy_canonical_bundle(source, temp, preflight["manifest"])
            staged_check = KnowledgePackManager.verify_export(temp)
            if not staged_check.get("valid"):
                raise RuntimeError("staged pack self-verification failed: %s" % ", ".join(staged_check.get("errors", [])))
            os.replace(str(temp), str(destination))
        except Exception:
            shutil.rmtree(str(temp), ignore_errors=True)
            raise

        now = self._utc_now()
        candidate = PackIntakeCandidate(
            candidate_id=candidate_id,
            pack_id=str(preflight["manifest"]["pack_id"]),
            name=str(preflight["manifest"]["name"]),
            version=str(preflight["manifest"]["version"]),
            source_label=source_label.strip(),
            state="verified",
            staged_path=str(destination),
            staged_at=now,
            manifest_sha256=manifest_sha,
            member_count=int(preflight["member_count"]),
            payload_bytes=int(preflight["payload_bytes"]),
            note=note.strip() if note else None,
        )
        self._write_candidate(candidate)
        self._write_event("stage", candidate, {"source_path": str(source.resolve())})
        return candidate

    def verify_candidate(self, identifier: str) -> Dict[str, object]:
        candidate = self.inspect(identifier)
        if candidate.state not in {"verified", "approved"}:
            raise ValueError("pack candidate is not available for verification")
        staged = Path(candidate.staged_path)
        expected_staged = self.incoming_dir / candidate.candidate_id
        if staged.resolve() != expected_staged.resolve() or not self._is_within(staged.resolve(), self.incoming_dir.resolve()):
            raise RuntimeError("pack candidate staged path changed")
        preflight = self._preflight(staged)
        verification = KnowledgePackManager.verify_export(staged)
        if not verification.get("valid"):
            raise RuntimeError("staged pack verification failed: %s" % ", ".join(verification.get("errors", [])))
        manifest = preflight["manifest"]
        if str(manifest.get("pack_id")) != candidate.pack_id:
            raise RuntimeError("staged pack identity changed")
        if str(manifest.get("name")) != candidate.name or str(manifest.get("version")) != candidate.version:
            raise RuntimeError("pack candidate metadata changed")
        if int(preflight["member_count"]) != candidate.member_count or int(preflight["payload_bytes"]) != candidate.payload_bytes:
            raise RuntimeError("pack candidate size metadata changed")
        if self._sha256_file(staged / "manifest.json") != candidate.manifest_sha256:
            raise RuntimeError("staged manifest changed after intake")
        return {"valid": True, "candidate": candidate, "manifest": manifest, "member_count": preflight["member_count"], "payload_bytes": preflight["payload_bytes"]}

    def approve(self, identifier: str) -> PackIntakeCandidate:
        candidate = self.inspect(identifier)
        if candidate.state != "verified":
            raise ValueError("pack candidate is not awaiting approval")
        self.verify_candidate(candidate.candidate_id)
        updated = self._replace(candidate, state="approved", approved_at=self._utc_now())
        self._write_candidate(updated)
        self._write_event("approve", updated, {"authority_granted": False, "installed": False})
        return updated

    def reject(self, identifier: str, reason: str) -> PackIntakeCandidate:
        candidate = self.inspect(identifier)
        if candidate.state != "verified":
            raise ValueError("pack candidate is not awaiting approval")
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValueError("rejection reason is required")
        shutil.rmtree(candidate.staged_path, ignore_errors=True)
        updated = self._replace(candidate, state="rejected", rejection_reason=clean_reason)
        self._write_candidate(updated)
        self._write_event("reject", updated, {"reason": clean_reason})
        return updated

    def inspect(self, identifier: str) -> PackIntakeCandidate:
        exact = self.catalog_dir / (identifier + ".json")
        if exact.is_file():
            return self._read_candidate(exact)
        matches = sorted(self.catalog_dir.glob(identifier + "*.json"))
        if len(matches) == 1:
            return self._read_candidate(matches[0])
        if not matches:
            raise KeyError(identifier)
        raise KeyError("ambiguous pack candidate identifier: %s" % identifier)

    def list_candidates(self, state: Optional[str] = None) -> List[PackIntakeCandidate]:
        if state is not None and state not in _ALLOWED_STATES:
            raise ValueError("unknown pack candidate state: %s" % state)
        candidates = [self._read_candidate(path) for path in sorted(self.catalog_dir.glob("pcand_*.json"))]
        if state is not None:
            candidates = [candidate for candidate in candidates if candidate.state == state]
        return sorted(candidates, key=lambda candidate: (candidate.staged_at, candidate.candidate_id))

    def _preflight(self, root: Path) -> Dict[str, object]:
        if not root.is_dir() or root.is_symlink():
            raise ValueError("pack path must be a real directory")
        root_resolved = root.resolve()
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink() or not self._is_within(manifest_path.resolve(), root_resolved):
            raise ValueError("pack manifest is missing or unsafe")
        if manifest_path.stat().st_size > self.max_manifest_bytes:
            raise ValueError("pack manifest exceeds max_manifest_bytes")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("pack manifest is not valid JSON")
        if not isinstance(manifest, dict):
            raise ValueError("pack manifest must be an object")
        members = manifest.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("pack manifest has no members")
        if len(members) > self.max_members:
            raise ValueError("pack exceeds max_members")
        for field in ("pack_id", "name", "version"):
            if not isinstance(manifest.get(field), str) or not str(manifest[field]).strip():
                raise ValueError("pack manifest missing %s" % field)

        total = 0
        seen = set()
        for raw in members:
            if not isinstance(raw, dict):
                raise ValueError("pack member must be an object")
            sha = raw.get("sha256")
            if not isinstance(sha, str) or not _SHA256_RE.match(sha):
                raise ValueError("pack member has invalid sha256")
            if sha in seen:
                continue
            seen.add(sha)
            payload = root / "objects" / "sha256" / sha[:2] / sha
            if payload.is_symlink() or not payload.is_file() or not self._is_within(payload.resolve(), root_resolved):
                raise ValueError("pack payload is missing or unsafe: %s" % sha)
            total += payload.stat().st_size
            if total > self.max_pack_bytes:
                raise ValueError("pack exceeds max_pack_bytes")
        return {"manifest": manifest, "member_count": len(members), "payload_bytes": total}

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _copy_canonical_bundle(source: Path, destination: Path, manifest: Dict[str, object]) -> None:
        (destination / "objects" / "sha256").mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source / "manifest.json"), str(destination / "manifest.json"))
        copied = set()
        for raw in manifest.get("members", []):
            sha = str(raw["sha256"])
            if sha in copied:
                continue
            src = source / "objects" / "sha256" / sha[:2] / sha
            dst = destination / "objects" / "sha256" / sha[:2] / sha
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
            copied.add(sha)

    def _write_candidate(self, candidate: PackIntakeCandidate) -> None:
        path = self.catalog_dir / (candidate.candidate_id + ".json")
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(asdict(candidate), sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(str(temp), str(path))

    @staticmethod
    def _read_candidate(path: Path) -> PackIntakeCandidate:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return PackIntakeCandidate(**raw)

    def _write_event(self, action: str, candidate: PackIntakeCandidate, details: Optional[dict] = None) -> None:
        event = {
            "event_id": "lev_%s" % uuid4().hex,
            "timestamp": self._utc_now(),
            "action": action,
            "candidate_id": candidate.candidate_id,
            "pack_id": candidate.pack_id,
            "canonical_receipt": False,
            "receipt_scope": "velours_library_pack_intake_local_evidence",
            "details": details or {},
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    @staticmethod
    def _replace(candidate: PackIntakeCandidate, **changes) -> PackIntakeCandidate:
        values = asdict(candidate)
        values.update(changes)
        return PackIntakeCandidate(**values)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour-pack-intake", description="Verified quarantine for Velour knowledge packs")
    parser.add_argument("--root", default="library-data")
    parser.add_argument("--max-pack-bytes", type=int, default=8 * 1024 * 1024 * 1024)
    parser.add_argument("--max-members", type=int, default=10000)
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage", help="verify and quarantine an exported pack")
    stage.add_argument("bundle")
    stage.add_argument("--source-label", required=True)
    stage.add_argument("--note")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("identifier")
    listing = sub.add_parser("list")
    listing.add_argument("--state")
    approve = sub.add_parser("approve", help="approve a verified pack for later adoption")
    approve.add_argument("identifier")
    reject = sub.add_parser("reject")
    reject.add_argument("identifier")
    reject.add_argument("--reason", required=True)
    return parser


def _candidate_dict(candidate: PackIntakeCandidate) -> Dict[str, object]:
    return asdict(candidate)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    manager = PackIntakeManager(Path(args.root), max_pack_bytes=args.max_pack_bytes, max_members=args.max_members)
    try:
        if args.command == "stage":
            result = manager.stage(args.bundle, source_label=args.source_label, note=args.note)
            print(json.dumps(_candidate_dict(result), sort_keys=True, indent=2))
            return 0
        if args.command == "inspect":
            print(json.dumps(_candidate_dict(manager.inspect(args.identifier)), sort_keys=True, indent=2))
            return 0
        if args.command == "list":
            for candidate in manager.list_candidates(args.state):
                print("%s\t%s\t%s\t%s\t%s" % (candidate.candidate_id, candidate.state, candidate.pack_id, candidate.version, candidate.name))
            return 0
        if args.command == "approve":
            print(json.dumps(_candidate_dict(manager.approve(args.identifier)), sort_keys=True, indent=2))
            return 0
        if args.command == "reject":
            print(json.dumps(_candidate_dict(manager.reject(args.identifier, args.reason)), sort_keys=True, indent=2))
            return 0
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(str(exc))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
