"""Local lifecycle policy for adopted Velour knowledge-pack revisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, Union

from .catalog import Library
from .pack_adoption import PackAdoptionManager

_STATES = {"installed", "active", "stale", "superseded", "removed"}
_SCHEMA = "velours_library.pack_family.v1"
_ADOPTION_SCHEMA = "velours_library.pack_adoption.v1"
_RECEIPT_SCOPE = "velours_library_pack_lifecycle_local_evidence"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PackLifecycleManager:
    """Choose a preferred adopted pack revision without importing authority."""

    def __init__(self, root: Union[str, Path], *, adoption=None, library=None) -> None:
        self.root = Path(root)
        self.library = library or Library(self.root)
        self.adoption = adoption or PackAdoptionManager(self.root, library=self.library)
        self.family_dir = self.root / "catalog" / "pack-lifecycle" / "families"
        self.events_path = self.root / "receipts" / "pack-lifecycle-events.jsonl"
        self.family_dir.mkdir(parents=True, exist_ok=True)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)

    def register(self, adoption_id: str):
        record = self._adoption(adoption_id)
        path = self._path(record["pack_name"])
        family = self._read(path) if path.is_file() else self._new_family(record)
        revision = self._revision(family, record["adoption_id"], required=False)
        if revision is None:
            revision = self._new_revision(record)
            family["revisions"].append(revision)
            self._save(path, family)
        else:
            self._binding(revision, record)
        self._event(family, revision, "register")
        return self._snapshot(family, revision)

    def activate(self, adoption_id: str):
        family, revision, path = self._locate(adoption_id, verify=True)
        if revision["state"] == "active":
            if family["active_adoption_id"] != revision["adoption_id"]:
                raise RuntimeError("family active pointer drift")
            self._event(family, revision, "activate")
            return self._snapshot(family, revision)
        if revision["state"] != "installed":
            raise ValueError("only an installed revision may be activated")
        if family["active_adoption_id"] not in (None, revision["adoption_id"]):
            raise ValueError("pack family already has an active revision; use supersede")
        now = self._now()
        revision.update(state="active", activated_at=now)
        family.update(active_adoption_id=revision["adoption_id"], updated_at=now)
        self._save(path, family)
        self._event(family, revision, "activate")
        return self._snapshot(family, revision)

    def mark_stale(self, adoption_id: str):
        family, revision, path = self._locate(adoption_id, verify=True)
        if revision["state"] == "stale":
            self._event(family, revision, "stale")
            return self._snapshot(family, revision)
        if revision["state"] not in {"installed", "active"}:
            raise ValueError("only installed or active revisions may become stale")
        now = self._now()
        revision.update(state="stale", stale_at=now)
        if family["active_adoption_id"] == revision["adoption_id"]:
            family["active_adoption_id"] = None
        family["updated_at"] = now
        self._save(path, family)
        self._event(family, revision, "stale")
        return self._snapshot(family, revision)

    def supersede(self, old_id: str, new_id: str):
        old_family, _, old_path = self._locate(old_id, verify=True)
        new_family, _, new_path = self._locate(new_id, verify=True)
        if old_path != new_path or old_family["family_id"] != new_family["family_id"]:
            raise ValueError("pack revisions belong to different families")
        family = self._read(old_path)
        old = self._revision(family, old_id)
        new = self._revision(family, new_id)
        if (old["state"], old.get("superseded_by_adoption_id"), new["state"], family["active_adoption_id"]) == (
            "superseded", new_id, "active", new_id
        ):
            self._event(family, new, "supersede", {"supersedes_adoption_id": old_id})
            return self._snapshot(family, new)
        if old["state"] != "active" or family["active_adoption_id"] != old_id:
            raise ValueError("predecessor must be the active revision")
        if new["state"] != "installed":
            raise ValueError("successor must be installed before supersession")
        now = self._now()
        old.update(state="superseded", superseded_at=now, superseded_by_adoption_id=new_id)
        new.update(state="active", activated_at=now, supersedes_adoption_id=old_id)
        family.update(active_adoption_id=new_id, updated_at=now)
        self._save(old_path, family)
        self._event(family, new, "supersede", {"supersedes_adoption_id": old_id})
        return self._snapshot(family, new)

    def remove(self, adoption_id: str):
        family, revision, path = self._locate(adoption_id, verify=False)
        if revision["state"] == "removed":
            self._event(family, revision, "remove")
            return self._snapshot(family, revision)
        if revision["state"] == "active" or family["active_adoption_id"] == revision["adoption_id"]:
            raise ValueError("active revision must be replaced or made stale before removal")
        revision.update(state="removed", removed_at=self._now())
        family["updated_at"] = self._now()
        self._save(path, family)
        self._event(family, revision, "remove")
        return self._snapshot(family, revision)

    def current(self, pack_name: str):
        path = self._path(pack_name)
        if not path.is_file():
            raise KeyError(pack_name)
        family = self._read(path)
        active = family["active_adoption_id"]
        if active is None:
            return None
        revision = self._revision(family, active)
        if revision["state"] != "active":
            raise RuntimeError("family active pointer drift")
        return self._snapshot(family, revision)

    def history(self, pack_name: str):
        path = self._path(pack_name)
        if not path.is_file():
            raise KeyError(pack_name)
        family = self._read(path)
        rows = sorted(family["revisions"], key=lambda x: (x["registered_at"], x["adoption_id"]))
        return [self._snapshot(family, row) for row in rows]

    def inspect(self, adoption_id: str):
        family, revision, _ = self._locate(adoption_id, verify=False)
        return self._snapshot(family, revision)

    def verify(self, adoption_id: str) -> bool:
        family, revision, _ = self._locate(adoption_id, verify=False)
        self._binding(revision, self._adoption(revision["adoption_id"]))
        self._invariants(family)
        return True

    def _adoption(self, adoption_id: str):
        record = dict(self.adoption.inspect(adoption_id))
        if record.get("schema") != _ADOPTION_SCHEMA:
            raise ValueError("unsupported adoption record schema")
        for field in ("adoption_id", "pack_id", "pack_name", "pack_version", "manifest_sha256", "local_trust"):
            if not isinstance(record.get(field), str) or not record[field].strip():
                raise ValueError("adoption record missing %s" % field)
        if record.get("canonical_receipt") is not False or record.get("authority_granted") is not False:
            raise ValueError("adoption record authority/evidence boundary changed")
        items = record.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("adoption record has no items")
        seen = set()
        for raw in items:
            if not isinstance(raw, dict) or not isinstance(raw.get("local_item_id"), str):
                raise ValueError("adoption item missing local identity")
            if not isinstance(raw.get("sha256"), str) or not _SHA256.match(raw["sha256"]):
                raise ValueError("adoption item has invalid sha256")
            if not isinstance(raw.get("adoption_tag"), str) or not raw["adoption_tag"]:
                raise ValueError("adoption item missing provenance tag")
            item_id = raw["local_item_id"]
            if item_id in seen:
                raise ValueError("adoption record contains duplicate local item identities")
            seen.add(item_id)
            item = self.library.inspect(item_id)
            if item.sha256 != raw["sha256"]:
                raise RuntimeError("adoption/local item hash drift: %s" % item_id)
            if item.trust_class != record["local_trust"] or raw.get("local_trust_class") != record["local_trust"]:
                raise RuntimeError("adoption/local trust drift: %s" % item_id)
            if raw["adoption_tag"] not in set(item.tags):
                raise RuntimeError("adoption provenance tag missing locally: %s" % item_id)
            if not self.library.verify(item_id):
                raise RuntimeError("adopted local item failed verification: %s" % item_id)
        return record

    def _locate(self, adoption_id: str, *, verify: bool):
        matches = []
        for path in sorted(self.family_dir.glob("pfam_*.json")):
            family = self._read(path)
            for revision in family["revisions"]:
                if revision["adoption_id"].startswith(adoption_id):
                    matches.append((family, revision, path))
        exact = [row for row in matches if row[1]["adoption_id"] == adoption_id]
        if exact:
            result = exact[0]
        elif len(matches) == 1:
            result = matches[0]
        elif not matches:
            raise KeyError(adoption_id)
        else:
            raise KeyError("ambiguous adoption identifier: %s" % adoption_id)
        if verify:
            self._binding(result[1], self._adoption(result[1]["adoption_id"]))
        return result

    def _new_family(self, record):
        return {
            "schema": _SCHEMA,
            "family_id": self._family_id(record["pack_name"]),
            "pack_name": record["pack_name"],
            "normalized_name": self._normalize(record["pack_name"]),
            "active_adoption_id": None,
            "updated_at": self._now(),
            "revisions": [],
        }

    def _new_revision(self, record):
        return {
            "adoption_id": record["adoption_id"],
            "pack_id": record["pack_id"],
            "pack_version": record["pack_version"],
            "manifest_sha256": record["manifest_sha256"],
            "local_trust": record["local_trust"],
            "local_item_ids": [x["local_item_id"] for x in record["items"]],
            "state": "installed",
            "registered_at": self._now(),
            "activated_at": None,
            "stale_at": None,
            "superseded_at": None,
            "supersedes_adoption_id": None,
            "superseded_by_adoption_id": None,
            "removed_at": None,
        }

    @staticmethod
    def _revision(family, adoption_id: str, required: bool = True):
        exact = [x for x in family["revisions"] if x["adoption_id"] == adoption_id]
        if exact:
            return exact[0]
        prefix = [x for x in family["revisions"] if x["adoption_id"].startswith(adoption_id)]
        if len(prefix) == 1:
            return prefix[0]
        if not prefix and not required:
            return None
        if not prefix:
            raise KeyError(adoption_id)
        raise KeyError("ambiguous adoption identifier: %s" % adoption_id)

    @staticmethod
    def _binding(revision, record) -> None:
        expected = {
            "adoption_id": record["adoption_id"],
            "pack_id": record["pack_id"],
            "pack_version": record["pack_version"],
            "manifest_sha256": record["manifest_sha256"],
            "local_trust": record["local_trust"],
            "local_item_ids": [x["local_item_id"] for x in record["items"]],
        }
        for key, value in expected.items():
            if revision.get(key) != value:
                raise RuntimeError("pack lifecycle adoption binding drift: %s" % key)

    @staticmethod
    def _invariants(family) -> None:
        if family.get("schema") != _SCHEMA or not isinstance(family.get("revisions"), list):
            raise RuntimeError("invalid pack family registry")
        ids, active = [], []
        for revision in family["revisions"]:
            if not isinstance(revision, dict) or revision.get("state") not in _STATES:
                raise RuntimeError("invalid pack family revision")
            ids.append(revision.get("adoption_id"))
            if revision["state"] == "active":
                active.append(revision.get("adoption_id"))
        if None in ids or len(ids) != len(set(ids)) or len(active) > 1:
            raise RuntimeError("pack family revision invariant failed")
        pointer = family.get("active_adoption_id")
        if (active and pointer != active[0]) or (not active and pointer is not None):
            raise RuntimeError("pack family active pointer drift")

    def _snapshot(self, family, revision):
        result = dict(revision)
        result.update(
            family_id=family["family_id"],
            pack_name=family["pack_name"],
            active_adoption_id=family["active_adoption_id"],
            canonical_receipt=False,
            authority_granted=False,
        )
        return result

    def _read(self, path: Path):
        family = json.loads(path.read_text(encoding="utf-8"))
        self._invariants(family)
        return family

    def _save(self, path: Path, family) -> None:
        self._invariants(family)
        family["updated_at"] = self._now()
        fd, temp = tempfile.mkstemp(prefix=".%s-" % path.name, dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(family, handle, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, str(path))
        except Exception:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def _event(self, family, revision, action: str, extra=None) -> None:
        event_id = self._event_id(family["family_id"], revision["adoption_id"], action)
        if self._event_exists(event_id):
            return
        details = {
            "family_id": family["family_id"], "pack_name": family["pack_name"],
            "adoption_id": revision["adoption_id"], "pack_id": revision["pack_id"],
            "pack_version": revision["pack_version"], "state": revision["state"],
            "active_adoption_id": family["active_adoption_id"], "authority_granted": False,
        }
        details.update(extra or {})
        event = {
            "event_id": event_id, "timestamp": self._now(), "action": action,
            "canonical_receipt": False, "receipt_scope": _RECEIPT_SCOPE, "details": details,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _event_exists(self, event_id: str) -> bool:
        if not self.events_path.is_file():
            return False
        try:
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(line).get("event_id") == event_id:
                        return True
                except ValueError:
                    pass
        except OSError:
            pass
        return False

    @staticmethod
    def _event_id(family_id: str, adoption_id: str, action: str) -> str:
        value = "%s|%s|%s" % (family_id, adoption_id, action)
        return "plev_%s" % hashlib.sha256(value.encode()).hexdigest()[:24]

    @staticmethod
    def _normalize(name: str) -> str:
        value = " ".join(str(name).strip().split()).casefold()
        if not value:
            raise ValueError("pack name is required")
        return value

    @classmethod
    def _family_id(cls, name: str) -> str:
        return "pfam_%s" % hashlib.sha256(cls._normalize(name).encode()).hexdigest()[:24]

    def _path(self, name: str) -> Path:
        return self.family_dir / (self._family_id(name) + ".json")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour-pack-lifecycle")
    parser.add_argument("--root", default="library-data")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("register", "activate", "stale", "remove", "inspect", "verify"):
        p = sub.add_parser(command); p.add_argument("adoption_id")
    p = sub.add_parser("supersede"); p.add_argument("old_adoption_id"); p.add_argument("new_adoption_id")
    for command in ("current", "history"):
        p = sub.add_parser(command); p.add_argument("pack_name")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    manager = PackLifecycleManager(Path(args.root))
    try:
        if args.command == "register": result = manager.register(args.adoption_id)
        elif args.command == "activate": result = manager.activate(args.adoption_id)
        elif args.command == "stale": result = manager.mark_stale(args.adoption_id)
        elif args.command == "remove": result = manager.remove(args.adoption_id)
        elif args.command == "inspect": result = manager.inspect(args.adoption_id)
        elif args.command == "verify": result = {"valid": manager.verify(args.adoption_id), "adoption_id": args.adoption_id}
        elif args.command == "supersede": result = manager.supersede(args.old_adoption_id, args.new_adoption_id)
        elif args.command == "current": result = manager.current(args.pack_name)
        else: result = manager.history(args.pack_name)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(str(exc)); return 2


if __name__ == "__main__":
    raise SystemExit(main())
