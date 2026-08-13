from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

import pytest

from velours_library.pack_adoption import PackAdoptionManager
from velours_library.packs import KnowledgePackManager
from velours_library.source_provenance import (
    SourceProvenanceManager,
    validate_source_provenance_snapshot,
)


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
    imported_at: str = "2026-07-30T10:00:00Z"
    version_label: str = "1.0"
    lifecycle_state: str = "active"
    stale_after: str = None
    supersedes_item_id: str = None
    superseded_by_item_id: str = None


class FakeLibrary:
    def __init__(self, root: Path, items=()):
        self.root = root
        self.items = {item.item_id: item for item in items}

    def inspect(self, item_id):
        if item_id not in self.items:
            raise KeyError(item_id)
        return self.items[item_id]

    def verify(self, item_id):
        return item_id in self.items


class FakeAdoption:
    def __init__(self, records):
        self.records = records

    def inspect(self, adoption_id):
        if adoption_id not in self.records:
            raise KeyError(adoption_id)
        return self.records[adoption_id]


class FakeIntake:
    def __init__(self, candidates):
        self.candidates = candidates

    def verify_candidate(self, candidate_id):
        if candidate_id not in self.candidates:
            raise KeyError(candidate_id)
        return self.candidates[candidate_id]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_item(tmp_path: Path, item_id="item-a", data=b"alpha", **changes):
    path = tmp_path / (item_id + ".txt")
    path.write_bytes(data)
    item = Item(
        item_id=item_id,
        title="Workshop Manual",
        source="Maker",
        source_uri="https://example.invalid/manual",
        trust_class="primary",
        media_type="text/plain",
        language="en",
        sha256=digest(path),
        storage_path=str(path),
        rights_note="reference only",
        tags=("manual",),
    )
    return replace(item, **changes)


def manager(tmp_path, item):
    library = FakeLibrary(tmp_path, [item])
    return SourceProvenanceManager(tmp_path, library=library), library


def set_full(prov, item_id="item-a"):
    return prov.set(
        item_id,
        author="A. Engineer",
        publisher="Maker Press",
        license_status="manufacturer reference",
        source_published_at="2024-05-01",
        acquired_at="2026-07-30",
        acquisition_method="publisher download",
    )


