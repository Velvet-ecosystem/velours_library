"""Target-side adoption of approved portable Velour knowledge packs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .catalog import Library
from .pack_intake import PackIntakeManager

_TRUST_CLASSES = {"primary", "scholarly", "secondary", "community", "owner", "generated", "unknown"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ADOPTION_TAG_PREFIX = "velour-adoption:"
_RECEIPT_SCOPE = "velours_library_pack_adoption_local_evidence"

_MEDIA_SUFFIX = {
    "application/pdf": ".pdf",
    "application/json": ".json",
    "application/toml": ".toml",
    "application/yaml": ".yaml",
    "application/x-yaml": ".yaml",
    "text/yaml": ".yaml",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/x-rst": ".rst",
}


class PackAdoptionManager:
    """Adopt approved knowledge packs into a target library without importing authority.

    Remote trust, tags, freshness, lifecycle state, lineage, and receipts remain
    origin metadata. Local catalog records receive fresh identities and an
    explicit local trust decision.
    """

    def __init__(
        self,
        root: Union[str, Path],
        *,
        library: Optional[Library] = None,
        intake: Optional[PackIntakeManager] = None,
    ) -> None:
        self.root = Path(root)
        self.library = library if library is not None else Library(self.root)
        self.intake = intake if intake is not None else PackIntakeManager(self.root)
        self.catalog_dir = self.root / "catalog" / "pack-adoptions"
        self.journal_dir = self.catalog_dir / "journals"
        self.work_dir = self.root / "incoming" / "pack-adoption-work"
        self.receipts_dir = self.root / "receipts"
        self.events_path = self.receipts_dir / "pack-adoption-events.jsonl"
        for path in (self.catalog_dir, self.journal_dir, self.work_dir, self.receipts_dir):
            path.mkdir(parents=True, exist_ok=True)

    def plan(self, candidate_id: str, *, local_trust: str = "unknown") -> Dict[str, object]:
        trust = self._normalize_trust(local_trust)
        blockers: List[str] = []
        warnings: List[str] = []
        try:
            candidate = self.intake.inspect(candidate_id)
        except KeyError:
            return {
                "eligible": False,
                "candidate_id": candidate_id,
                "local_trust": trust,
                "blockers": ["pack_candidate_not_found"],
                "warnings": [],
                "members": [],
            }
        if candidate.state != "approved":
            blockers.append("pack_candidate_not_approved")
            return {
                "eligible": False,
                "candidate_id": candidate.candidate_id,
                "pack_id": candidate.pack_id,
                "local_trust": trust,
                "blockers": blockers,
                "warnings": warnings,
                "members": [],
            }
        try:
            verified = self.intake.verify_candidate(candidate.candidate_id)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            blockers.append("pack_candidate_verification_failed:%s" % str(exc))
            return {
                "eligible": False,
                "candidate_id": candidate.candidate_id,
                "pack_id": candidate.pack_id,
                "local_trust": trust,
                "blockers": blockers,
                "warnings": warnings,
                "members": [],
            }

        manifest = verified["manifest"]
        members = manifest.get("members") if isinstance(manifest, dict) else None
        if not isinstance(members, list) or not members:
            blockers.append("pack_has_no_members")
            member_plans: List[Dict[str, object]] = []
        else:
            member_plans = []
            for index, raw in enumerate(members):
                member_blockers = self._member_blockers(raw, index)
                blockers.extend(member_blockers)
                if isinstance(raw, dict):
                    remote_id = str(raw.get("item_id") or "")
                    sha = str(raw.get("sha256") or "")
                    member_plans.append(
                        {
                            "remote_item_id": remote_id,
                            "sha256": sha,
                            "title": raw.get("title"),
                            "remote_trust_class": raw.get("trust_class"),
                            "remote_lifecycle_state": raw.get("lifecycle_state"),
                            "local_trust_class": trust,
                            "local_tags": [self._adoption_tag(candidate.candidate_id, candidate.pack_id, remote_id)],
                            "remote_tags_promoted": False,
                            "remote_freshness_promoted": False,
                            "remote_lineage_promoted": False,
                        }
                    )

        adoption_id = self._adoption_id(candidate.candidate_id, candidate.pack_id)
        existing = self._record_path(adoption_id)
        already_adopted = existing.is_file()
        if already_adopted:
            record = self._read_json(existing)
            if record.get("local_trust") != trust:
                blockers.append("existing_adoption_local_trust_conflict")
            else:
                warnings.append("pack_already_adopted")

        return {
            "eligible": not blockers,
            "already_adopted": already_adopted,
            "adoption_id": adoption_id,
            "candidate_id": candidate.candidate_id,
            "pack_id": candidate.pack_id,
            "pack_name": candidate.name,
            "pack_version": candidate.version,
            "source_label": candidate.source_label,
            "local_trust": trust,
            "member_count": len(member_plans),
            "blockers": blockers,
            "warnings": warnings,
            "members": member_plans,
        }

    def adopt(self, candidate_id: str, *, local_trust: str = "unknown") -> Dict[str, object]:
        trust = self._normalize_trust(local_trust)
        candidate = self.intake.inspect(candidate_id)
        adoption_id = self._adoption_id(candidate.candidate_id, candidate.pack_id)
        record_path = self._record_path(adoption_id)
        journal_path = self._journal_path(adoption_id)

        if record_path.is_file():
            record = self._read_json(record_path)
            if record.get("local_trust") != trust:
                raise ValueError("pack already adopted with a different local trust decision")
            self._verify_completed_record(record)
            self._ensure_event(record)
            journal_path.unlink(missing_ok=True)
            shutil.rmtree(str(self.work_dir / adoption_id), ignore_errors=True)
            return record

        if journal_path.is_file():
            self._rollback_journal(self._read_json(journal_path))

        planned = self.plan(candidate.candidate_id, local_trust=trust)
        if not planned.get("eligible"):
            raise ValueError("pack adoption blocked: %s" % ", ".join(planned.get("blockers", [])))

        verified = self.intake.verify_candidate(candidate.candidate_id)
        manifest = dict(verified["manifest"])
        members = [dict(raw) for raw in manifest["members"]]
        member_journal = []
        for raw in members:
            remote_id = str(raw["item_id"])
            member_journal.append(
                {
                    "remote_item_id": remote_id,
                    "sha256": str(raw["sha256"]),
                    "adoption_tag": self._adoption_tag(candidate.candidate_id, candidate.pack_id, remote_id),
                    "state": "pending",
                    "local_candidate_id": None,
                    "local_item_id": None,
                }
            )
        journal: Dict[str, object] = {
            "schema": "velours_library.pack_adoption_journal.v1",
            "adoption_id": adoption_id,
            "candidate_id": candidate.candidate_id,
            "pack_id": candidate.pack_id,
            "local_trust": trust,
            "started_at": self._utc_now(),
            "members": member_journal,
        }
        self._write_json_atomic(journal_path, journal)
        work = self.work_dir / adoption_id
        work.mkdir(parents=True, exist_ok=True)

        try:
            adopted_items: List[Dict[str, object]] = []
            for index, member in enumerate(members):
                entry = member_journal[index]
                sha = str(member["sha256"])
                payload = Path(candidate.staged_path) / "objects" / "sha256" / sha[:2] / sha
                root_resolved = Path(candidate.staged_path).resolve()
                if payload.is_symlink() or not payload.is_file() or not self._is_within(payload.resolve(), root_resolved):
                    raise RuntimeError("pack payload became unsafe during adoption: %s" % sha)
                if self._sha256_file(payload) != sha:
                    raise RuntimeError("pack payload changed during adoption: %s" % sha)

                suffix = self._suffix_for_media(str(member.get("media_type") or "application/octet-stream"))
                local_source = work / ("member-%04d%s" % (index, suffix))
                shutil.copy2(str(payload), str(local_source))
                if self._sha256_file(local_source) != sha:
                    raise RuntimeError("adoption work copy checksum mismatch: %s" % sha)

                adoption_tag = str(entry["adoption_tag"])
                staged = self.library.stage(
                    local_source,
                    title=str(member["title"]),
                    source=str(member["source"]),
                    source_uri=self._optional_text(member.get("source_uri")),
                    trust_class=trust,
                    language=str(member.get("language") or "en"),
                    rights_note=self._optional_text(member.get("rights_note")),
                    tags=[adoption_tag],
                    version_label=self._optional_text(member.get("version_label")),
                    stale_after=None,
                    supersedes_item_id=None,
                )
                entry["state"] = "staged"
                entry["local_candidate_id"] = staged.candidate_id
                self._write_json_atomic(journal_path, journal)
                local_source.unlink(missing_ok=True)

                item = self.library.publish(staged.candidate_id)
                entry["state"] = "published"
                entry["local_item_id"] = item.item_id
                self._write_json_atomic(journal_path, journal)
                if not self.library.verify(item.item_id):
                    raise RuntimeError("adopted library payload failed local verification: %s" % item.item_id)
                entry["state"] = "verified"
                self._write_json_atomic(journal_path, journal)
                adopted_items.append(
                    self._adopted_item_record(candidate, member, item, staged.candidate_id, adoption_tag, trust)
                )

            record: Dict[str, object] = {
                "schema": "velours_library.pack_adoption.v1",
                "adoption_id": adoption_id,
                "candidate_id": candidate.candidate_id,
                "pack_id": candidate.pack_id,
                "pack_name": candidate.name,
                "pack_version": candidate.version,
                "source_label": candidate.source_label,
                "manifest_sha256": candidate.manifest_sha256,
                "local_trust": trust,
                "adopted_at": self._utc_now(),
                "canonical_receipt": False,
                "authority_granted": False,
                "items": adopted_items,
            }
            self._write_json_atomic(record_path, record)
        except Exception:
            if not record_path.is_file():
                try:
                    self._rollback_journal(self._read_json(journal_path))
                finally:
                    shutil.rmtree(str(work), ignore_errors=True)
            raise

        # A durable completed record is the rollback boundary. Evidence failure does
        # not tear adopted items back out of the local library.
        self._ensure_event(record)
        journal_path.unlink(missing_ok=True)
        shutil.rmtree(str(work), ignore_errors=True)
        return record

    def inspect(self, identifier: str) -> Dict[str, object]:
        exact = self._record_path(identifier)
        if exact.is_file():
            return self._read_json(exact)
        matches = []
        for path in sorted(self.catalog_dir.glob("adopt_*.json")):
            if path.parent == self.journal_dir:
                continue
            record = self._read_json(path)
            if (
                str(record.get("adoption_id", "")).startswith(identifier)
                or str(record.get("candidate_id", "")).startswith(identifier)
                or str(record.get("pack_id", "")).startswith(identifier)
            ):
                matches.append(record)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise KeyError(identifier)
        raise KeyError("ambiguous adoption identifier: %s" % identifier)

    def origin_for(self, local_item_id: str) -> Dict[str, object]:
        matches = []
        for path in sorted(self.catalog_dir.glob("adopt_*.json")):
            record = self._read_json(path)
            for item in record.get("items", []):
                if isinstance(item, dict) and item.get("local_item_id") == local_item_id:
                    origin = dict(item)
                    origin.update(
                        {
                            "adoption_id": record["adoption_id"],
                            "candidate_id": record["candidate_id"],
                            "pack_id": record["pack_id"],
                            "pack_name": record["pack_name"],
                            "pack_version": record["pack_version"],
                            "source_label": record["source_label"],
                            "local_trust": record["local_trust"],
                            "canonical_receipt": False,
                            "authority_granted": False,
                        }
                    )
                    matches.append(origin)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise KeyError(local_item_id)
        raise RuntimeError("local item appears in multiple adoption records: %s" % local_item_id)

    def recover(self) -> List[str]:
        recovered: List[str] = []
        for path in sorted(self.journal_dir.glob("adopt_*.json")):
            journal = self._read_json(path)
            adoption_id = str(journal.get("adoption_id") or path.stem)
            record_path = self._record_path(adoption_id)
            if record_path.is_file():
                record = self._read_json(record_path)
                self._verify_completed_record(record)
                self._ensure_event(record)
                path.unlink(missing_ok=True)
                shutil.rmtree(str(self.work_dir / adoption_id), ignore_errors=True)
            else:
                self._rollback_journal(journal)
            recovered.append(adoption_id)
        return recovered

    def _rollback_journal(self, journal: Mapping[str, object]) -> None:
        adoption_id = str(journal.get("adoption_id") or "")
        members = journal.get("members") if isinstance(journal.get("members"), list) else []
        expected = {}
        for raw in members:
            if isinstance(raw, dict):
                tag = str(raw.get("adoption_tag") or "")
                sha = str(raw.get("sha256") or "")
                if tag:
                    expected[tag] = sha

        # Remove published adoption items first. Tags plus expected hashes keep the
        # rollback scoped to this journal even if other library content shares bytes.
        for item in list(self.library.list_items()):
            tags = set(getattr(item, "tags", ()) or ())
            matched = [tag for tag in expected if tag in tags]
            if not matched:
                continue
            if item.sha256 != expected[matched[0]]:
                continue
            try:
                self.library.remove(item.item_id)
            except (KeyError, ValueError):
                pass

        # Catch crashes after stage but before the journal learned the candidate ID.
        for candidate in list(self.library.list_candidates("staged")):
            tags = set(getattr(candidate, "tags", ()) or ())
            matched = [tag for tag in expected if tag in tags]
            if not matched:
                continue
            if candidate.sha256 != expected[matched[0]]:
                continue
            try:
                self.library.reject(candidate.candidate_id, "pack adoption rollback")
            except (KeyError, ValueError):
                pass

        leftovers = []
        for item in list(self.library.list_items()):
            tags = set(getattr(item, "tags", ()) or ())
            if any(tag in tags for tag in expected):
                leftovers.append("item:%s" % item.item_id)
        for staged_candidate in list(self.library.list_candidates("staged")):
            tags = set(getattr(staged_candidate, "tags", ()) or ())
            if any(tag in tags for tag in expected):
                leftovers.append("candidate:%s" % staged_candidate.candidate_id)
        if leftovers:
            raise RuntimeError("adoption rollback incomplete: %s" % ", ".join(sorted(leftovers)))

        journal_path = self._journal_path(adoption_id)
        journal_path.unlink(missing_ok=True)
        shutil.rmtree(str(self.work_dir / adoption_id), ignore_errors=True)
        try:
            self._append_event(
                self._event_id(adoption_id, "rollback"),
                "rollback",
                {
                    "adoption_id": adoption_id,
                    "candidate_id": journal.get("candidate_id"),
                    "pack_id": journal.get("pack_id"),
                    "authority_granted": False,
                },
            )
        except OSError:
            pass

    def _verify_completed_record(self, record: Mapping[str, object]) -> None:
        trust = str(record.get("local_trust") or "")
        items = record.get("items")
        if not isinstance(items, list) or not items:
            raise RuntimeError("completed adoption record has no items")
        for raw in items:
            if not isinstance(raw, dict):
                raise RuntimeError("completed adoption record has invalid item metadata")
            item = self.library.inspect(str(raw["local_item_id"]))
            if item.sha256 != raw.get("sha256"):
                raise RuntimeError("adopted item hash identity drift: %s" % item.item_id)
            if item.trust_class != trust:
                raise RuntimeError("adopted item local trust drift: %s" % item.item_id)
            tag = str(raw.get("adoption_tag") or "")
            if tag not in set(item.tags):
                raise RuntimeError("adopted item provenance tag missing: %s" % item.item_id)
            if not self.library.verify(item.item_id):
                raise RuntimeError("adopted item verification failed: %s" % item.item_id)

    def _ensure_event(self, record: Mapping[str, object]) -> None:
        adoption_id = str(record["adoption_id"])
        event_id = self._event_id(adoption_id, "complete")
        if self._event_exists(event_id):
            return
        self._append_event(
            event_id,
            "complete",
            {
                "adoption_id": adoption_id,
                "candidate_id": record.get("candidate_id"),
                "pack_id": record.get("pack_id"),
                "local_trust": record.get("local_trust"),
                "local_item_ids": [item.get("local_item_id") for item in record.get("items", []) if isinstance(item, dict)],
                "authority_granted": False,
                "imported_receipts": False,
            },
        )

    def _event_exists(self, event_id: str) -> bool:
        if not self.events_path.is_file():
            return False
        try:
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(line).get("event_id") == event_id:
                        return True
                except ValueError:
                    continue
        except OSError:
            return False
        return False

    def _append_event(self, event_id: str, action: str, details: Mapping[str, object]) -> None:
        event = {
            "event_id": event_id,
            "timestamp": self._utc_now(),
            "action": action,
            "canonical_receipt": False,
            "receipt_scope": _RECEIPT_SCOPE,
            "details": dict(details),
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    @staticmethod
    def _member_blockers(raw: object, index: int) -> List[str]:
        prefix = "member_%d" % index
        if not isinstance(raw, dict):
            return [prefix + "_invalid"]
        blockers = []
        for field in ("item_id", "title", "source", "media_type"):
            if not isinstance(raw.get(field), str) or not str(raw.get(field) or "").strip():
                blockers.append(prefix + "_missing_" + field)
        sha = raw.get("sha256")
        if not isinstance(sha, str) or not _SHA256_RE.match(sha):
            blockers.append(prefix + "_invalid_sha256")
        for optional in ("source_uri", "rights_note", "version_label", "stale_after", "supersedes_item_id", "superseded_by_item_id"):
            if raw.get(optional) is not None and not isinstance(raw.get(optional), str):
                blockers.append(prefix + "_invalid_" + optional)
        if raw.get("tags") is not None and not isinstance(raw.get("tags"), list):
            blockers.append(prefix + "_invalid_tags")
        if raw.get("trust_class") is not None and not isinstance(raw.get("trust_class"), str):
            blockers.append(prefix + "_invalid_trust_class")
        if raw.get("lifecycle_state") is not None and not isinstance(raw.get("lifecycle_state"), str):
            blockers.append(prefix + "_invalid_lifecycle_state")
        return blockers

    @staticmethod
    def _adopted_item_record(candidate, member: Mapping[str, object], item, local_candidate_id: str, adoption_tag: str, trust: str) -> Dict[str, object]:
        return {
            "local_item_id": item.item_id,
            "local_candidate_id": local_candidate_id,
            "local_trust_class": trust,
            "adoption_tag": adoption_tag,
            "remote_item_id": member.get("item_id"),
            "title": member.get("title"),
            "source": member.get("source"),
            "source_uri": member.get("source_uri"),
            "media_type": member.get("media_type"),
            "language": member.get("language"),
            "sha256": member.get("sha256"),
            "rights_note": member.get("rights_note"),
            "version_label": member.get("version_label"),
            "remote_trust_class": member.get("trust_class"),
            "remote_tags": list(member.get("tags") or []),
            "remote_lifecycle_state": member.get("lifecycle_state"),
            "remote_stale_after": member.get("stale_after"),
            "remote_supersedes_item_id": member.get("supersedes_item_id"),
            "remote_superseded_by_item_id": member.get("superseded_by_item_id"),
            "source_pack_candidate_id": candidate.candidate_id,
            "source_pack_id": candidate.pack_id,
        }

    @staticmethod
    def _suffix_for_media(media_type: str) -> str:
        normalized = media_type.split(";", 1)[0].strip().lower()
        if normalized in _MEDIA_SUFFIX:
            return _MEDIA_SUFFIX[normalized]
        if normalized.startswith("text/"):
            return ".txt"
        return ".bin"

    @staticmethod
    def _normalize_trust(value: str) -> str:
        trust = str(value).strip().lower() or "unknown"
        if trust not in _TRUST_CLASSES:
            raise ValueError("unknown local trust class: %s" % trust)
        return trust

    @staticmethod
    def _optional_text(value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _adoption_id(candidate_id: str, pack_id: str) -> str:
        digest = hashlib.sha256((candidate_id + "|" + pack_id).encode("utf-8")).hexdigest()
        return "adopt_%s" % digest[:24]

    @staticmethod
    def _adoption_tag(candidate_id: str, pack_id: str, remote_item_id: str) -> str:
        digest = hashlib.sha256((candidate_id + "|" + pack_id + "|" + remote_item_id).encode("utf-8")).hexdigest()
        return _ADOPTION_TAG_PREFIX + digest[:24]

    @staticmethod
    def _event_id(adoption_id: str, action: str) -> str:
        digest = hashlib.sha256((adoption_id + "|" + action).encode("utf-8")).hexdigest()
        return "lev_adopt_%s" % digest[:24]

    def _record_path(self, adoption_id: str) -> Path:
        return self.catalog_dir / (adoption_id + ".json")

    def _journal_path(self, adoption_id: str) -> Path:
        return self.journal_dir / (adoption_id + ".json")

    @staticmethod
    def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        try:
            temp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            os.replace(str(temp), str(path))
        except Exception:
            temp.unlink(missing_ok=True)
            raise

    @staticmethod
    def _read_json(path: Path) -> Dict[str, object]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("adoption metadata is not an object: %s" % path)
        return raw

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour-pack-adopt", description="Adopt approved Velour knowledge packs into a local library")
    parser.add_argument("--root", default="library-data")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "adopt"):
        command = sub.add_parser(name)
        command.add_argument("candidate_id")
        command.add_argument("--trust", default="unknown")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("identifier")
    origin = sub.add_parser("origin")
    origin.add_argument("local_item_id")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    manager = PackAdoptionManager(Path(args.root))
    try:
        if args.command == "plan":
            result = manager.plan(args.candidate_id, local_trust=args.trust)
            print(json.dumps(result, sort_keys=True, indent=2))
            return 0 if result.get("eligible") else 3
        if args.command == "adopt":
            print(json.dumps(manager.adopt(args.candidate_id, local_trust=args.trust), sort_keys=True, indent=2))
            return 0
        if args.command == "inspect":
            print(json.dumps(manager.inspect(args.identifier), sort_keys=True, indent=2))
            return 0
        if args.command == "origin":
            print(json.dumps(manager.origin_for(args.local_item_id), sort_keys=True, indent=2))
            return 0
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(str(exc))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
