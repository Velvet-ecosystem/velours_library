import json
from pathlib import Path

import pytest

from velours_library import Library


def test_add_search_inspect_and_verify(tmp_path: Path):
    source = tmp_path / "n.md"; source.write_text("# Alternator\nInspect pulley alignment.", encoding="utf-8")
    library = Library(tmp_path / "lib"); item = library.add(source, title="Alternator Notes", source="owner", trust_class="owner", tags=["repair"])
    assert library.inspect(item.item_id).title == "Alternator Notes"; assert library.verify(item.item_id); assert library.search("pulley")[0].item_id == item.item_id


def test_duplicate_bytes_keep_separate_provenance(tmp_path: Path):
    source = tmp_path / "same.txt"; source.write_text("shared bytes")
    library = Library(tmp_path / "lib"); first = library.add(source, title="A", source="a"); second = library.add(source, title="B", source="b")
    assert first.sha256 == second.sha256 and first.item_id != second.item_id and first.storage_path == second.storage_path


def test_search_returns_source_and_trust(tmp_path: Path):
    source = tmp_path / "m.txt"; source.write_text("battery charging voltage")
    library = Library(tmp_path / "lib"); item = library.add(source, title="Battery", source="Maker", trust_class="primary")
    result = library.search("battery")[0]; assert result.item_id == item.item_id; assert (result.source, result.trust_class) == ("Maker", "primary")


def test_verify_detects_tampering(tmp_path: Path):
    source = tmp_path / "g.txt"; source.write_text("original")
    library = Library(tmp_path / "lib"); item = library.add(source, title="G", source="local"); Path(item.storage_path).write_text("changed")
    assert not library.verify(item.item_id)


def test_remove_preserves_shared_payload_until_last_reference(tmp_path: Path):
    source = tmp_path / "same.txt"; source.write_text("shared")
    library = Library(tmp_path / "lib"); first = library.add(source, title="A", source="a"); second = library.add(source, title="B", source="b"); payload = Path(first.storage_path)
    library.remove(first.item_id); assert payload.exists(); library.remove(second.item_id); assert not payload.exists()


def test_inspect_accepts_unique_sha_prefix(tmp_path: Path):
    source = tmp_path / "x.txt"; source.write_text("unique")
    library = Library(tmp_path / "lib"); item = library.add(source, title="X", source="local"); assert library.inspect(item.sha256[:12]).item_id == item.item_id


def test_library_events_are_noncanonical(tmp_path: Path):
    source = tmp_path / "x.txt"; source.write_text("evidence")
    library = Library(tmp_path / "lib"); item = library.add(source, title="X", source="local"); library.verify(item.item_id)
    events = [json.loads(line) for line in library.receipt_path.read_text().splitlines()]; assert events and all(event["canonical_receipt"] is False for event in events)


def test_staged_candidate_is_not_searchable_until_publish(tmp_path: Path):
    source = tmp_path / "secret.txt"; source.write_text("quarantine telescope")
    library = Library(tmp_path / "lib"); candidate = library.stage(source, title="Staged", source="local")
    assert library.search("telescope") == []; item = library.publish(candidate.candidate_id); assert library.search("telescope")[0].item_id == item.item_id


def test_publish_refuses_tampered_staged_payload(tmp_path: Path):
    source = tmp_path / "x.txt"; source.write_text("original")
    library = Library(tmp_path / "lib"); candidate = library.stage(source, title="X", source="local"); Path(candidate.staged_path).write_text("tampered")
    with pytest.raises(RuntimeError): library.publish(candidate.candidate_id)


def test_reject_keeps_audit_record_but_removes_payload(tmp_path: Path):
    source = tmp_path / "x.txt"; source.write_text("candidate")
    library = Library(tmp_path / "lib"); candidate = library.stage(source, title="X", source="local"); staged = Path(candidate.staged_path)
    rejected = library.reject(candidate.candidate_id, "bad source"); assert rejected.state == "rejected" and rejected.rejection_reason == "bad source" and not staged.exists(); assert library.inspect_candidate(candidate.candidate_id).state == "rejected"


def test_file_size_limit_blocks_stage(tmp_path: Path):
    source = tmp_path / "big.bin"; source.write_bytes(b"x" * 11); library = Library(tmp_path / "lib", max_file_bytes=10)
    with pytest.raises(ValueError): library.stage(source, title="Big", source="local")


def test_large_text_can_archive_without_extraction(tmp_path: Path):
    source = tmp_path / "large.txt"; source.write_text("alpha beta gamma"); library = Library(tmp_path / "lib", max_extract_bytes=4)
    item = library.add(source, title="Large", source="local"); assert Path(item.storage_path).exists() and item.extracted_text_path is None


def test_evidence_has_stable_chunk_and_line_location(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("one\ntwo\nneedle phrase\nfour\nfive\n", encoding="utf-8")
    library = Library(tmp_path / "lib", chunk_lines=3); item = library.add(source, title="Manual", source="Maker", trust_class="primary")
    result = library.evidence("needle phrase")[0]
    assert result.item_id == item.item_id; assert result.chunk_id and result.location == {"kind": "lines", "start_line": 1, "end_line": 3}; assert result.sha256 == item.sha256


def test_reindex_reproduces_chunk_identity(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")
    library = Library(tmp_path / "lib", chunk_lines=2); item = library.add(source, title="Manual", source="Maker")
    before = [(r.chunk_id, r.location) for r in library.evidence("alpha")]; assert library.reindex(item.item_id) == 2; after = [(r.chunk_id, r.location) for r in library.evidence("alpha")]
    assert before == after


def test_evidence_bundle_is_reference_only_and_noncanonical(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("torque reference", encoding="utf-8")
    library = Library(tmp_path / "lib"); library.add(source, title="Torque", source="Maker", trust_class="primary")
    bundle = library.evidence_bundle("torque")
    assert bundle["reference_only"] is True and bundle["canonical_receipt"] is False; assert bundle["results"][0]["canonical_receipt"] is False


def test_pdf_chunk_locations_are_pages(tmp_path: Path):
    source = tmp_path / "fake.pdf"; source.write_bytes(b"%PDF-fake")
    library = Library(tmp_path / "lib")
    library._extract_pdf_pages = lambda path: ["page one needle", "page two"]  # type: ignore
    item = library.add(source, title="PDF Manual", source="Maker", trust_class="primary")
    result = library.evidence("needle")[0]
    assert item.media_type == "application/pdf"; assert result.location == {"kind": "page", "page": 1}


def test_metadata_only_item_is_still_retrievable(tmp_path: Path):
    source = tmp_path / "radio.bin"; source.write_bytes(b"\x00\x01\x02")
    library = Library(tmp_path / "lib"); item = library.add(source, title="Radio Datasheet Binary", source="Maker", trust_class="primary", tags=["radio"])
    result = library.evidence("radio")[0]
    assert result.item_id == item.item_id and result.chunk_id is None and result.retrieval_method == "metadata" and result.location == {"kind": "metadata"}
