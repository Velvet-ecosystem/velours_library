# Knowledge Pack Format

A Velour knowledge pack is a deterministic manifest plus optional content-addressed payload objects. It is a transport format for governed reference material, not an authority grant.

## Identity

The manifest schema is `velours_library.knowledge_pack.v1`. `pack_id` is derived from the canonical JSON content of the manifest excluding the `pack_id` field itself. Canonical JSON uses sorted keys and compact separators, so the same name, version, description, and ordered member snapshots produce the same identity.

Members snapshot provenance and lifecycle metadata together with the canonical SHA-256 payload identity. A later lifecycle or source-provenance change does not rewrite an existing pack manifest. Verification against a live library reports that difference as drift.

## Optional source provenance

A member may carry a `source_provenance` object containing author, publisher, license or usage status, source publication date, acquisition date/method, and the source library's original import timestamp.

The object is optional so older knowledge-pack v1 manifests remain valid. When present, it is included in canonical pack identity and travels as evidence metadata only. It does not promote trust class or grant authority.

## Export layout

```text
<pack>/
  manifest.json
  objects/
    sha256/
      ab/
        ab...full-sha256
```

Duplicate members that reference identical bytes share one exported object. Exports are assembled in a temporary sibling directory, verified, and atomically renamed into place. An existing destination is never overwritten.

## Verification

Pack verification checks manifest identity and every payload hash. It also validates any optional `source_provenance` object and rejects authority-bearing fields inside that object. A copied pack can verify itself without access to the source library or the Internet.

Checksums provide integrity, not signer identity. Cryptographic signing is intentionally outside this slice. Signing requires explicit key ownership, rotation, revocation, and trust policy rather than an ad hoc private key hidden inside the library implementation.
