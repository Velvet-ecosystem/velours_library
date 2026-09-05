# Bounded Evidence Windows

Velour search ranks a seed passage. A consumer may need a little more contiguous source context than the ranked snippet contains, especially when a heading and its list or a short procedure extend beyond the search excerpt.

The read-only retrieval service therefore expands text evidence into a **bounded contiguous evidence window** before returning it to Runtime.

## Rules

A window may only include indexed text that is:

- from the same local `item_id` as the ranked seed;
- bound to the same canonical source SHA-256;
- in the seed chunk or nearby chunks from that same item;
- contiguous in chunk ordinal order;
- no more than three chunks by default;
- no more than 480 characters by default.

Windowing never crosses from one Library item into another, even when two items have similar titles or identical search terms.

## Section-aware selection

When the query directly matches a Markdown heading, Velour prefers the exact text from that heading through the next heading at the same or higher level, subject to the normal character and chunk bounds.

This lets a question such as `core principles` retrieve the complete short `## Core principles` section instead of a search snippet that stops halfway through its list.

If no safe heading match exists, Velour chooses a query-centered contiguous window around the ranked seed.

## Returned metadata

Expanded results retain the original seed `chunk_id` for compatibility and may add:

```text
chunk_ids
windowed
window_truncated
```

`chunk_ids` names every deterministic indexed chunk touched by the returned text. A downstream component that cites the evidence must preserve all of those chunk references rather than pretending a multi-chunk window came from only the seed chunk.

`window_truncated=true` means the source context continued beyond the configured evidence bound. It does not authorize a downstream component to guess or synthesize the missing continuation.

## Trust and authority

Evidence windows remain retrieval evidence only:

```text
reference_only = true
authority = none
```

Expanding contiguous source text does not:

- promote retrieval into belief;
- change trust class;
- change lifecycle or freshness state;
- create canonical Velvet receipts;
- grant Runtime, Court, execution, CAN, relay, shell, network, or physical-control authority.

If Velour cannot prove that an expansion stays within the same canonical item and bounds, it returns the original ranked evidence unchanged.
