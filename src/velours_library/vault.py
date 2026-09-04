# SPDX-License-Identifier: GPL-3.0-only
"""Local Velvet vault layout, health policy, and cross-media object catalog.

This module deliberately does not format block devices, unlock encrypted
volumes, delete media, or grant Runtime authority. It manages only a mounted,
explicitly selected vault root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


VAULT_LAYOUT_VERSION = 1
DEFAULT_VAULT_ROOT = Path("/srv/velvet")

VAULT_DIRECTORIES: Tuple[str, ...] = (
    "library/knowledge",
    "library/manuals",
    "library/research",
    "library/vehicle",
    "library/home",
    "library/indexed",
    "receipts/events",
    "receipts/decisions",
    "receipts/actions",
    "receipts/emergency",
    "receipts/security",
    "receipts/integrity",
    "media/video/rolling",
    "media/video/events",
    "media/video/security",
    "media/video/emergency",
    "media/video/retained",
    "media/images/captures",
    "media/images/reference",
    "media/images/retained",
    "media/audio",
    "models/vision",
    "models/speech",
    "models/language",
    "models/embeddings",
    "maps",
    "snapshots/system",
    "snapshots/configuration",
    "snapshots/state",
    "logs/runtime",
    "logs/hardware",
    "logs/network",
    "logs/diagnostics",
    "staging",
    "quarantine",
    "backup",
    "catalog",
)


class RetentionClass(str, Enum):
    CACHE = "CACHE"
    ROLLING = "ROLLING"
    STANDARD = "STANDARD"
    PROTECTED = "PROTECTED"
    PERMANENT = "PERMANENT"


_RETENTION_RANK = {
    RetentionClass.CACHE: 0,
    RetentionClass.ROLLING: 1,
    RetentionClass.STANDARD: 2,
    RetentionClass.PROTECTED: 3,
    RetentionClass.PERMANENT: 4,
}


@dataclass(frozen=True)
class VaultPolicy:
    cleanup_trigger_fraction: float = 0.15
    hard_reserve_fraction: float = 0.10

    def __post_init__(self) -> None:
        if not 0.0 < self.hard_reserve_fraction < self.cleanup_trigger_fraction < 1.0:
            raise ValueError(
                "policy requires 0 < hard_reserve_fraction < cleanup_trigger_fraction < 1"
            )

    def may_auto_purge(self, retention: RetentionClass) -> bool:
        retention = _retention(retention)
        return retention in (RetentionClass.CACHE, RetentionClass.ROLLING)


@dataclass(frozen=True)
class VaultHealth:
    state: str
    root: str
    total_bytes: int
    available_bytes: int
    used_bytes: int
    available_fraction: float
    cleanup_trigger_fraction: float
    hard_reserve_fraction: float
    cleanup_recommended: bool
    reserve_guard_active: bool


class VaultManager:
    """Manage a mounted Velvet vault without owning block-device operations."""

    def __init__(
        self,
        root: Path = DEFAULT_VAULT_ROOT,
        *,
        policy: VaultPolicy = VaultPolicy(),
        statvfs_provider=None,
    ) -> None:
        if not isinstance(root, Path):
            root = Path(root)
        self.root = root.expanduser()
        self.policy = policy
        self._statvfs = statvfs_provider or os.statvfs

    @property
    def manifest_path(self) -> Path:
        return self.root / ".velvet-vault.json"

    @property
    def catalog_path(self) -> Path:
        return self.root / "catalog" / "vault.sqlite3"

    def initialize(self) -> Dict[str, Any]:
        self._ensure_root_safe(create=True)
        for relative in VAULT_DIRECTORIES:
            self._ensure_directory(relative)
        self._initialize_catalog()
        manifest = self._load_or_create_manifest()
        health = self.health()
        return {
            "manifest": manifest,
            "health": asdict(health),
            "directory_count": len(VAULT_DIRECTORIES),
            "catalog": str(self.catalog_path),
        }

    def health(self) -> VaultHealth:
        self._ensure_root_safe(create=False)
        stats = self._statvfs(str(self.root))
        block_size = int(stats.f_frsize or stats.f_bsize)
        total = int(block_size * stats.f_blocks)
        available = int(block_size * stats.f_bavail)
        used = max(0, total - available)
        fraction = (available / total) if total else 0.0

        if fraction <= self.policy.hard_reserve_fraction:
            state = "reserve_guard"
        elif fraction <= self.policy.cleanup_trigger_fraction:
            state = "cleanup_due"
        else:
            state = "healthy"

        return VaultHealth(
            state=state,
            root=str(self.root),
            total_bytes=total,
            available_bytes=available,
            used_bytes=used,
            available_fraction=fraction,
            cleanup_trigger_fraction=self.policy.cleanup_trigger_fraction,
            hard_reserve_fraction=self.policy.hard_reserve_fraction,
            cleanup_recommended=state in ("cleanup_due", "reserve_guard"),
            reserve_guard_active=state == "reserve_guard",
        )

    def register_object(
        self,
        path: Path,
        *,
        kind: str,
        source: str,
        classification: str = "local",
        retention: RetentionClass = RetentionClass.STANDARD,
        related_event: Optional[str] = None,
        related_receipt: Optional[str] = None,
        tags: Sequence[str] = (),
    ) -> Dict[str, Any]:
        self._ensure_root_safe(create=False)
        retention = _retention(retention)
        relative_path, resolved = self._resolve_object_path(path)
        if not resolved.exists() or not resolved.is_file():
            raise ValueError("vault object must be an existing regular file")

        digest = _sha256_file(resolved)
        object_id = "obj-" + uuid.uuid4().hex
        created = datetime.now(timezone.utc).isoformat()
        normalized_tags = tuple(sorted({_text(tag, "tag") for tag in tags}))

        record = {
            "object_id": object_id,
            "kind": _text(kind, "kind"),
            "path": relative_path.as_posix(),
            "created": created,
            "source": _text(source, "source"),
            "classification": _text(classification, "classification"),
            "retention": retention.value,
            "sha256": digest,
            "related_event": _optional_text(related_event, "related_event"),
            "related_receipt": _optional_text(related_receipt, "related_receipt"),
            "tags": list(normalized_tags),
        }

        self._initialize_catalog()
        try:
            with sqlite3.connect(str(self.catalog_path)) as db:
                db.execute(
                    """
                    INSERT INTO vault_objects (
                        object_id, kind, path, created, source, classification,
                        retention, sha256, related_event, related_receipt, tags_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["object_id"],
                        record["kind"],
                        record["path"],
                        record["created"],
                        record["source"],
                        record["classification"],
                        record["retention"],
                        record["sha256"],
                        record["related_event"],
                        record["related_receipt"],
                        json.dumps(record["tags"], sort_keys=True, separators=(",", ":")),
                    ),
                )
                db.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("vault object path is already registered") from exc
        return record

    def list_objects(
        self,
        *,
        kind: Optional[str] = None,
        retention: Optional[RetentionClass] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        self._ensure_root_safe(create=False)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        self._initialize_catalog()

        clauses: List[str] = []
        params: List[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(_text(kind, "kind"))
        if retention is not None:
            clauses.append("retention = ?")
            params.append(_retention(retention).value)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        query = (
            "SELECT object_id, kind, path, created, source, classification, "
            "retention, sha256, related_event, related_receipt, tags_json "
            "FROM vault_objects"
            + where
            + " ORDER BY created DESC, object_id DESC LIMIT ?"
        )
        params.append(limit)

        with sqlite3.connect(str(self.catalog_path)) as db:
            rows = db.execute(query, params).fetchall()

        return [
            {
                "object_id": row[0],
                "kind": row[1],
                "path": row[2],
                "created": row[3],
                "source": row[4],
                "classification": row[5],
                "retention": row[6],
                "sha256": row[7],
                "related_event": row[8],
                "related_receipt": row[9],
                "tags": json.loads(row[10]),
            }
            for row in rows
        ]

    def promote(self, object_id: str, retention: RetentionClass) -> Dict[str, Any]:
        self._ensure_root_safe(create=False)
        object_id = _text(object_id, "object_id")
        requested = _retention(retention)
        self._initialize_catalog()

        with sqlite3.connect(str(self.catalog_path)) as db:
            row = db.execute(
                "SELECT retention FROM vault_objects WHERE object_id = ?", (object_id,)
            ).fetchone()
            if row is None:
                raise KeyError(object_id)
            current = RetentionClass(row[0])
            if _RETENTION_RANK[requested] < _RETENTION_RANK[current]:
                raise ValueError("retention may only be promoted, not downgraded")
            db.execute(
                "UPDATE vault_objects SET retention = ? WHERE object_id = ?",
                (requested.value, object_id),
            )
            db.commit()

        return {"object_id": object_id, "retention": requested.value}

    def verify_object(self, object_id: str) -> Dict[str, Any]:
        self._ensure_root_safe(create=False)
        object_id = _text(object_id, "object_id")
        self._initialize_catalog()

        with sqlite3.connect(str(self.catalog_path)) as db:
            row = db.execute(
                "SELECT path, sha256 FROM vault_objects WHERE object_id = ?", (object_id,)
            ).fetchone()
        if row is None:
            raise KeyError(object_id)

        relative = Path(row[0])
        candidate = self.root / relative
        if candidate.is_symlink():
            return {"object_id": object_id, "verified": False, "reason": "object-symlinked"}
        resolved = candidate.resolve(strict=True)
        root_resolved = self.root.resolve(strict=True)
        if not _is_relative_to(resolved, root_resolved):
            raise ValueError("catalog path escaped vault root")
        if not resolved.is_file():
            return {"object_id": object_id, "verified": False, "reason": "object-unavailable"}

        digest = _sha256_file(resolved)
        return {
            "object_id": object_id,
            "verified": digest == row[1],
            "expected_sha256": row[1],
            "observed_sha256": digest,
        }

    def _ensure_root_safe(self, *, create: bool) -> None:
        if self.root.exists() and self.root.is_symlink():
            raise ValueError("vault root may not be a symlink")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.exists() or not self.root.is_dir():
            raise FileNotFoundError(str(self.root))

    def _ensure_directory(self, relative: str) -> None:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("vault layout paths must stay relative")
        current = self.root
        for part in relative_path.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("vault layout may not traverse symlinks")
            current.mkdir(exist_ok=True)

    def _resolve_object_path(self, path: Path) -> Tuple[Path, Path]:
        if not isinstance(path, Path):
            path = Path(path)
        candidate = path if path.is_absolute() else self.root / path
        if candidate.is_symlink():
            raise ValueError("symlink vault objects are not accepted")
        resolved = candidate.resolve(strict=True)
        root_resolved = self.root.resolve(strict=True)
        if not _is_relative_to(resolved, root_resolved):
            raise ValueError("vault object path must stay inside vault root")

        relative = resolved.relative_to(root_resolved)
        current = root_resolved
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ValueError("vault object path may not traverse symlinks")
        return relative, resolved

    def _initialize_catalog(self) -> None:
        self._ensure_directory("catalog")
        with sqlite3.connect(str(self.catalog_path)) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS vault_objects (
                    object_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    created TEXT NOT NULL,
                    source TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    retention TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    related_event TEXT,
                    related_receipt TEXT,
                    tags_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS vault_objects_retention_idx "
                "ON vault_objects(retention)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS vault_objects_sha256_idx "
                "ON vault_objects(sha256)"
            )
            db.commit()

    def _load_or_create_manifest(self) -> Dict[str, Any]:
        if self.manifest_path.exists():
            if self.manifest_path.is_symlink():
                raise ValueError("vault manifest may not be a symlink")
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if data.get("schema") != "velvet.vault.v1":
                raise ValueError("unsupported vault manifest schema")
            if data.get("layout_version") != VAULT_LAYOUT_VERSION:
                raise ValueError("unsupported vault layout version")
            return data

        data = {
            "schema": "velvet.vault.v1",
            "layout_version": VAULT_LAYOUT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "root_role": "local-vault",
            "authority": "none",
            "auto_delete_classes": [
                RetentionClass.CACHE.value,
                RetentionClass.ROLLING.value,
            ],
            "protected_classes": [
                RetentionClass.PROTECTED.value,
                RetentionClass.PERMANENT.value,
            ],
            "cleanup_trigger_fraction": self.policy.cleanup_trigger_fraction,
            "hard_reserve_fraction": self.policy.hard_reserve_fraction,
        }
        self.manifest_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return data


def _retention(value: Any) -> RetentionClass:
    if isinstance(value, RetentionClass):
        return value
    if isinstance(value, str):
        try:
            return RetentionClass(value.strip().upper())
        except ValueError as exc:
            raise ValueError("unknown retention class") from exc
    raise TypeError("retention must be RetentionClass or string")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be a non-empty string".format(name))
    return value.strip()


def _optional_text(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    return _text(value, name)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="velour-vault",
        description="Initialize and inspect a mounted Velvet local vault.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("VELVET_VAULT_ROOT", str(DEFAULT_VAULT_ROOT))),
    )
    parser.add_argument("--cleanup-trigger", type=float, default=0.15)
    parser.add_argument("--hard-reserve", type=float, default=0.10)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init")
    commands.add_parser("status")

    register = commands.add_parser("register")
    register.add_argument("path", type=Path)
    register.add_argument("--kind", required=True)
    register.add_argument("--source", required=True)
    register.add_argument("--classification", default="local")
    register.add_argument(
        "--retention",
        choices=[item.value for item in RetentionClass],
        default=RetentionClass.STANDARD.value,
    )
    register.add_argument("--event")
    register.add_argument("--receipt")
    register.add_argument("--tag", action="append", default=[])

    listing = commands.add_parser("list")
    listing.add_argument("--kind")
    listing.add_argument(
        "--retention", choices=[item.value for item in RetentionClass]
    )
    listing.add_argument("--limit", type=int, default=100)

    promote = commands.add_parser("promote")
    promote.add_argument("object_id")
    promote.add_argument(
        "retention",
        choices=[item.value for item in RetentionClass],
    )

    verify = commands.add_parser("verify")
    verify.add_argument("object_id")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    policy = VaultPolicy(
        cleanup_trigger_fraction=args.cleanup_trigger,
        hard_reserve_fraction=args.hard_reserve,
    )
    manager = VaultManager(args.root, policy=policy)

    if args.command == "init":
        _json_print(manager.initialize())
        return 0
    if args.command == "status":
        _json_print(asdict(manager.health()))
        return 0
    if args.command == "register":
        _json_print(
            manager.register_object(
                args.path,
                kind=args.kind,
                source=args.source,
                classification=args.classification,
                retention=args.retention,
                related_event=args.event,
                related_receipt=args.receipt,
                tags=args.tag,
            )
        )
        return 0
    if args.command == "list":
        _json_print(
            manager.list_objects(
                kind=args.kind,
                retention=args.retention,
                limit=args.limit,
            )
        )
        return 0
    if args.command == "promote":
        _json_print(manager.promote(args.object_id, args.retention))
        return 0
    if args.command == "verify":
        _json_print(manager.verify_object(args.object_id))
        return 0
    raise RuntimeError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
