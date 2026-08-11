# Library Architecture

Velour's Library is organized as a pipeline rather than a single folder of files.

```text
source
  -> acquisition
  -> quarantine / incoming
  -> validation
  -> canonical archive
  -> metadata + provenance catalog
  -> extraction / normalization
  -> indexes
  -> curated knowledge packs
  -> retrieval service
  -> Velvet / authorized handmaidens
```

## Separation of concerns

### Canonical archive
Preserves source material as acquired whenever practical. Derived text, OCR output, summaries, embeddings, and normalized representations do not overwrite canonical evidence.

### Catalog
Stores source identity, acquisition time, licensing notes, hashes, versions, trust class, relationships, transformations, and lifecycle state.

### Indexes
Indexes are disposable derivatives. They may be rebuilt from the archive and catalog. Initial targets are full-text search, semantic retrieval, entity lookup, and structured metadata filtering.

### Knowledge packs
A knowledge pack is a curated, portable collection with a manifest. Packs can describe automotive, electronics, fabrication, computing, maps, science, medical reference, or Velvet-specific research collections.

### Retrieval
Retrieval returns evidence plus provenance. A result should carry enough metadata for Velvet to distinguish primary documentation, secondary reporting, community discussion, owner-authored notes, inferred relationships, and generated derivatives.

## Storage posture

Git stores code, schemas, documentation, manifests, examples, and small fixtures. Bulk source archives belong on managed local storage rather than in repository history.
