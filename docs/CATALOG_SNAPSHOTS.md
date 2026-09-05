# Catalog snapshots

Canonical archive bytes are the evidence, but the catalog is what remembers what those bytes mean.

`velour-snapshot` creates a deterministic metadata snapshot that can be stored with normal backups and used later to detect catalog drift or assist recovery.

```bash
velour-snapshot --root /srv/velvet/library create
```

The default destination is:

```text
catalog/snapshots/<snapshot-id>.json
```

The snapshot records published item metadata and, by default, candidate/quarantine metadata. It includes source labels, source URIs, trust classes, hashes, relative storage paths, tags, lifecycle state, version/freshness data, and revision links.

It does **not** embed canonical payload bytes and is not a substitute for backing up the archive itself.

## Deterministic identity

`generated_at` is deliberately excluded from snapshot identity. If the same logical catalog is snapshotted twice without changes, both snapshots have the same `snapshot_id`.

The identity is a SHA-256 over canonical JSON for the snapshot core.

Inspect a stored snapshot:

```bash
velour-snapshot --root /srv/velvet/library inspect catalog/snapshots/<id>.json
```

If metadata inside the snapshot is altered without recomputing its identity, inspection reports the mismatch.

## Drift comparison

Compare current published catalog state with an earlier snapshot:

```bash
velour-snapshot --root /srv/velvet/library compare catalog/snapshots/<id>.json
```

The report lists added, removed, and changed local item IDs.

This is inventory drift, not truth drift. It does not decide whether a changed source is better or worse.

## Backup relationship

A useful archive backup set includes at least:

- canonical `archive/sha256/` objects
- `catalog/library.sqlite3`
- source provenance sidecars and pack state
- local lifecycle evidence/receipts
- one or more catalog snapshots
- external ZIM inventories if the Kiwix shelf is used

Snapshots are intentionally metadata-only so they can be copied and compared cheaply even when the underlying archive is hundreds of gigabytes.

No restore command is automatic. Recovery that would recreate or replace catalog state remains an explicit operator procedure rather than letting a metadata file mutate Library truth by itself.
