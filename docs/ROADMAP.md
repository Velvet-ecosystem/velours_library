# Roadmap

## Phase 0 — Foundation

- repository boundaries
- provenance and trust doctrine
- source manifest schema
- knowledge-pack concept
- retrieval contract
- security posture

## Phase 1 — Minimal local library

- SQLite catalog
- SHA-256 canonical identity
- filesystem-backed archive
- text and Markdown ingestion
- PDF text extraction
- deterministic full-text search
- ingestion receipts
- CLI for add, inspect, search, verify and remove

## Phase 2 — Rich retrieval

- chunk/location mapping
- semantic index as an optional accelerator
- entity and relationship extraction
- source conflict surfacing
- stale/version detection
- query evidence bundles

## Phase 3 — Portable knowledge packs

- pack manifest schema
- dependency/version rules
- atomic install/update/rollback
- signed or checksummed transfer bundles
- connected-node acquisition to offline-node delivery

## Phase 4 — Multi-node library

- Velour-hosted retrieval service
- cache and replication policy
- pack placement by node/storage capacity
- degraded/offline operation
- library health events and resource-abuse tests

The architecture should remain useful at every phase. No later semantic or generative feature may become a prerequisite for basic cataloging, verification, or full-text retrieval.
