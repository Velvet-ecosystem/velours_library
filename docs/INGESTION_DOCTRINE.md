# Ingestion Doctrine

The goal of ingestion is not to make information disappear into a database. It is to make information retrievable without losing its identity.

## Ingestion stages

1. **Acquire** — record source URI, medium, owner/provider, acquisition method and timestamp.
2. **Quarantine** — place unvalidated material in an incoming state.
3. **Identify** — determine format, title, publisher/author, version, language, date and licensing notes where possible.
4. **Hash** — calculate a content checksum before transformation.
5. **Classify** — assign domain, trust class, sensitivity and intended knowledge pack.
6. **Preserve** — store canonical source material separately from derivatives.
7. **Extract** — produce searchable text, metadata, tables or other machine-usable derivatives.
8. **Index** — update full-text, semantic and structured indexes.
9. **Receipt** — record what happened, with tool/version information where available.
10. **Publish internally** — make the item available to retrieval only after validation policy passes.

## Rules

- Never silently replace canonical source material with generated text.
- Never discard provenance during conversion.
- OCR output is a derivative and may contain errors.
- Generated summaries are commentary, not source evidence.
- Duplicate detection should prefer hashes and source identity over filenames alone.
- A failed transform must not invalidate an otherwise preserved source.
- Unknown or ambiguous licensing must be recorded rather than guessed.
- Retrieval should expose stale/version warnings when relevant.
