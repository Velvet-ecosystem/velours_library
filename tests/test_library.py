import json
from pathlib import Path

from velours_library import Library


def test_add_search_inspect_and_verify(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("# Alternator\nInspect pulley alignment before replacing the belt.", encoding="utf-8")
    library = Library(tmp_path / "library")
    item = library.add(source, title="Alternator Notes", source="owner field notes", trust_class="owner", tags=["repair", "tiburon"])

    inspected = library.inspect(item.item_id)
    assert inspected.title == "Alternator Notes"
    assert inspected.tags == ("repair", "tiburon")
    assert library.verify(item.item_id) is True
    results = library.search("pulley alignment")
    assert results and results[0].item_id == item.item_id
    assert results[0].trust_class == "owner"


def test_duplicate_bytes_keep_separate_provenance(tmp_path: Path) -> None:
    source = tmp_path / "same.txt"
    source.write_text("shared bytes", encoding="utf-8")
    library = Library(tmp_path / "library")
    first = library.add(source, title="Factory Copy", source="manufacturer", trust_class="primary")
    second = library.add(source, title="Owner Copy", source="Mister", trust_class="owner")

    assert first.item_id != second.item_id
    assert first.sha256 == second.sha256
    assert first.storage_path == second.storage_path
    assert len(library.list_items()) == 2


def test_search_returns_source_and_trust(tmp_path: Path) -> None:
    source = tmp_path / "manual.txt"
    source.write_text("battery charging voltage reference", encoding="utf-8")
    library = Library(tmp_path / "library")
    item = library.add(source, title="Battery Manual", source="Example Manufacturer", trust_class="primary", tags=["battery"])

    result = library.search("battery")[0]
    assert result.item_id == item.item_id
    assert result.source == "Example Manufacturer"
    assert result.trust_class == "primary"


def test_verify_detects_tampering(tmp_path: Path) -> None:
    source = tmp_path / "guide.txt"
    source.write_text("original", encoding="utf-8")
    library = Library(tmp_path / "library")
    item = library.add(source, title="Guide", source="local")
    Path(item.storage_path).write_text("changed", encoding="utf-8")
    assert library.verify(item.item_id) is False


def test_remove_preserves_shared_payload_until_last_reference(tmp_path: Path) -> None:
    source = tmp_path / "same.txt"
    source.write_text("shared", encoding="utf-8")
    library = Library(tmp_path / "library")
    first = library.add(source, title="One", source="a")
    second = library.add(source, title="Two", source="b")
    payload = Path(first.storage_path)

    library.remove(first.item_id)
    assert payload.exists()
    assert library.inspect(second.item_id).item_id == second.item_id
    library.remove(second.item_id)
    assert not payload.exists()


def test_inspect_accepts_unique_sha_prefix(tmp_path: Path) -> None:
    source = tmp_path / "item.txt"
    source.write_text("unique prefix data", encoding="utf-8")
    library = Library(tmp_path / "library")
    item = library.add(source, title="Prefix", source="local")
    assert library.inspect(item.sha256[:12]).item_id == item.item_id


def test_library_events_are_explicitly_noncanonical_receipts(tmp_path: Path) -> None:
    source = tmp_path / "item.txt"
    source.write_text("receipt evidence", encoding="utf-8")
    library = Library(tmp_path / "library")
    item = library.add(source, title="Receipt", source="local")
    assert library.verify(item.item_id) is True

    events = [json.loads(line) for line in library.receipt_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) >= 2
    assert all(event["canonical_receipt"] is False for event in events)
    assert all(event["receipt_scope"] == "velours_library_local_evidence" for event in events)
