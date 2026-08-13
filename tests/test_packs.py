from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from velours_library.packs import KnowledgePackManager


@dataclass(frozen=True)
class Item:
    item_id: str
    title: str
    source: str
    source_uri: str
    trust_class: str
    media_type: str
    language: str
    sha256: str
    storage_path: str
    rights_note: str
    tags: tuple
    version_label: str = "1.0"
    lifecycle_state: str = "active"
    stale_after: str = None
    supersedes_item_id: str = None
    superseded_by_item_id: str = None


class FakeLibrary:
    def __init__(self, items):
        self.items = {item.item_id: item for item in items}

    def inspect(self, item_id):
        if item_id not in self.items:
            raise KeyError(item_id)
        return self.items[item_id]


def sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_item(tmp_path: Path, item_id: str, data: bytes, **changes):
    path = tmp_path / (item_id + ".bin")
    path.write_bytes(data)
    item = Item(item_id, item_id.title(), "Maker", "https://example.invalid", "primary", "application/octet-stream", "en", sha(path), str(path), None, ("demo",))
    return replace(item, **changes)


def test_pack_identity_is_deterministic_and_order_independent(tmp_path: Path):
    a = make_item(tmp_path, "a", b"alpha")
    b = make_item(tmp_path, "b", b"beta")
    manager = KnowledgePackManager(FakeLibrary([a, b]))
    first = manager.build_manifest("Vehicle Core", "1", [b.item_id, a.item_id])
    second = manager.build_manifest("Vehicle Core", "1", [a.item_id, b.item_id])
    assert first == second


def test_export_deduplicates_identical_payloads(tmp_path: Path):
    a = make_item(tmp_path, "a", b"shared")
    bpath = tmp_path / "b.bin"; bpath.write_bytes(b"shared")
    b = replace(a, item_id="b", title="B", storage_path=str(bpath))
    manager = KnowledgePackManager(FakeLibrary([a, b]))
    manifest = manager.build_manifest("Shared", "1", ["a", "b"])
    out = manager.export(manifest, tmp_path / "bundle")
    objects = [p for p in (out / "objects" / "sha256").rglob("*") if p.is_file()]
    assert len(objects) == 1


def test_manifest_tampering_is_detected(tmp_path: Path):
    item = make_item(tmp_path, "a", b"alpha")
    manager = KnowledgePackManager(FakeLibrary([item]))
    manifest = manager.build_manifest("Core", "1", ["a"])
    manifest["name"] = "Changed"
    result = manager.verify_manifest(manifest)
    assert not result["valid"] and "pack_id_mismatch" in result["errors"]


def test_export_payload_tampering_is_detected(tmp_path: Path):
    item = make_item(tmp_path, "a", b"alpha")
    manager = KnowledgePackManager(FakeLibrary([item]))
    manifest = manager.build_manifest("Core", "1", ["a"])
    out = manager.export(manifest, tmp_path / "bundle")
    payload = next(p for p in (out / "objects" / "sha256").rglob("*") if p.is_file())
    payload.write_bytes(b"tampered")
    result = manager.verify_export(out)
    assert not result["valid"] and any(error.startswith("export_payload_checksum_mismatch") for error in result["errors"])


def test_export_verifies_without_source_library(tmp_path: Path):
    item = make_item(tmp_path, "a", b"alpha")
    manager = KnowledgePackManager(FakeLibrary([item]))
    out = manager.export(manager.build_manifest("Core", "1", ["a"]), tmp_path / "bundle")
    assert KnowledgePackManager.verify_export(out)["valid"] is True


def test_lifecycle_drift_is_warning_not_manifest_rewrite(tmp_path: Path):
    item = make_item(tmp_path, "a", b"alpha", lifecycle_state="active")
    library = FakeLibrary([item])
    manager = KnowledgePackManager(library)
    manifest = manager.build_manifest("Core", "1", ["a"])
    library.items["a"] = replace(item, lifecycle_state="superseded", superseded_by_item_id="b")
    result = manager.verify_against_library(manifest)
    assert result["valid"] is True
    assert "member_lifecycle_state_drift:a" in result["warnings"]
    assert manifest["members"][0]["lifecycle_state"] == "active"


def test_missing_source_payload_blocks_export(tmp_path: Path):
    item = make_item(tmp_path, "a", b"alpha")
    manager = KnowledgePackManager(FakeLibrary([item]))
    manifest = manager.build_manifest("Core", "1", ["a"])
    Path(item.storage_path).unlink()
    result = manager.verify_against_library(manifest)
    assert not result["valid"] and "missing_library_payload:a" in result["errors"]


def test_manifest_and_export_are_immutable_destinations(tmp_path: Path):
    item = make_item(tmp_path, "a", b"alpha")
    manager = KnowledgePackManager(FakeLibrary([item]))
    manifest = manager.build_manifest("Core", "1", ["a"])
    manifest_path = manager.write_manifest(manifest, tmp_path / "manifest.json")
    with pytest.raises(FileExistsError):
        manager.write_manifest(manifest, manifest_path)
    out = manager.export(manifest, tmp_path / "bundle")
    with pytest.raises(FileExistsError):
        manager.export(manifest, out)
