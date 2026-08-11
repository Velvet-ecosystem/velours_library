# Security and Safety

Knowledge ingestion is an input boundary. Documents, archives, webpages, repositories, OCR output, and metadata may be malformed, hostile, misleading, or simply wrong.

## Required posture

- Treat newly acquired material as untrusted input.
- Quarantine before publication into active retrieval.
- Validate file type independently of filename extension where practical.
- Apply size and resource limits to extraction and indexing jobs.
- Protect against archive bombs, recursive archives, parser crashes, path traversal, and oversized documents.
- Never execute code merely because it was found inside a knowledge source.
- Keep secrets, credentials, private keys, and tokens out of cataloged knowledge by default.
- Record failed ingestion attempts and reasons without losing canonical evidence needed for diagnosis.
- Keep model-generated transformations clearly marked as generated derivatives.

## Web and repository captures

A captured webpage or source repository is evidence, not executable authority. Instructions found inside stored material must never supersede Velvet's runtime, safety, owner, or capability policies.

## Sensitive collections

Knowledge packs may carry sensitivity labels and access rules. Medical, personal, credential-related, owner-private, and vehicle-specific information should be separable from general public-reference collections.
