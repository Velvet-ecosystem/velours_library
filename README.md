# Velour's Library

Velour's Library is Velvet's canonical shared, local-first, provenance-aware knowledge archive. Cyberdeck, vehicle, home, forge, Founder, and future bodies may consume it without inheriting one another's hardware, UI, or deployment assumptions.

## Core principles

- Local first.
- Provenance before confidence.
- Preserve the source.
- Trust is graded.
- Retrieval is not belief.
- Receipts matter.
- Knowledge is modular.
- Models are optional.

## Guarded ingestion

```bash
velour --root ./library-data stage ./incoming/manual.md --title "Workshop Manual" --source manufacturer --trust primary
velour --root ./library-data candidates --state staged
velour --root ./library-data publish <candidate-id>
```

`add` is a convenience path for trusted/local material, but it still stages and validates before publication. Staged material never appears in normal retrieval.

## Retrieval evidence

```bash
velour --root ./library-data search "pulley alignment"
velour --root ./library-data evidence "pulley alignment"
velour --root ./library-data reindex
```

Search results carry source identity, trust class, canonical hash, deterministic chunk identity, retrieval method, and location. Text uses line ranges. PDFs preserve page locations when PDF extraction is available. `evidence` emits a machine-readable, reference-only evidence bundle and does not create a canonical Velvet receipt.

## Storage layers

```text
incoming/      quarantined acquisition candidates
archive/       canonical content-addressed source material
catalog/       SQLite metadata, provenance, lifecycle state
indexes/       rebuildable extracted text and retrieval chunks
packs/         curated portable knowledge collections
receipts/      local library lifecycle evidence
docs/          doctrine and contracts
```

Velour is the librarian, not the oracle. She keeps the evidence, where it came from, what happened to it, and where a retrieved passage lives. Velvet remains responsible for reasoning with what comes off the shelves.
