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

## Portable knowledge packs

Knowledge packs freeze a curated set of library items into a deterministic manifest that snapshots provenance, trust, version, lifecycle state, and canonical payload hashes. Pack identity is derived from canonical JSON rather than a random identifier.

Exports use content-addressed `objects/sha256/` storage, deduplicate identical payloads, verify every object before publication, and can be checked again on an isolated machine without the source library. Lifecycle changes after pack creation appear as drift warnings; they do not silently rewrite historical manifests.

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
```

Remote trust labels, tags, stale deadlines, lifecycle state, and revision links remain origin metadata unless a separate local policy deliberately promotes them. Adoption events are noncanonical local evidence, imported source-node receipts are not accepted as local receipts, and adoption grants no Runtime, Court, executor, shell, network, CAN, relay, or physical-control authority.
