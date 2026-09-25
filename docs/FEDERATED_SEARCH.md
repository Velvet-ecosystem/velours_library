# Velour federated Archive search

`velour-search` is the reference-only backend for the Archive magnifying-glass surface.

It combines independent providers without turning search results into Velvet authority:

- **Library**: always searches Velour's local indexed evidence under `--root`.
- **ZIM/Kiwix**: optional full-text search through a loopback-only `kiwix-serve` endpoint.
- **Web**: optional SearXNG search through the already-reviewed `velour-web` provider boundary.

The command emits `velour.federated_search.v1` JSON. Every result carries `authority: none` and `external_reference: true`. Provider state is reported independently under `sources`, so a missing Kiwix process or unavailable web provider does not suppress local Library results.

Example:

```text
velour-search "Automotive Grade Linux" \
  --root /srv/velvet/library \
  --kiwix-endpoint http://127.0.0.1:8080 \
  --web-endpoint https://search.example/search
```

No provider is enabled implicitly except the local Library. Kiwix is restricted to loopback URLs. Web search inherits the controlled SearXNG policy and has no default third-party endpoint.

## Kiwix contract

The Kiwix provider uses `kiwix-serve` public API routes only:

- `/catalog/v2/entries` to discover served ZIM books;
- `/search` with XML output for bounded full-text result metadata.

It does not expose Kiwix directly to the vehicle LAN, does not follow arbitrary external targets, and does not persist ZIM results into the canonical Library.

## Next interface slice

The Founder Interface should invoke `velour-search` through a narrow CLI bridge, map its three provider groups into the Scroll-based federated search widget, and enable the Archive magnifying-glass hotspot. Opening a result remains provider-specific and must keep the same reference-only boundary.
