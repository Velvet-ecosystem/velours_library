# Bulk document ingestion

`velour-ingest` is the loading dock for manuals, datasheets, books, exported web pages, office documents, scanned references, and other local source batches.

It deliberately feeds the existing guarded Library path:

```text
file / folder
  -> metadata probe
  -> duplicate check
  -> Library.stage()
  -> quarantine
  -> explicit review
  -> Library.publish()
  -> canonical SHA-256 archive
  -> extraction / chunks / search
```

The command does not create a second catalog, bypass source trust, or turn a downloaded document into truth.

## Safe default

Without `--publish`, every accepted file is staged only:

```bash
velour-ingest \
  --root /srv/velvet/library \
  ~/manual-drop \
  --source owner-import \
  --trust owner
```

Review candidates with the normal Library command:

```bash
velour --root /srv/velvet/library candidates --state staged
velour --root /srv/velvet/library publish <candidate-id>
```

For a batch that is already reviewed and intentionally trusted, publication can be explicit:

```bash
velour-ingest \
  --root /srv/velvet/library \
  ~/hyundai-manuals \
  --source Hyundai \
  --trust primary \
  --source-uri-base manufacturer://hyundai/manuals \
  --tag automotive \
  --tag tiburon \
  --publish
```

`--dry-run` performs discovery, metadata probing, hashing, and duplicate decisions without creating candidates or archive objects.

## Supported searchable formats

The richer document path supports:

- text and Markdown
- CSV, JSON, YAML, TOML, INI, logs
- normal text-bearing PDF
- scanned PDF through optional OCR
- HTML / XHTML
- DOCX
- ODT
- EPUB
- common raster images through optional OCR

Unsupported files may still be preserved as metadata-only candidates with `--all-files`.

The canonical source is never replaced by extracted text. HTML cleanup, office-document text, PDF text, and OCR output are disposable derivatives under the normal Library index tree.

## OCR posture

OCR is opt-in:

```bash
velour-ingest \
  --root /srv/velvet/library \
  ~/scanned-manuals \
  --source owner-import \
  --ocr
```

For sparse/scanned PDFs, Velour uses a locally installed `ocrmypdf` executable, writing only to temporary derivative files before normal text extraction. Canonical input bytes are not rewritten.

For standalone images, Velour uses a locally installed `tesseract` executable.

The commands are invoked with fixed argument lists rather than through a shell. If OCR was requested and the required executable is unavailable for a document that actually needs it, that file is reported as an error rather than silently pretending it became searchable.

OCR language defaults to English (`eng`) and can be changed, for example:

```bash
--ocr-language eng+fra
```

The corresponding Tesseract language packs must exist locally.

## Sidecar metadata

A file may have a sibling JSON sidecar named by appending `.velour.json` to the complete filename:

```text
2008-tiburon-service-manual.pdf
2008-tiburon-service-manual.pdf.velour.json
```

Example:

```json
{
  "title": "2008 Hyundai Tiburon Service Manual",
  "source": "Hyundai",
  "trust": "primary",
  "language": "en",
  "rights_note": "owner-supplied reference",
  "tags": ["automotive", "tiburon", "service-manual"],
  "version": "2008"
}
```

The schema is `schemas/ingest_sidecar.schema.json`.

Supported sidecar fields may override embedded metadata. Unknown fields fail that file instead of being ignored, which prevents spelling mistakes from silently losing provenance.

`"ignore": true` excludes a file from that batch.

## Embedded metadata

Where practical, Velour may read non-authoritative descriptive metadata such as a document title, author, language, or publisher from PDF, HTML, DOCX, ODT, or EPUB containers.

Embedded metadata does **not** choose trust class. Trust remains an explicit Library decision.

Licensing or rights are never guessed when absent.

## Repeat imports and duplicate bytes

The underlying Library intentionally allows multiple catalog items to reference identical canonical bytes because provenance may differ.

Bulk import adds an idempotence convenience: a rerun skips an object when SHA-256, source label, and source URI already match an existing non-rejected candidate/item.

Use `--keep-duplicates` when another provenance record is intentional.

## Batch source URIs

`--source-uri-base` lets a batch retain stable, non-secret relative identities without storing an operator's absolute filesystem paths.

Example:

```bash
--source-uri-base vault://manuals/tiburon
```

A file at `engine/torque.pdf` receives:

```text
vault://manuals/tiburon/engine/torque.pdf
```

Avoid putting secrets, credentials, or private tokens in source URIs.

## Large files

Normal Library size ceilings still apply. `velour-ingest` does not weaken them.

Very large reference archives such as Wikipedia ZIM files belong on the external Kiwix shelf rather than being copied into the canonical per-document archive. See `ZIM_REFERENCE_SHELF.md`.
