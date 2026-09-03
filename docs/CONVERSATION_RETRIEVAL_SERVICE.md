# Conversation retrieval service

Velour's existing read-only retrieval service can feed Velvet's local conversation path without exposing Library mutation operations.

## Start the service

After installing this package, `velour-serve` runs the same retrieval service implemented by `velours_library.retrieval_service`.

For a Founder-local bench deployment:

```bash
mkdir -p /var/lib/velvet/secrets/library
chmod 700 /var/lib/velvet/secrets/library
printf '%s\n' '<random secret of at least 24 characters>' \
  > /var/lib/velvet/secrets/library/founder.token
chmod 600 /var/lib/velvet/secrets/library/founder.token

velour-serve \
  --root /path/to/library-data \
  --bind 127.0.0.1 \
  --port 8765 \
  --peer-secret-dir /var/lib/velvet/secrets/library
```

The matching Runtime client uses the same `founder.token` and sends `X-Velvet-Node-ID: founder`.

## Later Velour node

When the Library moves to a Velour/Lyra node, bind the service only to the intended private-LAN interface and point Runtime's `VELVET_LIBRARY_URL` at that address. The evidence contract does not change.

## Exposed surface

The service exposes only:

- `GET /v1/health`
- authenticated `POST /v1/search`
- authenticated `POST /v1/evidence`

It does not expose staging, publication, acquisition, pack adoption, lifecycle mutation, archive paths, SQLite access, Runtime authority, Court, executors, or physical control.

Retrieval remains `reference_only = true` and `authority = none`.
