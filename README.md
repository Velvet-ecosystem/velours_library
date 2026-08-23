# Velour's Library

Velour's Library is Velvet's canonical shared, local-first, provenance-aware knowledge archive. It preserves source evidence, keeps acquisition and transformation history, and returns retrieval results with enough provenance for another Velvet component to reason about them without treating retrieval as belief.

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

```bash
velour --root ./library-data stage ./incoming/manual.md \
  --title "Workshop Manual" --source manufacturer --trust primary \
  --version 1.4 --stale-after 2027-01-01
velour --root ./library-data candidates --state staged
velour --root ./library-data publish <candidate-id>
```

`add` is a convenience path for trusted/local material, but it still stages and validates before publication. Staged material never appears in normal retrieval.

## Approved remote acquisition

`velour-acquire` is the governed delivery path from approved HTTP(S) sources to the existing staging dock. It is intentionally single-resource and policy-driven. It does not crawl sites, publish candidates, or turn downloaded material into trusted truth.

```bash
velour-acquire \
  --root ./library-data \
  --policy ./local/acquisition-policy.json \
  check https://manuals.example.org/products/widget.pdf

velour-acquire \
  --root ./library-data \
  --policy ./local/acquisition-policy.json \
  fetch https://manuals.example.org/products/widget.pdf \
  --title "Widget Service Manual" \
  --tag workshop \
  --version 2.1
```

Successful acquisition produces a normal `staged` candidate plus an acquisition audit record. Publication remains a separate explicit action through the existing Library workflow.

Source policies use exact origins and optional path prefixes, can constrain content types and byte counts, reject private/local addresses by default, re-check redirects, and may pin an expected SHA-256 when a source publishes one. Real source policies are deployment-local configuration rather than repository defaults.

See `docs/APPROVED_SOURCE_ACQUISITION.md` and `schemas/acquisition_policy.schema.json`.

## Retrieval evidence

```bash
velour --root ./library-data search "pulley alignment"
velour --root ./library-data evidence "pulley alignment"
velour --root ./library-data reindex
```

Search results carry source identity, trust class, canonical hash, deterministic chunk identity, retrieval method, and location. Text uses line ranges. PDFs preserve page locations when PDF extraction is available. Evidence bundles are reference-only and do not create canonical Velvet receipts.

## Source lifecycle

```bash
velour --root ./library-data add ./manual-1.4.md \
  --title "Workshop Manual" --source manufacturer --trust primary \
  --version 1.4 --supersedes <old-item-id>
velour --root ./library-data lifecycle <item-id>
velour --root ./library-data stale <item-id>
velour --root ./library-data refresh <item-id> --stale-after 2027-08-01
velour --root ./library-data stale-list
```

Velour preserves superseded revisions instead of deleting history. Retrieval carries lifecycle state, replacement links, freshness deadlines, and explicit warnings. Relevance scoring is not silently altered by recency or version state.

Velour is the librarian, not the oracle. She keeps the evidence, where it came from, what happened to it, which revision replaced it, and where a retrieved passage lives. Velvet remains responsible for reasoning with what comes off the shelves.

## Source provenance

Source provenance sidecars add richer source history without rewriting the core catalog. Records are bound to the local `item_id` and canonical SHA-256 payload identity.

```bash
velour-provenance --root ./library-data set <item-id> \
  --author "A. Engineer" \
  --publisher "Maker Press" \
  --license-status "manufacturer reference" \
  --published-at 2024-05-01 \
  --acquired-at 2026-07-30 \
  --acquisition-method "publisher download"

velour-provenance --root ./library-data inspect <item-id>
```

Source provenance may record author, publisher, license or usage status, source publication date, acquisition date/method, and the source library's original import time. These fields are evidence metadata only. They do not change trust class, truth status, or execution authority.

## Portable knowledge packs

Knowledge packs freeze a curated set of library items into a deterministic manifest that snapshots provenance, trust, version, lifecycle state, and canonical payload hashes. Pack identity is derived from canonical JSON rather than a random identifier.

Exports use content-addressed `objects/sha256/` storage, deduplicate identical payloads, verify every object before publication, and can be checked again on an isolated machine without the source library. Lifecycle or provenance changes after pack creation appear as drift warnings; they do not silently rewrite historical manifests.

New manifests may include an optional `source_provenance` object for each member. Older v1 manifests without that object remain valid.

Checksums establish integrity, not authorship. Cryptographic signing remains a separate future trust-layer decision.

## Pack intake quarantine

Transferred packs enter a separate verified quarantine before any target library adopts their contents. Intake preflights size/member limits, refuses symlink payloads, verifies the exported bundle, reconstructs only the canonical manifest and hash-addressed payload set, and verifies the quarantined copy again.

```bash
velour-pack-intake --root ./library-data stage ./cartridge \
  --source-label "garage node"
velour-pack-intake --root ./library-data list --state verified
velour-pack-intake --root ./library-data approve <pack-candidate-id>
```

`approved` means eligible for a later adoption step. It does not install the pack, grant authority, or turn its trust metadata into truth.

## Pack adoption

Approved cartridges may be adopted into the local catalog through a separate target-side transaction. Adoption re-verifies the quarantined pack, creates fresh local item identities, uses the ordinary local `stage -> publish -> verify` path, and records pack-origin provenance without importing the sending node's authority decisions.

```bash
velour-pack-adopt --root ./library-data plan <pack-candidate-id>
velour-pack-adopt --root ./library-data adopt <pack-candidate-id> --trust unknown
velour-pack-adopt --root ./library-data origin <local-item-id>
velour-provenance --root ./library-data import-adoption <adoption-id>
```

Remote trust labels, tags, stale deadlines, lifecycle state, and revision links remain origin metadata unless a separate local policy deliberately promotes them. Rich source provenance can be restored from the quarantined pack onto the fresh local item identities after adoption. Imported source-node receipts are not accepted as local receipts, and adoption or provenance import grants no Runtime, Court, executor, shell, network, CAN, relay, or physical-control authority.

## Pack lifecycle and updates

Adopted pack revisions are registered into an explicit local lifecycle before one becomes the preferred revision for that library.

```bash
velour-pack-lifecycle --root ./library-data register <adoption-id>
velour-pack-lifecycle --root ./library-data activate <adoption-id>
velour-pack-lifecycle --root ./library-data supersede <old-adoption-id> <new-adoption-id>
velour-pack-lifecycle --root ./library-data current "Workshop"
```

Lifecycle states are `installed`, `active`, `stale`, `superseded`, and `removed`. Only one revision may be active per pack family. A successor must already be fully adopted and registered before it can replace another revision, and the predecessor state, successor state, and family active pointer switch in one atomic family-file update.

`active` means preferred **knowledge-pack revision** only. It grants no execution authority. Lifecycle removal is logical and preserves adoption records, local items, and canonical archive bytes.
