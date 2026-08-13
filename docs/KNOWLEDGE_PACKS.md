# Knowledge Packs

Knowledge packs are governed, portable collections of library material. A pack manifest describes the collection, source snapshots, versions, lifecycle metadata, and integrity hashes while payload bytes travel through content-addressed objects.

Example domains:

```text
automotive/
  can/
  obd2/
  hyundai/
  heavy-truck/
  electrical/
electronics/
  datasheets/
  microcontrollers/
  sensors/
  radio/
fabrication/
  cnc/
  3d-printing/
  machining/
  welding/
computing/
  linux/
  python/
  networking/
  github/
science/
maps/
medical-reference/
velvet-research/
```

## Transport and adoption

The current portable path is:

`build -> export -> verify -> intake quarantine -> approve -> adopt -> register`

Transport integrity never grants execution authority. An adopted member receives a fresh local item identity and an explicit local trust decision while remote trust, tags, freshness, and revision lineage remain provenance unless local policy deliberately promotes them.

## Pack lifecycle

After adoption, local pack revisions use:

`installed -> active -> stale / superseded -> removed`

Only one revision may be active per pack family. Pack-family identity is case-insensitive, and a successor must already be adopted and registered before it can replace the active revision.

Supersession updates the predecessor state, successor state, and family active pointer in one atomic registry-file replacement. An interrupted update leaves the previously valid active revision usable.

`active` means preferred knowledge-pack revision only. It does not grant Runtime, Court, executor, shell, network, vehicle, or physical-control authority.

Removal is logical and preserves adoption records, local library items, and canonical archive evidence.

## Portable updates

A home or connected node may acquire and validate updates, produce a checksummed bundle, and move it to a vehicle or isolated node without requiring that target to access the Internet directly.

Future work can add delta packs and cryptographic signing. Signing remains separate until key ownership, rotation, revocation, and trust policy are deliberately defined.
