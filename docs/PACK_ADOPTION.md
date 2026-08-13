# Knowledge Pack Adoption

Pack adoption is the target-side transition from an approved intake cartridge to locally owned library records. It is deliberately separate from intake approval and from authority.

```text
verified external bundle
    -> intake approval
    -> adoption plan
    -> local staged candidate
    -> local publication
    -> local verification
    -> adoption record + local evidence
```

## Local identity

Every adopted member receives a fresh local library item ID. The source node's item ID remains provenance in the adoption record and is never reused as local identity.

The local catalog defaults adopted material to trust class `unknown`. A caller may choose another valid local trust class only as an explicit local policy decision. Remote trust labels, tags, freshness deadlines, lifecycle state, and supersession links are preserved in origin metadata but are not automatically promoted into local policy.

Remote title, source, source URI, media type, language, rights note, version label, payload hash, and lineage metadata remain traceable through `origin_for()`.

## Recovery

Adoption uses a durable installation journal. Each member goes through the ordinary local `stage -> publish -> verify` path and receives internal adoption tags. If adoption fails before the completed record is written, recovery rejects adoption-tagged staged candidates and removes adoption-tagged published items.

A completed adoption record is the durable completion marker. If writing the noncanonical adoption evidence event fails after the record is durable, the library is not rolled back. A retry verifies the local items, writes the missing event idempotently, and clears the stale journal.

## Authority boundary

Adoption grants no Runtime, Court, executor, shell, network, CAN, relay, or physical-control authority. Imported source-node receipts are not accepted as local receipts. Adoption evidence is explicitly local and noncanonical:

```json
{
  "canonical_receipt": false,
  "receipt_scope": "velours_library_pack_adoption_local_evidence"
}
```

Integrity answers whether the transported bytes match the pack. Adoption answers whether this node accepted local copies. Neither answers whether a claim is true or whether an action is authorized.

## Current pack-v1 provenance limit

Pack v1 does not yet snapshot the source library's original acquisition timestamp or publication timestamp. Adoption does not invent those dates. A later pack-format extension may carry them as optional provenance fields without changing the authority boundary above.
