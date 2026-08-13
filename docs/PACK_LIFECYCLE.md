# Knowledge Pack Lifecycle

Pack lifecycle is local policy for already-adopted knowledge packs. It chooses which locally verified revision is preferred without changing the adoption record, source provenance, item identity, trust decision, canonical bytes, or any execution authority.

```text
approved cartridge
    -> adopted locally
    -> installed
    -> active
    -> stale / superseded
    -> removed (logical)
```

## States

- `installed` — adopted and registered, but not preferred.
- `active` — preferred revision for this local library.
- `stale` — retained and known, but no longer preferred because local policy considers it outdated.
- `superseded` — replaced by another registered revision of the same pack family.
- `removed` — logically removed from lifecycle selection while provenance, adopted items, and canonical archive evidence remain.

Only one revision may be `active` inside a pack family.

## Pack families

Pack-family identity is derived from a normalized, case-insensitive pack name. All revisions of the same named pack share one atomic family registry file. This avoids splitting the predecessor state, successor state, and active pointer across independently writable files.

A revision registry entry binds to immutable adoption facts:

- adoption ID
- pack ID
- pack version
- manifest SHA-256
- explicit local trust decision
- local item IDs

Lifecycle verification fails if those adoption facts drift.

## Atomic replacement

A successor must already be fully adopted and registered. `supersede(old, new)` requires the predecessor to be active and the successor to be installed. One atomic family-file replacement then:

1. marks the predecessor `superseded`;
2. links it to the successor;
3. marks the successor `active`;
4. links it back to the predecessor; and
5. moves the family active pointer to the successor.

If the atomic write fails, the previously valid family file remains authoritative and the old revision stays active.

## Evidence recovery

Lifecycle events are deterministic local evidence with:

```json
{
  "canonical_receipt": false,
  "receipt_scope": "velours_library_pack_lifecycle_local_evidence"
}
```

State is written before its evidence append. If evidence writing fails after a durable state transition, retrying the same operation recognizes the completed state and repairs the missing event exactly once.

## Authority boundary

`active` means preferred **knowledge-pack revision** only. Pack lifecycle grants no Runtime, Court, executor, shell, network, CAN, relay, vehicle, medical, or physical-control authority.

Lifecycle removal is deliberately logical. It does not delete adoption records, local library items, or canonical archive objects.
