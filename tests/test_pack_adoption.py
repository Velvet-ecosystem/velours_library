import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from velours_library import Library
from velours_library.pack_adoption import PackAdoptionManager
from velours_library.pack_intake import PackIntakeManager


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def make_bundle(root: Path, members=None):
    root.mkdir(parents=True, exist_ok=True)
    if members is None:
        members = [
            {
                "item_id": "remote_manual_1",
                "title": "Workshop Manual",
                "source": "Maker",
                "source_uri": "https://example.invalid/manual",
                "trust_class": "primary",
                "media_type": "text/markdown",
                "language": "en",
                "data": b"# Manual\nneedle torque reference\n",
                "rights_note": "redistributable example",
                "version_label": "1.0",
                "lifecycle_state": "superseded",
                "stale_after": "2020-01-01",
                "supersedes_item_id": "remote_old",
                "superseded_by_item_id": "remote_new",
                "tags": ["automotive", "maker"],
            }
        ]
    manifest_members = []
    for raw_member in members:
        raw = dict(raw_member)
        data = raw.pop("data")
        sha = hashlib.sha256(data).hexdigest()
        payload = root / "objects" / "sha256" / sha[:2] / sha
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_bytes(data)
        raw["sha256"] = sha
        raw["payload_bytes"] = len(data)
        manifest_members.append(raw)
    seed = {
        "schema": "velours_library.knowledge_pack.v1",
        "name": "Demo Pack",
        "version": "1.0",
        "description": None,
        "members": manifest_members,
    }
    manifest = dict(seed)
    manifest["pack_id"] = "kpack_%s" % hashlib.sha256(_canonical_bytes(seed)).hexdigest()[:24]
    (root / "manifest.json").write_bytes(_canonical_bytes(manifest) + b"\n")
    return manifest


def setup_manager(tmp_path: Path, *, approve=True, members=None):
    bundle = tmp_path / "bundle"
    manifest = make_bundle(bundle, members)
    root = tmp_path / "library"
    library = Library(root)
    intake = PackIntakeManager(root)
    candidate = intake.stage(bundle, source_label="garage node")
    if approve:
        candidate = intake.approve(candidate.candidate_id)
    manager = PackAdoptionManager(root, library=library, intake=intake)
    return manager, library, intake, candidate, manifest


def _delete_adoption_tag(library, item_id, tag):
    if hasattr(library, "_connect"):
        with library._connect() as conn:
            conn.execute("DELETE FROM tags WHERE item_id=? AND tag=?", (item_id, tag))
        return
    old = library.items[item_id]
    library.items[item_id] = replace(old, tags=tuple(x for x in old.tags if x != tag))


def _change_local_trust(library, item_id, trust):
    if hasattr(library, "_connect"):
        with library._connect() as conn:
            conn.execute("UPDATE items SET trust_class=? WHERE item_id=?", (trust, item_id))
        return
    library.items[item_id] = replace(library.items[item_id], trust_class=trust)


def test_plan_requires_approved_candidate(tmp_path):
    manager, _, _, candidate, _ = setup_manager(tmp_path, approve=False)
    plan = manager.plan(candidate.candidate_id)
    assert plan["eligible"] is False
    assert "pack_candidate_not_approved" in plan["blockers"]


def test_plan_defaults_local_trust_unknown_without_remote_policy_promotion(tmp_path):
    manager, _, _, candidate, _ = setup_manager(tmp_path)
    plan = manager.plan(candidate.candidate_id)
    member = plan["members"][0]
    assert plan["eligible"] is True and plan["local_trust"] == "unknown"
    assert member["remote_trust_class"] == "primary"
    assert member["local_trust_class"] == "unknown"
    assert member["remote_tags_promoted"] is False
    assert member["remote_freshness_promoted"] is False
    assert member["remote_lineage_promoted"] is False


def test_adopt_creates_fresh_local_identity_and_explicit_local_trust(tmp_path):
    manager, library, _, candidate, manifest = setup_manager(tmp_path)
    record = manager.adopt(candidate.candidate_id, local_trust="secondary")
    adopted = record["items"][0]
    item = library.inspect(adopted["local_item_id"])
    assert item.item_id != manifest["members"][0]["item_id"]
    assert item.item_id.startswith("lib_")
    assert item.trust_class == "secondary"
    assert adopted["local_candidate_id"].startswith("cand_")


