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
