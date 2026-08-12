# Source Lifecycle Contract

Source lifecycle describes currency and lineage. It does not declare truth.

Each published item may carry a human-readable version label, an optional freshness deadline, a lifecycle state, a predecessor link, and a derived successor link. States are `active`, `stale`, and `superseded`.

Supersession is linear. Publishing revision B with `supersedes=A` marks A as superseded and records B as A's successor. A source that already has a successor cannot be superseded by a second branch through this API. Historical revisions remain searchable and retrievable.

Freshness deadlines do not delete or hide evidence. Retrieval adds `freshness_deadline_passed` when the deadline has passed. Malformed deadlines remain visible as `invalid_stale_after` rather than crashing retrieval. Explicitly stale sources carry `source_stale`; superseded sources carry `source_superseded`.

Relevance and currency remain separate dimensions. Velour does not silently boost a newer revision or suppress an older one merely because of lifecycle state. Consumers receive the lifecycle metadata and decide how to use it.

Linked revisions cannot be removed through the ordinary remove operation because deletion would break lineage. Superseded items cannot be refreshed to active or downgraded to merely stale.
