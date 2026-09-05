# Kiwix / ZIM reference shelf

Large offline website archives are a different storage problem from ordinary manuals.

A single Wikipedia ZIM may be many gigabytes, while the canonical Library object path is optimized for bounded documents with provenance, per-item extraction, and SHA-addressed preservation. Copying a huge ZIM into that path would waste storage and make ordinary document limits meaningless.

Velour therefore keeps ZIM archives on an **external read-only reference shelf**:

```text
/srv/velvet/library/
└── external/
    └── zim/
        ├── wikipedia_....zim
        ├── wiktionary_....zim
        └── ...
```

`velour-zim` inventories and serves this shelf through a locally installed `kiwix-serve` process.

## Initialize

```bash
velour-zim --root /srv/velvet/library init
```

Copy downloaded or transferred ZIM archives into:

```text
/srv/velvet/library/external/zim/
```

Split ZIM archives are supported when the first part is named `.zimaa`; the remaining `.zimab`, `.zimac`, and later parts are grouped into the same inventory entry.

## Status

```bash
velour-zim --root /srv/velvet/library status
```

Status reports shelf size, archive count, whether `kiwix-serve` is installed, and whether the shelf is ready.

## Inventory

Create a lightweight inventory:

```bash
velour-zim --root /srv/velvet/library inventory
```

For an integrity pass that hashes every ZIM part:

```bash
velour-zim --root /srv/velvet/library inventory --hash
```

Hashing a large Wikipedia collection can read hundreds of gigabytes and is therefore explicit rather than automatic.

The inventory is written atomically to:

```text
catalog/zim-shelf.json
```

It is local reference metadata, not a canonical Velvet receipt and not an authority grant.

## Serve locally

The safe default binds only to loopback and asks Kiwix to block direct external navigation:

```bash
velour-zim --root /srv/velvet/library serve
```

Default endpoint:

```text
http://127.0.0.1:8080/
```

Velvet, the Home unit, or a local browser can then use Kiwix's full-text search for ZIMs that contain a search index.

`kiwix-serve` is intentionally treated as its own read-only reference engine instead of unpacking Wikipedia into millions of normal Library candidates.

## LAN exposure is explicit

Binding to a non-loopback address is rejected unless the operator explicitly supplies `--allow-network`:

```bash
velour-zim \
  --root /srv/velvet/library \
  serve \
  --address 192.168.1.20 \
  --allow-network
```

A private or encrypted Velvet transport/reverse proxy remains preferable when the service is reachable by other nodes.

Kiwix Server itself is HTTP. Network reachability is not identity or authorization.

## External links

Velour asks Kiwix to block direct external navigation by default. This keeps an offline reference lookup from unexpectedly becoming a public-web transition.

The operator may deliberately disable that posture with:

```bash
--allow-external-links
```

Doing so changes browsing behavior only. It does not change Library trust or authority.

## Relationship to normal retrieval

The ordinary Velour Library remains the source for provenance-rich document evidence, page/line locations, revisions, and knowledge packs.

The ZIM shelf is a large external reference engine. A future federated retrieval adapter may merge Kiwix `/search` results into Velour evidence responses while retaining a clear `source_engine=kiwix` boundary. Until then, the shelf is separately searchable through Kiwix and does not masquerade as normal catalog evidence.
