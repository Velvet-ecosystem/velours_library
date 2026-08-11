# Ingestion Guardrails

New material enters Velour's Library through a quarantine boundary.

```text
source -> stage -> inspect/verify -> publish -> archive/catalog/index
                 \-> reject -> audit record + staged payload removal
```

Staged candidates are not searchable and are not part of the active library. Publication recalculates SHA-256 before copying bytes into the canonical content-addressed archive.

Default resource limits protect small nodes from accidental or hostile input: a maximum staged file size, a separate extraction-size ceiling, and a PDF-specific parser ceiling. Large valid files may still be archived without extracting text. PDF parsing is attempted only when the stored bytes begin with a PDF header, not merely because a filename ends in `.pdf`.

These limits are local policy defaults, not universal truth. Deployments may tune them to hardware and trust context.
