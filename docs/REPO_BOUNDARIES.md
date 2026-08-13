# Repository Boundaries

Velour's Library owns knowledge acquisition, preservation, cataloging, provenance, indexing, pack assembly, retrieval evidence, and knowledge-library lifecycle policy.

It does **not** own:

- Velvet's core reasoning or persona
- event transport
- receipt-system implementation outside library-specific receipt emitters
- runtime orchestration
- physical vehicle/home/forge control
- language-development architecture
- continuity identity

Integrations should occur through narrow interfaces rather than duplicating those repositories.

Before implementing a new subsystem here, check adjacent Velvet repositories for an existing owner. If another repository already owns the capability, this repository should define only the library-side adapter or contract required to use it.

## Expected integrations

- `velvet-receipts` — authoritative receipt format / verification where applicable
- `velvet-event-protocol` — event transport contracts
- `velvet-runtime` — service lifecycle and runtime hosting
- `velvet-ai-core` — reasoning-side retrieval consumer
- `velvet-language` — language-facing use of retrieved knowledge, without moving language ownership here
- `velvet-continuity-spine` — identity / lineage references where required

This boundary keeps Velour a librarian rather than quietly turning her into a second brain, runtime, event bus, or control system.