def adoption_fixture(tmp_path: Path, *, with_provenance=True, authority=False, pack_id=None):
    remote = make_item(tmp_path, "remote", b"payload")
    local = make_item(tmp_path, "local", b"payload")
    local_library = FakeLibrary(tmp_path, [local])
    snapshot = {
        "author": "A. Engineer",
        "publisher": "Maker Press",
        "license_status": "manufacturer reference",
        "source_published_at": "2024-05-01",
        "acquired_at": "2026-07-30",
        "acquisition_method": "publisher download",
        "source_library_imported_at": "2026-07-30T10:00:00Z",
    }
    member = {
        "item_id": remote.item_id,
        "title": remote.title,
        "source": remote.source,
        "source_uri": remote.source_uri,
        "trust_class": remote.trust_class,
        "media_type": remote.media_type,
        "language": remote.language,
        "sha256": remote.sha256,
        "payload_bytes": Path(remote.storage_path).stat().st_size,
        "version_label": remote.version_label,
        "lifecycle_state": remote.lifecycle_state,
        "stale_after": None,
        "supersedes_item_id": None,
        "superseded_by_item_id": None,
        "rights_note": remote.rights_note,
        "tags": list(remote.tags),
    }
    if with_provenance:
        member["source_provenance"] = snapshot
    seed = {"schema": "velours_library.knowledge_pack.v1", "name": "Workshop", "version": "1", "description": None, "members": [member]}
    canonical = json.dumps(seed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    actual_pack_id = "kpack_" + hashlib.sha256(canonical).hexdigest()[:24]
    manifest = dict(seed, pack_id=actual_pack_id)
    record_pack_id = pack_id if pack_id is not None else actual_pack_id
    adoption = {
        "schema": "velours_library.pack_adoption.v1",
        "adoption_id": "adopt_demo",
        "candidate_id": "pcand_demo",
        "pack_id": record_pack_id,
        "pack_name": "Workshop",
        "pack_version": "1",
        "manifest_sha256": "f" * 64,
        "local_trust": "unknown",
        "authority_granted": authority,
        "canonical_receipt": False,
        "items": [{
            "local_item_id": local.item_id,
            "local_candidate_id": "cand_local",
            "local_trust_class": "unknown",
            "adoption_tag": "velour-adoption:demo",
            "remote_item_id": remote.item_id,
            "sha256": remote.sha256,
        }],
    }
    adoption_mgr = FakeAdoption({"adopt_demo": adoption})
    intake_mgr = FakeIntake({"pcand_demo": {"manifest": manifest}})
    prov = SourceProvenanceManager(tmp_path, library=local_library, adoption=adoption_mgr, intake=intake_mgr)
    return prov, local_library, adoption, manifest


def test_01_set_and_inspect(tmp_path):
    item = make_item(tmp_path)
    prov, _ = manager(tmp_path, item)
    created = set_full(prov)
    assert prov.inspect(item.item_id) == created
    assert created.authority_granted is False and created.canonical_receipt is False


def test_02_source_library_import_time_defaults_from_item(tmp_path):
    item = make_item(tmp_path, imported_at="2026-08-01T12:34:56Z")
    prov, _ = manager(tmp_path, item)
    assert prov.set(item.item_id, author="A").source_library_imported_at == item.imported_at


def test_03_sidecar_is_bound_to_item_and_hash(tmp_path):
    item = make_item(tmp_path)
    prov, _ = manager(tmp_path, item)
    rec = set_full(prov)
    assert rec.item_id == item.item_id and rec.sha256 == item.sha256


def test_04_hash_drift_is_rejected(tmp_path):
    item = make_item(tmp_path)
    prov, library = manager(tmp_path, item)
    set_full(prov)
    library.items[item.item_id] = replace(item, sha256="0" * 64)
    with pytest.raises(RuntimeError):
        prov.inspect(item.item_id)


def test_05_temporal_fields_require_iso8601(tmp_path):
    item = make_item(tmp_path)
    prov, _ = manager(tmp_path, item)
    with pytest.raises(ValueError):
        prov.set(item.item_id, source_published_at="sometime last spring")


def test_06_snapshot_refuses_authority_fields():
    with pytest.raises(ValueError):
        validate_source_provenance_snapshot({"author": "A", "authority_granted": True})


def test_07_snapshot_refuses_unknown_fields():
    with pytest.raises(ValueError):
        validate_source_provenance_snapshot({"author": "A", "favorite_color": "red"})


def test_08_merge_preserves_existing_fields(tmp_path):
    item = make_item(tmp_path)
    prov, _ = manager(tmp_path, item)
    prov.set(item.item_id, author="A", publisher="P")
    updated = prov.set(item.item_id, license_status="reference")
    assert updated.author == "A" and updated.publisher == "P" and updated.license_status == "reference"


def test_09_identical_set_is_idempotent(tmp_path):
    item = make_item(tmp_path)
    prov, _ = manager(tmp_path, item)
    first = set_full(prov)
    second = set_full(prov)
    assert first.recorded_at == second.recorded_at


def test_10_event_is_local_noncanonical_and_deduplicated(tmp_path):
    item = make_item(tmp_path)
    prov, _ = manager(tmp_path, item)
    set_full(prov); set_full(prov)
    rows = [json.loads(line) for line in prov.events_path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["canonical_receipt"] is False
    assert rows[0]["details"]["authority_granted"] is False


def test_11_list_records(tmp_path):
    a = make_item(tmp_path, "a")
    b = make_item(tmp_path, "b", b"beta")
    library = FakeLibrary(tmp_path, [a, b])
    prov = SourceProvenanceManager(tmp_path, library=library)
    prov.set("a", author="A"); prov.set("b", author="B")
    assert {row.item_id for row in prov.list_records()} == {"a", "b"}


def test_12_missing_snapshot_is_none(tmp_path):
    item = make_item(tmp_path)
    prov, _ = manager(tmp_path, item)
    assert prov.snapshot(item.item_id) is None


def test_13_pack_without_sidecar_keeps_source_provenance_optional(tmp_path):
    item = make_item(tmp_path)
    library = FakeLibrary(tmp_path, [item])
    manifest = KnowledgePackManager(library).build_manifest("Core", "1", [item.item_id])
    assert "source_provenance" not in manifest["members"][0]


def test_14_pack_snapshots_source_provenance(tmp_path):
    item = make_item(tmp_path)
    library = FakeLibrary(tmp_path, [item])
    prov = SourceProvenanceManager(tmp_path, library=library)
    set_full(prov)
    manifest = KnowledgePackManager(library).build_manifest("Core", "1", [item.item_id])
    assert manifest["members"][0]["source_provenance"]["author"] == "A. Engineer"


def test_15_pack_identity_with_provenance_is_deterministic(tmp_path):
    item = make_item(tmp_path)
    library = FakeLibrary(tmp_path, [item])
    set_full(SourceProvenanceManager(tmp_path, library=library))
    packs = KnowledgePackManager(library)
    assert packs.build_manifest("Core", "1", [item.item_id]) == packs.build_manifest("Core", "1", [item.item_id])


def test_16_new_provenance_changes_future_pack_identity(tmp_path):
    item = make_item(tmp_path)
    library = FakeLibrary(tmp_path, [item])
    prov = SourceProvenanceManager(tmp_path, library=library)
    prov.set(item.item_id, author="A")
    first = KnowledgePackManager(library).build_manifest("Core", "1", [item.item_id])
    prov.set(item.item_id, publisher="P")
    second = KnowledgePackManager(library).build_manifest("Core", "1", [item.item_id])
    assert first["pack_id"] != second["pack_id"]


def test_17_live_provenance_drift_is_warning_not_manifest_rewrite(tmp_path):
    item = make_item(tmp_path)
    library = FakeLibrary(tmp_path, [item])
    prov = SourceProvenanceManager(tmp_path, library=library)
    prov.set(item.item_id, author="A")
    packs = KnowledgePackManager(library)
    manifest = packs.build_manifest("Core", "1", [item.item_id])
    frozen = dict(manifest["members"][0]["source_provenance"])
    prov.set(item.item_id, publisher="P")
    result = packs.verify_against_library(manifest)
    assert result["valid"] is True
    assert "member_source_provenance_drift:%s" % item.item_id in result["warnings"]
    assert manifest["members"][0]["source_provenance"] == frozen


def test_18_malformed_source_provenance_invalidates_manifest(tmp_path):
    item = make_item(tmp_path)
    library = FakeLibrary(tmp_path, [item])
    packs = KnowledgePackManager(library)
    manifest = packs.build_manifest("Core", "1", [item.item_id])
    manifest["members"][0]["source_provenance"] = {"authority_granted": True}
    # Recompute identity so validation failure is specifically provenance, not only pack ID.
    seed = {k: v for k, v in manifest.items() if k != "pack_id"}
    manifest["pack_id"] = "kpack_" + hashlib.sha256(json.dumps(seed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()[:24]
    result = packs.verify_manifest(manifest)
    assert not result["valid"] and any("invalid_member_source_provenance" in error for error in result["errors"])


def test_19_export_with_provenance_verifies_offline(tmp_path):
    item = make_item(tmp_path)
    library = FakeLibrary(tmp_path, [item])
    set_full(SourceProvenanceManager(tmp_path, library=library))
    packs = KnowledgePackManager(library)
    out = packs.export(packs.build_manifest("Core", "1", [item.item_id]), tmp_path / "bundle")
    assert KnowledgePackManager.verify_export(out)["valid"] is True


def test_20_import_adoption_restores_provenance(tmp_path):
    prov, _, _, _ = adoption_fixture(tmp_path)
    restored = prov.import_adoption("adopt_demo")
    assert len(restored) == 1 and restored[0].author == "A. Engineer"


def test_21_import_binds_to_fresh_local_identity(tmp_path):
    prov, _, _, _ = adoption_fixture(tmp_path)
    restored = prov.import_adoption("adopt_demo")[0]
    assert restored.item_id == "local" and restored.origin_adoption_id == "adopt_demo"


def test_22_import_adoption_is_idempotent(tmp_path):
    prov, _, _, _ = adoption_fixture(tmp_path)
    first = prov.import_adoption("adopt_demo")[0]
    second = prov.import_adoption("adopt_demo")[0]
    assert first.recorded_at == second.recorded_at
    rows = [json.loads(line) for line in prov.events_path.read_text().splitlines()]
    assert len(rows) == 1


def test_23_import_skips_members_without_source_provenance(tmp_path):
    prov, _, _, _ = adoption_fixture(tmp_path, with_provenance=False)
    assert prov.import_adoption("adopt_demo") == []


def test_24_import_refuses_authority_bearing_adoption(tmp_path):
    prov, _, _, _ = adoption_fixture(tmp_path, authority=True)
    with pytest.raises(ValueError):
        prov.import_adoption("adopt_demo")


def test_25_import_refuses_pack_identity_drift(tmp_path):
    prov, _, _, _ = adoption_fixture(tmp_path, pack_id="kpack_" + "0" * 24)
    with pytest.raises(RuntimeError):
        prov.import_adoption("adopt_demo")


def test_26_import_refuses_local_payload_identity_drift(tmp_path):
    prov, library, _, _ = adoption_fixture(tmp_path)
    local = library.items["local"]
    library.items["local"] = replace(local, sha256="0" * 64)
    with pytest.raises(RuntimeError):
        prov.import_adoption("adopt_demo")


def test_27_existing_adoption_gate_accepts_optional_source_provenance(tmp_path):
    item = make_item(tmp_path)
    member = {
        "item_id": item.item_id,
        "title": item.title,
        "source": item.source,
        "media_type": item.media_type,
        "sha256": item.sha256,
        "source_provenance": {"author": "A"},
    }
    assert PackAdoptionManager._member_blockers(member, 0) == []
