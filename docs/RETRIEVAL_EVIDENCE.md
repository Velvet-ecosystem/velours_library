# Retrieval Evidence

Velour returns evidence records rather than anonymous snippets.

Every full-text retrieval result carries the source item identity, source and trust class, canonical SHA-256, deterministic chunk identity, retrieval method, and a location inside the extracted source. Plain-text sources use line ranges. PDF extraction preserves page boundaries and reports page numbers.

A retrieval result remains reference material. It is not a belief, Court decision, capability grant, Runtime state, identity claim, or canonical Receipt.

`velour evidence <query>` returns a machine-readable evidence bundle with `reference_only: true` and `canonical_receipt: false`.

Chunk IDs are deterministic from canonical source hash, source location, and chunk content hash. Rebuilding an unchanged index therefore recreates the same chunk identities. Indexes remain disposable derivatives; the archive and provenance catalog remain durable.

Items with no extracted text can still be retrieved through title/source/tag metadata, but those results explicitly use `retrieval_method: metadata` and `location.kind: metadata` rather than inventing a source-text location.
