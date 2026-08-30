# Retrieval Contract

A library query should return evidence records, not anonymous text fragments.

Minimum conceptual result:

```yaml
query_id: q-...
result_id: r-...
item_id: source-item-id
snippet: relevant extracted text
source_title: Example Manual
trust_class: primary
canonical_hash: sha256:...
location:
  page: 42
  section: Fuel System
retrieval:
  method: full_text
  score: 0.91
warnings: []
```

## Rules

- Preserve source identity through retrieval.
- Expose the location within the source where practical.
- Separate retrieval score from source trust.
- Do not interpret vector similarity as confidence in truth.
- Generated summaries must point back to their supporting source records.
- When conflicting sources are found, return the conflict rather than silently averaging it away.
- Stale or superseded material should remain discoverable when historically useful, but carry an explicit state warning.

## Remote retrieval boundary

The same evidence contract may be served read-only to approved remote Velvet-compatible nodes. Network delivery must not weaken the semantics above.

Remote retrieval:

- returns only published retrieval/search evidence
- does not expose staged candidates, archive paths, the catalog database, ingestion, publication, deletion, or lifecycle mutation
- remains `reference_only: true`
- carries `authority: none`
- treats transport reachability as connectivity, not identity, trust, or permission
- authenticates deployment nodes independently from Riven continuity identity
- preserves source hash, trust class, location, retrieval method, lifecycle state, and warnings
- keeps mobile operation local-first so loss of Home reduces knowledge depth rather than disabling the mobile body

The first implementation is documented in `HOME_REMOTE_RETRIEVAL.md` and exposes bounded `/v1/search` and `/v1/evidence` requests plus a minimal health endpoint.
