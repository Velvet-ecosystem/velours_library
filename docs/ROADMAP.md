# Roadmap

The Library remains useful at every phase. No semantic, generative, network, or model feature may become a prerequisite for basic cataloging, verification, full-text retrieval, or source preservation.

## Phase 0 — Foundation — complete

- repository boundaries
- provenance and trust doctrine
- source manifest schema
- knowledge-pack concept
- retrieval contract
- security posture

## Phase 1 — Local library — complete

- SQLite catalog
- SHA-256 canonical identity
- filesystem-backed archive
- quarantine / review / publication boundary
- text and Markdown ingestion
- PDF text extraction
- deterministic full-text search
- local lifecycle evidence
- CLI for add, inspect, search, verify and remove
- guarded recursive bulk intake
- rerun-safe batch duplicate handling
- HTML, DOCX, ODT and EPUB text extraction
- opt-in OCR fallback for scanned PDFs and raster images
- metadata sidecars and conservative embedded metadata probing
- automatic staged drop-folder example

## Phase 2 — Rich retrieval — active

Complete:

- deterministic chunk/location mapping
- page-aware PDF evidence
- bounded contiguous evidence windows
- query evidence bundles
- source lifecycle and version/freshness warnings

Still optional/future:

- semantic index as an accelerator, never a dependency
- entity and relationship extraction
- explicit source-conflict surfacing
- richer diagram/table structure extraction

## Phase 3 — Portable knowledge packs — substantially complete

- deterministic pack manifests
- hash-addressed transfer objects
- pack quarantine/intake
- target-side governed adoption
- local pack lifecycle and revision switching
- portable source provenance
- drift warnings

Future trust-layer work:

- optional cryptographic signing/authorship contracts
- richer dependency/version rules where real packs require them

## Phase 4 — Multi-node library — active

Complete:

- Velour-hosted authenticated read-only retrieval service
- Home-to-mobile retrieval contract
- bounded evidence responses
- local-first failure posture

Still future:

- cache and replication policy
- automated pack placement by node/storage capacity
- multi-node health/resource-abuse testing
- bounded transfer contract for raw documents or packs where justified

## Phase 5 — Archive operations — active

Complete:

- 1 TB local vault layout and mount fail-closed posture
- retention classes and reserve thresholds
- cross-media vault catalog
- read-only Library integrity doctor
- deterministic catalog snapshots and drift comparison
- external Kiwix/ZIM reference shelf for very large offline collections

Still future:

- federated evidence adapter that can merge Kiwix search into normal Velour retrieval without disguising source-engine provenance
- bounded local audio/video transcription pipeline
- richer image/diagram understanding derivatives
- backup-copy orchestration and restore rehearsal tooling
- optional semantic index implementation after an appropriate local embedding model is selected
