import json
from pathlib import Path

from velours_library import Library
from velours_library.snapshot import LibrarySnapshotManager


def test_snapshot_identity_is_deterministic_for_same_catalog(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("needle", encoding="utf-8")
    library = Library(tmp_path / "lib"); library.add(source, title="Manual", source="maker")
    manager = LibrarySnapshotManager(library)
    first = manager.create_payload(); second = manager.create_payload()
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["core"] == second["core"]


def test_snapshot_round_trip_and_compare(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("needle", encoding="utf-8")
    library = Library(tmp_path / "lib"); library.add(source, title="Manual", source="maker")
    manager = LibrarySnapshotManager(library)
    path, payload = manager.write()
    assert path.is_file() and manager.inspect(path)["valid"] is True
    report = manager.compare(path)
    assert report["snapshot_id"] == payload["snapshot_id"] and report["drift"] is False


def test_snapshot_detects_catalog_drift(tmp_path: Path):
    first = tmp_path / "a.txt"; first.write_text("a", encoding="utf-8")
    second = tmp_path / "b.txt"; second.write_text("b", encoding="utf-8")
    library = Library(tmp_path / "lib"); library.add(first, title="A", source="maker")
    manager = LibrarySnapshotManager(library); path, _ = manager.write()
    added = library.add(second, title="B", source="maker")
    report = manager.compare(path)
    assert report["drift"] is True and report["added_item_ids"] == [added.item_id]


def test_snapshot_self_identity_detects_metadata_tampering(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("a", encoding="utf-8")
    library = Library(tmp_path / "lib"); library.add(source, title="A", source="maker")
    manager = LibrarySnapshotManager(library); path, _ = manager.write()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["core"]["items"][0]["title"] = "changed"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert manager.inspect(path)["valid"] is False
