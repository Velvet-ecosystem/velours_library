# Trust and Provenance

Velour records where information came from and how much evidentiary weight it should carry. Trust is metadata, not a declaration that a claim is true.

## Suggested trust classes

- `primary` — original manufacturer, standards body, project owner, official government or direct first-party documentation.
- `scholarly` — peer-reviewed or otherwise formally published research with identifiable authorship.
- `secondary` — reputable analysis, reporting, textbooks or maintained technical references.
- `community` — forums, Q&A, discussion boards, personal technical writeups and community-maintained references.
- `owner` — material supplied or authored by Mister / the system owner.
- `generated` — machine-generated summaries, extractions, inferred relationships or synthetic derivatives.
- `unknown` — provenance or reliability has not yet been classified.

These classes may be refined by domain-specific policy. They must never be used to automatically convert uncertainty into certainty.

## Minimum provenance record

Each cataloged item should be able to record:

- stable item ID
- title
- source / publisher / author when known
- source URI or acquisition origin
- acquired timestamp
- published or version date when known
- content hash
- media type
- language
- license / rights note
- trust class
- canonical storage identity
- parent/derived relationships
- transformation history
- indexing state
- knowledge-pack membership
- stale/version status

## Retrieval rule

A retrieval result should carry its source identity and trust class alongside its content. Velvet should be able to say not only *what was found*, but *what kind of source said it*.
