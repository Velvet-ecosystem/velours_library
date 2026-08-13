# Cyberdeck Relationship

`velours_library` is the canonical shared knowledge-library layer for the Velvet ecosystem.

The earlier Cyberdeck offline-library work is an important ancestor and proving ground. It established useful behaviour for file import, checksum verification, offline search, text extraction, and the rule that retrieved knowledge is reference material rather than authority.

Going forward:

- shared archive, catalog, provenance, indexing, retrieval, and knowledge-pack capabilities belong here;
- Cyberdeck may consume this library through a narrow adapter or package dependency;
- Cyberdeck-specific UI, hardware, field workflow, storage-placement, and deployment behaviour remain in `velvet-cyberdeck`;
- useful generic Cyberdeck code may be migrated or reimplemented here after overlap review;
- no consumer should be required to install or understand Cyberdeck in order to use Velour's Library.

This keeps Cyberdeck useful as a portable body while preventing the ecosystem-wide library from inheriting one surface's assumptions.
