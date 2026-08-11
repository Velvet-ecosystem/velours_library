# Velour's Library

Velour's Library is Velvet's local-first, provenance-aware knowledge archive: a governed place to ingest, index, preserve, verify, and retrieve trusted offline knowledge.

The library is the canonical shared knowledge-library layer for the Velvet ecosystem. Cyberdeck, vehicle, home, forge, Founder, and future bodies may consume it without inheriting one another's hardware, UI, or deployment assumptions.

The library is designed for documents, manuals, datasets, research, reference material, maps, selected web captures, source repositories, and owner-provided material. It separates raw evidence from searchable indexes and curated knowledge packs so Velvet can retrieve useful context without treating every stored source as equally trustworthy.

## Core principles

- **Local first** — the library remains useful without an Internet connection.
- **Provenance before confidence** — every item should retain where it came from, when it was acquired, and what transformed it.
- **Preserve the source** — normalized or indexed derivatives should not replace the original evidence.
- **Trust is graded** — a primary manufacturer datasheet is not equivalent to an anonymous forum post.
- **Retrieval is not belief** — finding a source does not make its claims true.
- **Receipts matter** — ingestion, transformation, indexing, update, and removal should be auditable.
- **Knowledge is modular** — collections can be installed, updated, verified, removed, and transported as governed knowledge packs.
- **Models are optional** — the archive and retrieval system must remain useful independently of any particular generative model.

## Phase 1 commands

```bash
velour --root ./library-data add ./incoming/manual.md \
  --title "Workshop Manual" \
  --source "manufacturer" \
  --trust primary \
  --tag automotive

velour --root ./library-data search "pulley alignment"
velour --root ./library-data inspect <item-or-sha-prefix>
velour --root ./library-data verify <item-or-sha-prefix>
velour --root ./library-data remove <item-or-sha-prefix>
```

The first implementation uses a SQLite catalog, SHA-256 content-addressed archive objects, inert text extraction, optional PDF extraction, offline full-text search, provenance-aware results, and local lifecycle evidence records.

## Planned library layers

```text
incoming/      material awaiting validation and ingestion
archive/       canonical preserved source material
catalog/       metadata, manifests, provenance, licensing, checksums
indexes/       full-text, semantic, entity and relationship indexes
packs/         curated portable knowledge collections
receipts/      ingestion and lifecycle evidence
tools/         import, validation, indexing and maintenance utilities
docs/          architecture, doctrine and schemas
```

Large datasets and copyrighted source material should generally not be committed directly to Git. This repository defines the library system, schemas, manifests, tooling, and governed structure that manage those materials on Velvet's storage.

## Velour's role

Velour is the librarian, not the oracle. She preserves evidence, records provenance, ranks source quality, retrieves relevant material, and tells Velvet what she found. Final reasoning remains separate from storage and retrieval.

> Keep the books. Keep the receipts. Keep the difference between evidence and truth.
