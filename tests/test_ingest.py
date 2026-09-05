import json
import zipfile
from pathlib import Path

from velours_library.ingest import BulkIngestor, DocumentLibrary, probe_metadata


def test_bulk_defaults_to_staged_quarantine(tmp_path: Path):
    incoming = tmp_path / "drop"; incoming.mkdir()
    (incoming / "manual.txt").write_text("needle workshop phrase", encoding="utf-8")
    library = DocumentLibrary(tmp_path / "lib")
    results = BulkIngestor(library, source="owner-import", trust_class="owner").ingest(incoming)
    assert [result.action for result in results] == ["staged"]
    assert library.search("needle") == []
    candidate = library.inspect_candidate(results[0].candidate_id)
    assert candidate.source == "owner-import" and candidate.trust_class == "owner"


def test_bulk_explicit_publish_uses_existing_library_path(tmp_path: Path):
    incoming = tmp_path / "drop"; incoming.mkdir()
    (incoming / "manual.txt").write_text("alternator pulley alignment", encoding="utf-8")
    library = DocumentLibrary(tmp_path / "lib")
    results = BulkIngestor(library, source="manufacturer", trust_class="primary").ingest(incoming, publish=True)
    assert results[0].action == "published"
    found = library.evidence("pulley")[0]
    assert found.item_id == results[0].item_id and found.trust_class == "primary"


def test_bulk_rerun_is_idempotent_for_same_source_and_uri(tmp_path: Path):
    incoming = tmp_path / "drop"; incoming.mkdir()
    (incoming / "manual.txt").write_text("same bytes", encoding="utf-8")
    library = DocumentLibrary(tmp_path / "lib")
    ingestor = BulkIngestor(library, source="maker", source_uri_base="vault://manuals")
    first = ingestor.ingest(incoming, publish=True)
    second = ingestor.ingest(incoming, publish=True)
    assert first[0].action == "published"
    assert second[0].action == "skipped" and second[0].reason == "already_present"
    assert len(library.list_items()) == 1


def test_bulk_can_keep_duplicate_provenance_when_explicit(tmp_path: Path):
    source = tmp_path / "manual.txt"; source.write_text("same bytes", encoding="utf-8")
    library = DocumentLibrary(tmp_path / "lib")
    ingestor = BulkIngestor(library, source="maker", keep_duplicates=True)
    assert ingestor.ingest(source, publish=True)[0].action == "published"
    assert ingestor.ingest(source, publish=True)[0].action == "published"
    assert len(library.list_items()) == 2


def test_sidecar_overrides_metadata_and_can_ignore(tmp_path: Path):
    source = tmp_path / "factory.txt"; source.write_text("manual", encoding="utf-8")
    sidecar = source.with_name(source.name + ".velour.json")
    sidecar.write_text(json.dumps({
        "title": "Factory Service Manual",
        "source": "Hyundai",
        "trust": "primary",
        "language": "en",
        "rights_note": "owner-supplied reference",
        "tags": ["vehicle", "tiburon"],
        "version": "2008",
    }), encoding="utf-8")
    metadata = probe_metadata(source, source="fallback")
    assert metadata.title == "Factory Service Manual"
    assert metadata.source == "Hyundai" and metadata.trust_class == "primary"
    assert metadata.version_label == "2008" and "vehicle" in metadata.tags
    sidecar.write_text(json.dumps({"ignore": True}), encoding="utf-8")
    assert probe_metadata(source, source="fallback").ignore is True


def test_html_is_extracted_without_scripts(tmp_path: Path):
    source = tmp_path / "page.html"
    source.write_text("<html><head><title>Relay Manual</title><script>scriptpoison</script></head><body><h1>Relay</h1><p>coil resistance needle</p></body></html>", encoding="utf-8")
    library = DocumentLibrary(tmp_path / "lib")
    item = library.add(source, title="Relay Manual", source="maker")
    assert library.evidence("resistance")[0].item_id == item.item_id
    assert library.search("scriptpoison") == []


def test_docx_text_is_extracted_with_standard_library_only(tmp_path: Path):
    source = tmp_path / "notes.docx"
    document_xml = """<?xml version='1.0' encoding='UTF-8'?>
    <w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
      <w:body><w:p><w:r><w:t>gearbox needle specification</w:t></w:r></w:p></w:body>
    </w:document>"""
    with zipfile.ZipFile(str(source), "w") as zf:
        zf.writestr("word/document.xml", document_xml)
    library = DocumentLibrary(tmp_path / "lib")
    item = library.add(source, title="Gearbox", source="owner")
    assert library.evidence("specification")[0].item_id == item.item_id


def test_sparse_pdf_uses_opt_in_ocr_and_keeps_page_locations(tmp_path: Path):
    source = tmp_path / "scan.pdf"; source.write_bytes(b"%PDF-fake")
    library = DocumentLibrary(tmp_path / "lib", ocr=True)
    library._extract_pdf_pages = lambda path: [""]  # type: ignore
    library._ocr_pdf_pages = lambda path: ["page one needle", "page two torque"]  # type: ignore
    item = library.add(source, title="Scanned Manual", source="maker")
    result = library.evidence("needle")[0]
    assert result.item_id == item.item_id and result.location == {"kind": "page", "page": 1}


def test_image_is_metadata_only_without_ocr(tmp_path: Path):
    source = tmp_path / "diagram.png"; source.write_bytes(b"not-a-real-png")
    library = DocumentLibrary(tmp_path / "lib", ocr=False)
    item = library.add(source, title="Wiring Diagram", source="owner", tags=["diagram"])
    result = library.evidence("diagram")[0]
    assert result.item_id == item.item_id and result.retrieval_method == "metadata"


def test_image_ocr_can_create_searchable_derivative(tmp_path: Path):
    source = tmp_path / "diagram.png"; source.write_bytes(b"not-a-real-png")
    library = DocumentLibrary(tmp_path / "lib", ocr=True)
    library._ocr_image = lambda path: "connector C14 needle pin 3"  # type: ignore
    item = library.add(source, title="Wiring Diagram", source="owner")
    assert library.evidence("connector")[0].item_id == item.item_id


def test_dry_run_does_not_create_candidates(tmp_path: Path):
    source = tmp_path / "manual.md"; source.write_text("dry run", encoding="utf-8")
    library = DocumentLibrary(tmp_path / "lib")
    result = BulkIngestor(library, source="owner").ingest(source, dry_run=True)[0]
    assert result.action == "planned_stage"
    assert library.list_candidates() == [] and library.list_items() == []


def test_unsupported_files_are_skipped_unless_all_files(tmp_path: Path):
    incoming = tmp_path / "drop"; incoming.mkdir()
    (incoming / "firmware.bin").write_bytes(b"binary")
    library = DocumentLibrary(tmp_path / "lib")
    assert BulkIngestor(library, source="owner").ingest(incoming) == []
    result = BulkIngestor(library, source="owner", all_files=True).ingest(incoming)[0]
    assert result.action == "staged"
