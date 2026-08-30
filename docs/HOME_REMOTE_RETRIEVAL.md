# Home-Hosted Remote Library Retrieval

## Purpose

Velour's Library may be physically hosted on a stationary Home node with much larger storage than a vehicle, cyberdeck, phone-class companion, or other mobile Velvet body can reasonably carry.

The remote retrieval service gives approved mobile nodes a narrow way to ask that Home Library for published evidence without mounting Home storage, opening the Library database, or gaining any write path.

The intended relationship is:

```text
mobile local Library / working set
            |
      local retrieval first
            |
       depth insufficient
            v
approved read-only Home Library request
            |
      LAN / protected IP path
      / Tailscale / future carrier
            |
       Velour retrieval
            |
 published evidence + provenance
            |
        mobile reasoning
```

Home unavailable means the mobile node becomes shallower, not nonfunctional. Internet unavailable means Home retrieval still works from already admitted local Library material.

## Ownership

`velours_library` owns the retrieval contract and the service/client implementation.

`Velvet_home` is a preferred physical host because a Home node can remain powered, connected, and storage-rich. Home does not fork the Library, own retrieval truth, or gain a separate knowledge architecture.

Transport remains separate. A request may travel over same-site IP, Tailscale, or another suitable future carrier. Transport membership is not Library trust and is not Velvet authority.

## Read-only service

Run the service directly from the installed package:

```bash
python -m velours_library.retrieval_service \
  --root /srv/velour/library-data \
  --bind 127.0.0.1 \
  --port 8765 \
  --peer-secret-dir /etc/velour/retrieval-peers
```

The default bind is loopback. Off-host exposure is a deployment decision.

For off-host use, expose the service only through a protected private interface or an authenticated/encrypted transport. A bearer token proves admission to this service; it does not encrypt a plain network and it is not Velvet identity.

The service exposes only:

```text
GET  /v1/health
POST /v1/search
POST /v1/evidence
```

It deliberately does not expose:

- the SQLite catalog
- archive/storage paths
- raw canonical objects
- staged candidates
- acquisition
- publication
- rejection
- lifecycle mutation
- deletion
- reindexing
- shell access
- Runtime, Court, executor, or physical-control authority

A later whole-document or knowledge-pack transfer feature should use a separate bounded transfer contract rather than widening this API.

## Approved mobile nodes

Each deployment keeps one local secret file per approved node:

```text
/etc/velour/retrieval-peers/
  tibby-founder.token
  cyberdeck-01.token
  mobile-companion-01.token
```

The filename stem is the declared `X-Velvet-Node-ID`. Node IDs are deployment identifiers, not Riven identity roots and not authorization to perform actions elsewhere in Velvet.

Secret files must:

- be regular files, not symlinks
- be readable only by the service account (`0600` is the expected posture)
- contain a strong random bearer secret of at least 24 characters
- remain outside Git, logs, receipts, surface manifests, capability snapshots, and ordinary diagnostics

Deleting or rotating one node's token revokes that node's retrieval admission without changing Velvet identity.

## Mobile client

A mobile node can use the included standard-library client:

```bash
python -m velours_library.remote_client \
  --url http://127.0.0.1:8765 \
  --node-id tibby-founder \
  --token-file /etc/velour/home-library.token \
  evidence "Tiburon accessory belt routing" \
  --limit 8
```

In a real remote deployment the URL should resolve over the chosen protected Home path rather than loopback.

The Python client also exposes:

```python
from velours_library.remote_client import RemoteLibraryClient

client = RemoteLibraryClient.from_token_file(
    "http://home-library:8765",
    node_id="tibby-founder",
    token_file="/etc/velour/home-library.token",
)

bundle = client.evidence("pulley alignment", limit=8)
```

## Evidence response

Remote retrieval preserves the existing Library evidence semantics. Results carry source identity, canonical SHA-256, trust class, location, retrieval method, score, lifecycle state, and warnings where available.

The network wrapper additionally states:

```text
read_only: true
reference_only: true
authority: none
```

Retrieved evidence is not belief, permission, or a canonical action receipt.

## Query privacy and audit

Successful and failed admitted retrieval operations write a small local audit record under:

```text
<library-root>/audit/remote-retrieval.jsonl
```

The audit records node ID, endpoint, result count, limit, timestamp, and SHA-256 of the query text. It deliberately does not store the raw query, reducing leakage of private task wording while still allowing operators to correlate repeated or abusive requests.

## Resource bounds

The service enforces bounded request size, query length, result count, and serialized response size. Defaults are intentionally modest so a weak Home node cannot be trivially exhausted by a valid but excessive query.

These are deployment-tunable ceilings, not a promise that every query is cheap. Runtime/host health may later add scheduling, pressure, or rate policy above this service without changing the retrieval contract.

## Failure posture

- Home unavailable -> mobile uses its local working set and packs
- retrieval service unavailable -> mobile records depth loss; local operation continues
- bad/expired node token -> request denied; no fallback authority path
- Tailscale unavailable -> same-site protected local path may still work if configured
- Internet unavailable -> admitted Home Library retrieval continues
- index degraded -> Home reports Library health separately; do not fabricate missing results
- oversized request/response -> fail bounded rather than consume unbounded memory

## Design laws

**Remote retrieval is a window into the shelves, not a key to the storeroom.**

**Home may hold more knowledge without becoming more authoritative.**

**A mobile node should lose depth when Home disappears, not lose itself.**
