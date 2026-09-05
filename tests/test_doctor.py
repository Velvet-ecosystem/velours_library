from pathlib import Path

from velours_library import Library
from velours_library.doctor import LibraryDoctor


def test_doctor_reports_healthy_library(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("needle", encoding="utf-8")
    library = Library(tmp_path / "lib"); library.add(source, title="Manual", source="maker")
    report = LibraryDoctor(library).audit()
    assert report["healthy"] is True
    assert report["errors"] == 0 and report["items"] == 1
    assert report["read_only"] is True and report["authority"] == "none"


def test_doctor_detects_archive_tampering(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("original", encoding="utf-8")
    library = Library(tmp_path / "lib"); item = library.add(source, title="Manual", source="maker")
    Path(item.storage_path).write_text("tampered", encoding="utf-8")
    report = LibraryDoctor(library).audit()
    assert report["healthy"] is False
    assert any(finding["code"] == "archive_checksum_mismatch" for finding in report["findings"])


def test_doctor_detects_missing_staged_payload(tmp_path: Path):
    source = tmp_path / "candidate.txt"; source.write_text("candidate", encoding="utf-8")
    library = Library(tmp_path / "lib"); candidate = library.stage(source, title="Candidate", source="owner")
    Path(candidate.staged_path).unlink()
    report = LibraryDoctor(library).audit()
    assert report["healthy"] is False
    assert any(finding["code"] == "staged_payload_missing" for finding in report["findings"])


def test_doctor_reports_orphan_derivatives_as_warning(tmp_path: Path):
    library = Library(tmp_path / "lib")
    orphan = library.text_dir / "orphan.txt"; orphan.write_text("orphan", encoding="utf-8")
    report = LibraryDoctor(library).audit()
    assert report["healthy"] is True
    assert report["warnings"] == 1
    assert report["findings"][0]["code"] == "orphan_extracted_text"


def test_doctor_reports_shared_payloads_without_calling_them_corruption(tmp_path: Path):
    source = tmp_path / "same.txt"; source.write_text("same", encoding="utf-8")
    library = Library(tmp_path / "lib")
    a = library.add(source, title="A", source="one")
    b = library.add(source, title="B", source="two")
    report = LibraryDoctor(library).audit()
    assert report["healthy"] is True
    assert report["duplicate_payload_groups"] == [{"sha256": a.sha256, "item_ids": sorted([a.item_id, b.item_id]), "references": 2}]
