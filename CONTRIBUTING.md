# Contributing to Velour's Library

Contributions are welcome when they preserve the Library's local-first, provenance-aware, evidence-only role in the Velvet ecosystem.

## Before opening a pull request

- Keep Library retrieval separate from belief, identity, authorization, and execution authority.
- Preserve staged-versus-published boundaries and source provenance.
- Do not add real credentials, bearer tokens, private source collections, customer/user data, private network topology, or deployment-local policy files.
- Use synthetic examples and public-safe test fixtures.
- Keep network services bounded and fail-closed. New remote capabilities should declare request/response limits, authentication behavior, failure posture, and audit behavior.
- Do not introduce generic shell execution, arbitrary filesystem writes, automatic trust promotion, or automatic publication.

## Testing

Install the development and PDF extras and run the full suite:

```bash
python -m pip install -e ".[dev,pdf]"
python -m pytest -q
```

The GitHub Actions workflow tests the supported Python range represented by the CI matrix.

Security-sensitive changes should include focused negative tests for malformed input, oversized input, path/symlink handling, authentication failures, redirect/address changes, integrity failures, or other relevant abuse cases.

## Pull requests

Keep changes focused and explain:

- what contract or behavior changes;
- why the change belongs in `velours_library` rather than Runtime, Event Protocol, Receipts, Riven, Home, or another Velvet repository;
- what tests prove the change;
- whether the change affects provenance, trust, publication, remote retrieval, acquisition, packs, or deployment security.

## License

Contributions are accepted under the repository's GNU General Public License v3.0.
