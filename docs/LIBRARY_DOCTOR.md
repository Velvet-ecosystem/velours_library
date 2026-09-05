# Library doctor

`velour-doctor` is a read-only integrity audit for a deployed Velour Library.

It exists for the boring but important question that appears after months of use: **are the shelves still actually consistent?**

```bash
velour-doctor --root /srv/velvet/library
```

The audit checks:

- every cataloged canonical archive payload exists
- canonical payload SHA-256 still matches the catalog identity
- every staged candidate still has its quarantine payload
- staged candidate SHA-256 still matches
- cataloged extracted-text paths still exist
- unreferenced canonical archive objects
- unreferenced extracted text
- unreferenced incoming/quarantine files
- shared canonical payload groups
- stale/freshness-expired source inventory

The doctor never deletes, repairs, publishes, rejects, reindexes, or changes trust.

A healthy report may still contain warnings. For example, duplicate payload groups are legitimate when the same source bytes have different provenance records, and an orphan derivative is a cleanup clue rather than proof that canonical evidence is corrupt.

Errors indicate broken evidence invariants such as missing or checksum-mismatched canonical bytes.

For a faster structural pass that does not read every payload:

```bash
velour-doctor --root /srv/velvet/library --no-hash
```

That mode cannot detect byte-level corruption.

The doctor's JSON output is explicitly marked read-only, reference-only, noncanonical, and authority-free. Repair actions remain separate operator decisions so an audit cannot quietly turn into destructive cleanup.
