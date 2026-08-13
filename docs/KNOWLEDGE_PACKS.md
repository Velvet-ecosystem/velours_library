# Knowledge Packs

Knowledge packs are governed, portable collections of library material. A pack is not necessarily a copy of every source file; it is a manifest describing the collection, required artifacts, indexes, versions and integrity information.

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

## Pack lifecycle

A future pack lifecycle should support:

`candidate -> validated -> installed -> active -> stale -> superseded -> removed`

Pack updates should be atomic where practical. An interrupted update must leave the previously valid pack usable.

## Portable updates

Knowledge packs are intended to support offline transfer. A home or connected node may acquire and validate updates, produce a signed or checksummed bundle, and move it to a vehicle or isolated node without requiring that target to access the Internet directly.
