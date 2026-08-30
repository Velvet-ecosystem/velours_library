# Public Release Readiness

This record captures the final public-release review for `velours_library`.

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

## Verified before visibility change

- Current `main` contains the intended approved-source acquisition and Home read-only retrieval work.
- The final public-hardening patch changes documentation, ignore rules, and package metadata only; it does not alter Library behavior or authority.
- The public-hardening pull request completed the Library test matrix successfully.
- An isolated TruffleHog 3.97.1 workflow fetched repository branches/history and scanned 265 chunks / 609,315 bytes with 0 verified secrets and 0 unverified secrets.
- The normal CI workflow uses read-only repository contents permission.
- GPLv3 is present and package metadata now declares the license and public repository/issue locations.
- Deployment-local token files, certificate/key material, local configuration, and generated `library-data/` are excluded by `.gitignore` in the public-hardening patch.

## Owner-controlled steps remaining

1. Merge the final public-hardening pull request.
2. Remove obsolete branches before changing visibility.
3. Change repository visibility to public.
4. Confirm the standard Velvet `protect main` ruleset is active on the default branch.
5. Enable/review public vulnerability reporting and other repository security settings where available.

Repository visibility remains an explicit owner-controlled action.
