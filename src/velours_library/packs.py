"""Portable, deterministic knowledge packs for Velour's Library."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from .source_provenance import SourceProvenanceManager, validate_source_provenance_snapshot

_PACK_SCHEMA = "velours_library.knowledge_pack.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pack_id(seed: Mapping[str, object]) -> str:
    digest = hashlib.sha256(_canonical_bytes(seed)).hexdigest()
    return "kpack_%s" % digest[:24]


class KnowledgePackManager:
    """Build, verify, and export portable knowledge-pack manifests."""

    def __init__(self, library) -> None:
        self.library = library
        root = getattr(library, "root", None)
        self.provenance = SourceProvenanceManager(root, library=library) if root is not None else None

    def build_manifest(self, name: str, version: str, item_ids: Iterable[str], *, description: Optional[str] = None) -> Dict[str, object]:
        clean_name = name.strip()
        clean_version = version.strip()
        if not clean_name or not clean_version:
            raise ValueError("pack name and version are required")
        ids = sorted({str(item_id).strip() for item_id in item_ids if str(item_id).strip()})
        if not ids:
            raise ValueError("knowledge pack requires at least one item")
        members: List[Dict[str, object]] = []
        for item_id in ids:
            item = self.library.inspect(item_id)
            payload = Path(item.storage_path)
            if not payload.is_file():
                raise FileNotFoundError(str(payload))
            actual = _sha256_file(payload)
            if actual != item.sha256:
                raise RuntimeError("source payload checksum mismatch: %s" % item.item_id)
            members.append(self._member_snapshot(item, payload.stat().st_size))
        seed: Dict[str, object] = {
            "schema": _PACK_SCHEMA,
            "name": clean_name,
            "version": clean_version,
            "description": description.strip() if description else None,
            "members": members,
        }
        manifest = dict(seed)
        manifest["pack_id"] = _pack_id(seed)
        return manifest

    @staticmethod
    def verify_manifest(manifest: Mapping[str, object]) -> Dict[str, object]:
        errors: List[str] = []
        if manifest.get("schema") != _PACK_SCHEMA:
            errors.append("unsupported_schema")
        if not isinstance(manifest.get("name"), str) or not str(manifest.get("name", "")).strip():
            errors.append("missing_name")
        if not isinstance(manifest.get("version"), str) or not str(manifest.get("version", "")).strip():
            errors.append("missing_version")
        members = manifest.get("members")
        if not isinstance(members, list) or not members:
            errors.append("missing_members")
            members = []
        seen_items = set()
        for raw in members:
            if not isinstance(raw, dict):
                errors.append("invalid_member")
                continue
            item_id = raw.get("item_id")
            sha = raw.get("sha256")
            if not isinstance(item_id, str) or not item_id:
                errors.append("invalid_member_item_id")
            elif item_id in seen_items:
                errors.append("duplicate_member_item_id:%s" % item_id)
            else:
                seen_items.add(item_id)
            if not isinstance(sha, str) or not _SHA256_RE.match(sha):
                errors.append("invalid_member_sha256:%s" % (item_id or "unknown"))
            if "source_provenance" in raw:
                try:
                    validate_source_provenance_snapshot(raw.get("source_provenance"))
                except ValueError as exc:
                    errors.append("invalid_member_source_provenance:%s:%s" % (item_id or "unknown", str(exc)))
        seed = {key: value for key, value in manifest.items() if key != "pack_id"}
        expected = _pack_id(seed)
        if manifest.get("pack_id") != expected:
            errors.append("pack_id_mismatch")
        return {"valid": not errors, "errors": errors, "expected_pack_id": expected}

    def verify_against_library(self, manifest: Mapping[str, object]) -> Dict[str, object]:
        base = self.verify_manifest(manifest)
        errors = list(base["errors"])
        warnings: List[str] = []
        if base["valid"]:
            for raw in manifest.get("members", []):
                member = dict(raw)
                item_id = str(member["item_id"])
                try:
                    item = self.library.inspect(item_id)
                except KeyError:
                    errors.append("missing_library_item:%s" % item_id)
                    continue
                payload = Path(item.storage_path)
                if not payload.is_file():
                    errors.append("missing_library_payload:%s" % item_id)
                    continue
                actual = _sha256_file(payload)
                if actual != member.get("sha256") or actual != item.sha256:
                    errors.append("payload_checksum_mismatch:%s" % item_id)
                    continue
                self._append_drift_warnings(warnings, member, item)
        return {"valid": not errors, "errors": errors, "warnings": sorted(set(warnings))}

    def write_manifest(self, manifest: Mapping[str, object], path) -> Path:
        checked = self.verify_manifest(manifest)
        if not checked["valid"]:
            raise ValueError("invalid pack manifest: %s" % ", ".join(checked["errors"]))
        destination = Path(path)
        if destination.exists():
            raise FileExistsError(str(destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_canonical_bytes(manifest) + b"\n")
        return destination

    def export(self, manifest: Mapping[str, object], destination) -> Path:
        verification = self.verify_against_library(manifest)
        if not verification["valid"]:
            raise RuntimeError("cannot export invalid pack: %s" % ", ".join(verification["errors"]))
        target = Path(destination)
        if target.exists():
            raise FileExistsError(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(tempfile.mkdtemp(prefix=".%s-" % target.name, dir=str(target.parent)))
        try:
            (temp / "objects" / "sha256").mkdir(parents=True, exist_ok=True)
            (temp / "manifest.json").write_bytes(_canonical_bytes(manifest) + b"\n")
            copied = set()
            for raw in manifest.get("members", []):
                member = dict(raw)
                sha = str(member["sha256"])
                if sha in copied:
                    continue
                item = self.library.inspect(str(member["item_id"]))
                source = Path(item.storage_path)
                object_path = temp / "objects" / "sha256" / sha[:2] / sha
                object_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(source), str(object_path))
                if _sha256_file(object_path) != sha:
                    raise RuntimeError("export payload checksum mismatch: %s" % sha)
                copied.add(sha)
            bundle = self.verify_export(temp)
            if not bundle["valid"]:
                raise RuntimeError("export self-verification failed: %s" % ", ".join(bundle["errors"]))
            os.replace(str(temp), str(target))
        except Exception:
            shutil.rmtree(str(temp), ignore_errors=True)
            raise
        return target

    @staticmethod
    def verify_export(path) -> Dict[str, object]:
        root = Path(path)
        errors: List[str] = []
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            return {"valid": False, "errors": ["missing_manifest"], "warnings": []}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"valid": False, "errors": ["invalid_manifest_json"], "warnings": []}
        checked = KnowledgePackManager.verify_manifest(manifest)
        errors.extend(checked["errors"])
        for raw in manifest.get("members", []) if isinstance(manifest.get("members"), list) else []:
            if not isinstance(raw, dict):
                continue
            sha = raw.get("sha256")
            if not isinstance(sha, str) or not _SHA256_RE.match(sha):
                continue
            payload = root / "objects" / "sha256" / sha[:2] / sha
            if not payload.is_file():
                errors.append("missing_export_payload:%s" % sha)
                continue
            if _sha256_file(payload) != sha:
                errors.append("export_payload_checksum_mismatch:%s" % sha)
        return {"valid": not errors, "errors": sorted(set(errors)), "warnings": [], "manifest": manifest}

    def _member_snapshot(self, item, payload_bytes: int) -> Dict[str, object]:
        member: Dict[str, object] = {
            "item_id": item.item_id,
            "title": item.title,
            "source": item.source,
            "source_uri": item.source_uri,
            "trust_class": item.trust_class,
            "media_type": item.media_type,
            "language": item.language,
            "sha256": item.sha256,
            "payload_bytes": int(payload_bytes),
            "version_label": getattr(item, "version_label", None),
            "lifecycle_state": getattr(item, "lifecycle_state", "active"),
            "stale_after": getattr(item, "stale_after", None),
            "supersedes_item_id": getattr(item, "supersedes_item_id", None),
            "superseded_by_item_id": getattr(item, "superseded_by_item_id", None),
            "rights_note": item.rights_note,
            "tags": list(item.tags),
        }
        if self.provenance is not None:
            snapshot = self.provenance.snapshot(item.item_id)
            if snapshot is not None:
                member["source_provenance"] = snapshot
        return member

    def _append_drift_warnings(self, warnings: List[str], member: Mapping[str, object], item) -> None:
        for field in ("version_label", "lifecycle_state", "stale_after", "supersedes_item_id", "superseded_by_item_id"):
            if member.get(field) != getattr(item, field, None):
                warnings.append("member_%s_drift:%s" % (field, item.item_id))
        if self.provenance is not None:
            current = self.provenance.snapshot(item.item_id)
            frozen = member.get("source_provenance") if "source_provenance" in member else None
            if frozen != current:
                warnings.append("member_source_provenance_drift:%s" % item.item_id)