def test_remote_tags_freshness_and_lineage_remain_origin_only(tmp_path):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    record = manager.adopt(candidate.candidate_id)
    item = library.inspect(record["items"][0]["local_item_id"])
    origin = manager.origin_for(item.item_id)
    assert item.tags == (origin["adoption_tag"],)
    assert item.lifecycle_state == "active"
    assert item.stale_after is None and item.supersedes_item_id is None
    assert origin["remote_tags"] == ["automotive", "maker"]
    assert origin["remote_lifecycle_state"] == "superseded"
    assert origin["remote_stale_after"] == "2020-01-01"
    assert origin["remote_supersedes_item_id"] == "remote_old"
    assert origin["remote_superseded_by_item_id"] == "remote_new"


def test_source_metadata_and_version_remain_traceable(tmp_path):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    record = manager.adopt(candidate.candidate_id)
    item = library.inspect(record["items"][0]["local_item_id"])
    origin = manager.origin_for(item.item_id)
    assert item.title == "Workshop Manual" and item.source == "Maker"
    assert item.version_label == "1.0"
    assert origin["source_uri"] == "https://example.invalid/manual"
    assert origin["rights_note"] == "redistributable example"


def test_media_type_maps_to_safe_ingestion_suffix():
    assert PackAdoptionManager._suffix_for_media("text/markdown") == ".md"
    assert PackAdoptionManager._suffix_for_media("application/pdf") == ".pdf"
    assert PackAdoptionManager._suffix_for_media("text/x-custom") == ".txt"
    assert PackAdoptionManager._suffix_for_media("application/octet-stream") == ".bin"


def test_adoption_is_idempotent_and_event_is_not_duplicated(tmp_path):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    first = manager.adopt(candidate.candidate_id)
    second = manager.adopt(candidate.candidate_id)
    assert first == second and len(library.list_items()) == 1
    events = [json.loads(line) for line in manager.events_path.read_text().splitlines()]
    assert len([event for event in events if event["action"] == "complete"]) == 1


def test_idempotent_retry_refuses_local_trust_change(tmp_path):
    manager, _, _, candidate, _ = setup_manager(tmp_path)
    manager.adopt(candidate.candidate_id, local_trust="unknown")
    with pytest.raises(ValueError, match="different local trust"):
        manager.adopt(candidate.candidate_id, local_trust="primary")


def test_retry_detects_missing_adoption_tag(tmp_path):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    record = manager.adopt(candidate.candidate_id)
    adopted = record["items"][0]
    _delete_adoption_tag(library, adopted["local_item_id"], adopted["adoption_tag"])
    with pytest.raises(RuntimeError, match="provenance tag missing"):
        manager.adopt(candidate.candidate_id)


def test_retry_detects_local_trust_drift(tmp_path):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    record = manager.adopt(candidate.candidate_id)
    _change_local_trust(library, record["items"][0]["local_item_id"], "primary")
    with pytest.raises(RuntimeError, match="local trust drift"):
        manager.adopt(candidate.candidate_id)


def test_pack_payload_mutation_after_approval_blocks_before_local_write(tmp_path):
    manager, library, _, candidate, manifest = setup_manager(tmp_path)
    sha = manifest["members"][0]["sha256"]
    payload = Path(candidate.staged_path) / "objects" / "sha256" / sha[:2] / sha
    payload.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="adoption blocked"):
        manager.adopt(candidate.candidate_id)
    assert library.list_items() == []
    assert library.list_candidates("staged") == []


