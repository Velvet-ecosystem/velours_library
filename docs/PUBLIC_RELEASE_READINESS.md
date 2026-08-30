# Public Release Readiness

This record defines the final public-release gates for `velours_library`.

## Public-safe scope

The repository may publish:

- Library contracts and implementation;
- guarded ingestion and publication workflow;
- provenance and lifecycle metadata;
- retrieval and evidence contracts;
- approved-source acquisition logic and schemas;
- portable knowledge-pack export, quarantine, adoption, provenance, and lifecycle logic;
- read-only remote retrieval service/client;
- synthetic examples, schemas, tests, and public documentation.

The repository must not publish real deployment secrets, bearer tokens, private source collections, owner policy, customer/user data, sensitive local network details, private acquisition policies, runtime databases, indexes, audit logs, or receipts.

## Security boundary

Public release does not grant execution authority. Library content and retrieval results remain evidence/reference material. Runtime, Court, identity, physical control, and canonical consequential-action authority remain outside this repository.

Remote retrieval remains read-only and reference-only. Off-host use requires a protected private interface or authenticated/encrypted transport. Bearer admission tokens are deployment-local and are not transport encryption or Velvet identity.

## Release gates

Before changing visibility to public, verify:

1. `main` contains the intended current acquisition and Home read-only retrieval work.
2. No open pull requests contain required release changes.
3. CI passes on the final public-hardening pull request.
4. A full fetched Git-history secret scan reports no verified or unverified secrets.
5. Obsolete branches are removed before visibility changes.
6. Repository settings are reviewed and the standard Velvet `protect main` ruleset is active immediately after public visibility is enabled.
7. Public vulnerability reporting / security settings are enabled where available.

## Current release posture

Prepared for public release subject to the gates above. Repository visibility remains an explicit owner-controlled action.
