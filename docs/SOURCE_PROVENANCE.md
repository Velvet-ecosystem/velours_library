# Source Provenance

Velour keeps richer source history in durable sidecars rather than expanding the core catalog every time a new provenance field is useful. Each sidecar is bound to a local library item by both `item_id` and canonical SHA-256 payload identity.

## Transferable fields

A source-provenance snapshot may carry:

- author
- publisher
- license or usage status
- source publication date
- acquisition date
- acquisition method
- the source library's original import timestamp

These fields describe where reference material came from. They do not change the local trust class, establish truth, import a Court decision, grant a capability, or authorize execution.

## Local sidecars

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

The sidecar is verified against the live catalog item before it is returned or packed. If the catalog item no longer has the SHA-256 identity recorded by the sidecar, provenance inspection fails rather than silently attaching old history to different bytes.

## Portable packs

Knowledge-pack v1 members may include an optional `source_provenance` object. It is part of the canonical manifest and therefore part of pack identity. Older v1 manifests without the object remain valid.

A later source-side provenance change does not rewrite a historical manifest. `verify_against_library()` reports provenance drift as a warning.

## Adoption restoration

Pack adoption deliberately creates fresh local item identities and does not import remote trust or authority. After adoption, richer source provenance may be restored separately:

```bash
velour-provenance --root ./library-data import-adoption <adoption-id>
```

The importer re-verifies the approved intake candidate, checks the pack identity against the adoption record, maps each remote member to its fresh local item, verifies matching payload hashes, and writes a new local sidecar bound to the local item identity.

This restoration is idempotent. It does not replace the adoption record or turn source-node receipts into local canonical receipts.

## Evidence boundary

Source-provenance events are local noncanonical evidence:

```json
{
  "canonical_receipt": false,
  "receipt_scope": "velours_library_source_provenance_local_evidence"
}
```

Source provenance cannot carry trust-class promotion, capability grants, execution permissions, Court decisions, or other authority-bearing fields.
