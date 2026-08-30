# Approved Source Acquisition

Velour's acquisition layer is the governed delivery path between approved remote sources and the existing Library quarantine/staging boundary.

It fills the missing first step in the ingestion doctrine:

```text
approved remote source
        |
policy match + network validation
        |
bounded fetch
        |
content-type / size / optional checksum validation
        |
acquisition record
        |
Library.stage()
        |
existing candidate inspection / publish / reject path
```

## Core rule

**Acquisition delivers evidence. It does not publish knowledge.**

A successful network fetch creates a normal staged Library candidate. Staged candidates remain absent from normal retrieval until the existing Library publication path accepts them.

The acquisition layer cannot:

- publish a candidate
- grant Runtime, Court, executor, shell, network, relay, or physical-control authority
- silently raise trust beyond the local source policy
- turn a downloaded claim into truth
- crawl a site or follow page links as new acquisition work
- discover and enroll new sources automatically

## Local source policy

Remote access is controlled by a deployment-local JSON policy using schema:

```text
velours.library.acquisition-policy.v1
```

A source rule declares:

- stable rule ID
- exact origin
- optional path prefix
- Library source label
- trust class
- allowed response content types
- per-source byte ceiling
- whether private/local network addresses are deliberately permitted
- rights/usage note
- default tags

The repository contains only an example policy. A real deployment policy is local configuration and should describe sources the owner has deliberately approved.

Example:

```json
{
  "schema": "velours.library.acquisition-policy.v1",
  "sources": [
    {
      "id": "maker-manuals",
      "origin": "https://manuals.example.org",
      "path_prefix": "/products",
      "source_label": "manufacturer",
      "trust_class": "primary",
      "allowed_content_types": ["application/pdf", "text/*"],
      "allow_private_network": false,
      "max_bytes": 33554432
    }
  ]
}
```

## Fetch one approved resource

```bash
velour-acquire \
  --root ./library-data \
  --policy ./local/acquisition-policy.json \
  check https://manuals.example.org/products/widget.pdf
```

Then stage it:

```bash
velour-acquire \
  --root ./library-data \
  --policy ./local/acquisition-policy.json \
  fetch https://manuals.example.org/products/widget.pdf \
  --title "Widget Service Manual" \
  --tag workshop \
  --version 2.1 \
  --stale-after 2027-08-01
```

For a source that publishes a trusted checksum, pin the expected bytes:

```bash
velour-acquire \
  --root ./library-data \
  --policy ./local/acquisition-policy.json \
  fetch https://manuals.example.org/products/widget.pdf \
  --title "Widget Service Manual" \
  --sha256 <64-hex-sha256>
```

Successful output includes a `candidate_id` with `candidate_state: staged` and `published: false`.

Normal Library review still follows:

```bash
velour --root ./library-data candidates --state staged
velour --root ./library-data publish <candidate-id>
```

or:

```bash
velour --root ./library-data reject <candidate-id> --reason "wrong revision"
```

## Acquisition records

Every successful delivery appends an acquisition record under:

```text
receipts/acquisition-events.jsonl
```

The record preserves:

- requested URL
- final URL after approved redirects
- source-rule identity
- acquisition timestamp
- SHA-256
- byte count
- response content type
- HTTP status
- ETag when present
- Last-Modified when present
- staged candidate identity
- permanent `authority: none`

Inspect them with:

```bash
velour-acquire --root ./library-data --policy ./local/acquisition-policy.json records
```

These are Library acquisition audit records, not a substitute for canonical ecosystem action Receipts.

## Network safety posture

The acquisition client accepts only HTTP(S) URLs that match an explicit source rule. Credentials embedded in URLs are rejected.

By default a source that resolves to loopback, private, link-local, multicast, reserved, or unspecified addresses is rejected. A local deployment may opt into a private-network source only by setting `allow_private_network: true` on that exact rule. This supports deliberately hosted local documentation servers without making LAN endpoints implicit acquisition targets.

Redirect targets are re-checked against source policy and network-address policy before following them.

This is an acquisition boundary, not a complete operating-system egress sandbox. Deployments that admit less-trusted operators or third-party acquisition jobs should additionally constrain the process with normal OS/network isolation.

## Resource posture

The downloader streams to a temporary file and hashes while writing. It does not keep an entire resource in memory.

The effective byte ceiling is the smallest of:

- the rule-specific maximum, when present
- policy `default_max_bytes`
- the Library's existing `max_file_bytes`

A declared `Content-Length` over the limit is rejected before streaming. A response that grows past the limit while streaming is also rejected.

Temporary acquisition payloads are removed after staging or failure. The existing `Library.stage()` copy is the quarantine candidate.

## Home relationship

Velvet Home is a natural place to run this tooling because it can be stationary, powered, storage-rich, and connected for long periods. Home does not own acquisition policy or Library truth. It merely hosts the service and storage when that deployment role is available.

Loss of Internet stops new deliveries. It does not stop retrieval from already published local Library material.
