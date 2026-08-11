# Phase 1: Minimal Local Library

The first functional slice is intentionally model-independent and runtime-independent.

## Included

- SQLite catalog and provenance records
- content-addressed SHA-256 archive objects
- separate provenance records for duplicate bytes
- inert text extraction for common text formats
- optional PDF text extraction through `pypdf`
- SQLite FTS5 search when available, with deterministic local fallback
- source and trust-class metadata in retrieval results
- integrity verification
- safe removal that preserves shared payloads while references remain
- local library lifecycle evidence records
- CLI commands: `add`, `inspect`, `search`, `verify`, `remove`, and `list`

## Receipt boundary

Files under the library's `receipts/` data directory are local evidence records. They deliberately carry:

```json
{
  "canonical_receipt": false,
  "receipt_scope": "velours_library_local_evidence"
}
```

They do not replace the canonical contracts owned by `velvet-receipts`. A later adapter may translate approved library lifecycle evidence into the ecosystem receipt format.

## Archive identity

Canonical payload bytes are stored by SHA-256 rather than original filename:

```text
archive/sha256/ab/abcdef...
```

Multiple catalog items may reference the same payload while preserving different acquisition sources, trust classes, tags, or other provenance.

## Compatibility posture

Core functionality uses the Python standard library and targets Python 3.8 or newer. PDF extraction is optional and uses `pypdf>=4,<6`, keeping the core library usable even when PDF support is not installed.
