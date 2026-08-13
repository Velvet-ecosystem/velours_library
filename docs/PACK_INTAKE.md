# Knowledge Pack Intake

Portable knowledge packs cross a trust boundary when they arrive on another Velvet node. Integrity is checked before the bundle enters Velour's quarantine, and approval remains distinct from installation or authority.

```text
external bundle
    -> preflight limits
    -> manifest + payload verification
    -> canonical quarantine copy
    -> verify again
    -> approved-for-adoption
    -> later installation/adoption layer
```

Only `manifest.json` and the SHA-256 addressed payload objects named by that manifest are copied into quarantine. Stray files are ignored. Symlink payloads are refused. Configurable limits bound manifest size, member count, and total payload bytes before full verification proceeds.

A staged pack has state `verified`. Approval re-runs preflight and bundle verification and confirms the manifest hash and `pack_id` have not changed since intake. `approved` means only that the cartridge is eligible for a later adoption step. It does not install library items, grant execution authority, or convert source trust metadata into truth.

Rejection deletes quarantined payload bytes while preserving the candidate metadata and local noncanonical intake event. Intake events use `velours_library_pack_intake_local_evidence` and explicitly set `canonical_receipt` to false.

The actual adoption/install operation is intentionally a separate slice so that local item identity, pack-origin provenance, lifecycle mapping, rollback, and collision behavior can be designed and tested without weakening the quarantine boundary.