def test_crash_after_stage_rolls_back_orphan_candidate(tmp_path, monkeypatch):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    original = library.stage
    def crash_after_stage(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected stage crash")
    monkeypatch.setattr(library, "stage", crash_after_stage)
    with pytest.raises(RuntimeError, match="stage crash"):
        manager.adopt(candidate.candidate_id)
    assert library.list_items() == []
    assert library.list_candidates("staged") == []


def test_crash_after_publish_rolls_back_published_item(tmp_path, monkeypatch):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    original = library.publish
    def crash_after_publish(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected publish crash")
    monkeypatch.setattr(library, "publish", crash_after_publish)
    with pytest.raises(RuntimeError, match="publish crash"):
        manager.adopt(candidate.candidate_id)
    assert library.list_items() == []


def test_completed_record_survives_evidence_write_failure_and_retry_repairs(tmp_path, monkeypatch):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    original = manager._append_event
    failed = {"done": False}
    def fail_once(event_id, action, details):
        if action == "complete" and not failed["done"]:
            failed["done"] = True
            raise OSError("disk hiccup")
        return original(event_id, action, details)
    monkeypatch.setattr(manager, "_append_event", fail_once)
    with pytest.raises(OSError, match="disk hiccup"):
        manager.adopt(candidate.candidate_id)
    assert len(library.list_items()) == 1
    monkeypatch.setattr(manager, "_append_event", original)
    record = manager.adopt(candidate.candidate_id)
    assert len(library.list_items()) == 1
    assert record["items"][0]["local_item_id"] == library.list_items()[0].item_id
    events = [json.loads(line) for line in manager.events_path.read_text().splitlines()]
    assert len([event for event in events if event["action"] == "complete"]) == 1


def test_recover_rolls_back_incomplete_journal_by_tag_and_hash(tmp_path):
    manager, library, _, candidate, manifest = setup_manager(tmp_path)
    adoption_id = manager._adoption_id(candidate.candidate_id, candidate.pack_id)
    remote_id = manifest["members"][0]["item_id"]
    tag = manager._adoption_tag(candidate.candidate_id, candidate.pack_id, remote_id)
    sha = manifest["members"][0]["sha256"]
    payload = Path(candidate.staged_path) / "objects" / "sha256" / sha[:2] / sha
    library.stage(payload, title="x", source="x", tags=[tag])
    journal = {
        "adoption_id": adoption_id,
        "candidate_id": candidate.candidate_id,
        "pack_id": candidate.pack_id,
        "members": [{"adoption_tag": tag, "sha256": sha}],
    }
    manager._write_json_atomic(manager._journal_path(adoption_id), journal)
    assert manager.recover() == [adoption_id]
    assert library.list_candidates("staged") == []
    assert not manager._journal_path(adoption_id).exists()


def test_recover_completed_record_repairs_event_without_rollback(tmp_path):
    manager, library, _, candidate, _ = setup_manager(tmp_path)
    record = manager.adopt(candidate.candidate_id)
    adoption_id = record["adoption_id"]
    manager.events_path.unlink()
    manager._write_json_atomic(
        manager._journal_path(adoption_id),
        {"adoption_id": adoption_id, "candidate_id": candidate.candidate_id, "pack_id": candidate.pack_id, "members": []},
    )
    assert manager.recover() == [adoption_id]
    assert len(library.list_items()) == 1
    assert any(json.loads(line)["action"] == "complete" for line in manager.events_path.read_text().splitlines())


def test_duplicate_payload_members_receive_separate_local_ids(tmp_path):
    data = b"same bytes"
    members = [
        {"item_id": "a", "title": "A", "source": "Maker", "trust_class": "primary", "media_type": "text/plain", "language": "en", "data": data, "tags": []},
        {"item_id": "b", "title": "B", "source": "Maker", "trust_class": "secondary", "media_type": "text/plain", "language": "en", "data": data, "tags": []},
    ]
    manager, library, _, candidate, _ = setup_manager(tmp_path, members=members)
    record = manager.adopt(candidate.candidate_id)
    ids = [item["local_item_id"] for item in record["items"]]
    assert len(set(ids)) == 2
    assert library.inspect(ids[0]).sha256 == library.inspect(ids[1]).sha256


def test_origin_missing_raises_keyerror(tmp_path):
    manager, _, _, _, _ = setup_manager(tmp_path)
    with pytest.raises(KeyError):
        manager.origin_for("lib_missing")


def test_invalid_member_metadata_blocks_adoption(tmp_path):
    members = [
        {"item_id": "x", "title": "", "source": "Maker", "trust_class": "primary", "media_type": "text/plain", "language": "en", "data": b"x", "tags": []}
    ]
    manager, library, _, candidate, _ = setup_manager(tmp_path, members=members)
    plan = manager.plan(candidate.candidate_id)
    assert plan["eligible"] is False
    assert any("missing_title" in blocker for blocker in plan["blockers"])
    with pytest.raises(ValueError, match="adoption blocked"):
        manager.adopt(candidate.candidate_id)
    assert library.list_items() == []


def test_unknown_local_trust_class_is_rejected(tmp_path):
    manager, _, _, candidate, _ = setup_manager(tmp_path)
    with pytest.raises(ValueError, match="unknown local trust class"):
        manager.plan(candidate.candidate_id, local_trust="definitely-trust-me")


def test_events_are_noncanonical_and_grant_no_authority(tmp_path):
    manager, _, _, candidate, _ = setup_manager(tmp_path)
    record = manager.adopt(candidate.candidate_id)
    assert record["canonical_receipt"] is False and record["authority_granted"] is False
    event = json.loads(manager.events_path.read_text().splitlines()[-1])
    assert event["canonical_receipt"] is False
    assert event["receipt_scope"] == "velours_library_pack_adoption_local_evidence"
    assert event["details"]["authority_granted"] is False
    assert event["details"]["imported_receipts"] is False
