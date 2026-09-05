from pathlib import Path

from velours_library import Library
from velours_library.evidence_window import expand_evidence_bundle


PRINCIPLES = """# Velour's Library

Intro text.

## Core principles

- Local first.
- Provenance before confidence.
- Preserve the source.
- Trust is graded.
- Retrieval is not belief.
- Receipts matter.
- Knowledge is modular.
- Models are optional.
- Currency is metadata, not truth.

## Guarded ingestion

Publication remains explicit.
"""


def _library_with_source(tmp_path: Path, text: str, *, chunk_lines: int = 40) -> Library:
    source = tmp_path / "source.md"
    source.write_text(text, encoding="utf-8")
    library = Library(tmp_path / "library", chunk_lines=chunk_lines)
    library.add(
        source,
        title="Velour Library README",
        source="test fixture",
        trust_class="primary",
    )
    return library


def test_markdown_heading_query_expands_to_complete_bounded_section(tmp_path: Path):
    library = _library_with_source(tmp_path, PRINCIPLES)
    original = library.evidence_bundle("core principles", 5)
    expanded = expand_evidence_bundle(library, "core principles", original)

    first = expanded["results"][0]
    assert first["windowed"] is True
    assert first["window_truncated"] is False
    assert first["snippet"].startswith("## Core principles")
    assert "- Currency is metadata, not truth." in first["snippet"]
    assert "## Guarded ingestion" not in first["snippet"]
    assert len(first["snippet"]) <= 480
    assert 1 <= len(first["chunk_ids"]) <= 3
    assert first["chunk_id"] in first["chunk_ids"]
    assert expanded["reference_only"] is True
    assert expanded["canonical_receipt"] is False


def test_window_can_cross_adjacent_chunks_but_never_crosses_item(tmp_path: Path):
    library = _library_with_source(tmp_path, PRINCIPLES, chunk_lines=4)
    expanded = expand_evidence_bundle(
        library,
        "core principles",
        library.evidence_bundle("core principles", 5),
        max_chunks=3,
    )

    first = expanded["results"][0]
    assert first["windowed"] is True
    assert 1 < len(first["chunk_ids"]) <= 3
    assert first["item_id"]
    with library._connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT item_id FROM chunks WHERE chunk_id IN (%s)"
            % ",".join("?" for _ in first["chunk_ids"]),
            tuple(first["chunk_ids"]),
        ).fetchall()
    assert {row["item_id"] for row in rows} == {first["item_id"]}


def test_window_respects_character_bound(tmp_path: Path):
    long_section = "## Core principles\n\n" + "\n".join(
        "- Principle %02d carries exact source wording for bounded retrieval." % index
        for index in range(30)
    ) + "\n\n## Next section\n"
    library = _library_with_source(tmp_path, long_section, chunk_lines=8)
    expanded = expand_evidence_bundle(
        library,
        "core principles",
        library.evidence_bundle("core principles", 5),
        max_characters=240,
    )
    first = expanded["results"][0]
    assert first["windowed"] is True
    assert first["window_truncated"] is True
    assert len(first["snippet"]) <= 240
    assert len(first["chunk_ids"]) <= 3


def test_metadata_only_result_is_left_unchanged(tmp_path: Path):
    source = tmp_path / "radio.bin"
    source.write_bytes(b"\x00\x01\x02")
    library = Library(tmp_path / "library")
    library.add(
        source,
        title="Radio Datasheet Binary",
        source="maker",
        trust_class="primary",
        tags=("radio",),
    )
    original = library.evidence_bundle("radio", 5)
    expanded = expand_evidence_bundle(library, "radio", original)
    assert expanded["results"][0] == original["results"][0]


def test_canonical_sha_mismatch_fails_soft_without_expansion(tmp_path: Path):
    library = _library_with_source(tmp_path, PRINCIPLES)
    bundle = library.evidence_bundle("core principles", 5)
    tampered = dict(bundle)
    result = dict(bundle["results"][0])
    result["sha256"] = "0" * 64
    tampered["results"] = [result]

    expanded = expand_evidence_bundle(library, "core principles", tampered)
    assert expanded["results"][0] == result
    assert "windowed" not in expanded["results"][0]
