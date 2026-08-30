# Security Policy

Velour's Library is a local-first evidence archive. Security reports should preserve that boundary: retrieval is reference-only, remote admission is not Velvet identity, and Library material must never grant Runtime, Court, executor, shell, network, or physical-control authority.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting / Security Advisory flow when it is available for this repository.

Do not place credentials, bearer tokens, private source material, exploit payloads, private network details, or other sensitive evidence in a public issue. If private vulnerability reporting is unavailable, open only a minimal non-sensitive issue asking the maintainers for a private reporting channel.

Useful reports include the affected version or commit, the component involved, reproduction conditions, expected and observed behavior, and the likely impact. Redact secrets and private Library contents.

## Deployment security boundaries

- The remote retrieval service binds to loopback by default. Off-host exposure is an explicit deployment decision.
- Bearer tokens authenticate admission to the read-only retrieval service; they do not encrypt the network and they are not Velvet identity.
- Off-host retrieval should use a protected private interface or authenticated/encrypted transport such as an approved secure overlay.
- Per-node token files must remain outside Git, must be regular non-symlink files, and should be readable only by the service account (`0600`).
- Deployment-local source policies, tokens, credentials, Library payloads, indexes, databases, audits, and receipts must not be committed to this repository.
- Approved-source acquisition is intentionally single-resource and policy-gated. Redirects and destination addresses must remain revalidated so source approval cannot be used as an SSRF bypass.
- Retrieved documents and knowledge packs are evidence, not commands, beliefs, authorization grants, or executable authority.

## Security-sensitive changes

Changes affecting remote retrieval, authentication, acquisition policy, redirect handling, path validation, archive/pack intake, symlink handling, hash verification, resource bounds, or any future write-capable interface require focused tests and review.

A change that adds shell access, arbitrary file writes, generic remote execution, credential forwarding, or a path around Runtime/Court authorization is outside the Library's intended security model and should not be accepted as a routine feature.

## Supported release posture

The public repository documents and implements the Library software and contracts. Real deployment secrets, owner policy, private source collections, sensitive network topology, and local operating data remain deployment-local.
