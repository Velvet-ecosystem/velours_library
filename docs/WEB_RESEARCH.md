# Velour controlled web research

Velour Web Research is a reference-only network boundary for the Founder research Scroll. It is intentionally separate from the UI so `velvet-interface` can remain a presentation layer while Velour owns retrieval, filtering, and provenance.

## Command

Installing `velours-library` exposes:

```text
velour-web search "query" --endpoint https://search.example/search
velour-web fetch https://example.org/article
```

Search uses the SearXNG JSON contract. A remote endpoint must use HTTPS by default. A loopback SearXNG endpoint may use HTTP only when `--allow-loopback-endpoint` is supplied explicitly. Public HTTP document retrieval is disabled by default and requires the separate `--allow-public-http` override.

## Safety boundary

Selected pages are treated as untrusted external reference material. The adapter:

- permits only HTTP/HTTPS URL syntax and defaults public retrieval to HTTPS;
- rejects credential-bearing URLs;
- rejects localhost plus private, loopback, link-local, multicast, reserved, and unspecified IP targets;
- re-validates redirect targets and the final response URL;
- limits redirects, response bytes, query length, result count, and accepted content types;
- accepts normal HTML/XHTML/plain-text documents only;
- strips scripts, styles, frames, objects, embeds, forms, media, images, metadata, event attributes, and other active markup;
- preserves only a small inert formatting allow-list for the lightweight reader;
- performs no downloads, JavaScript execution, memory promotion, Court action, vehicle control, or automatic Library persistence.

SearXNG search results are metadata only. A result is fetched only after explicit selection by the research surface.

## Output contracts

Search emits `velour.web_research.search.v1` JSON with bounded result metadata.

Fetch emits `velour.web_research.document.v1` JSON containing the sanitized HTML/plain text plus:

- final source URL;
- source host;
- UTC retrieval timestamp;
- SHA-256 of the original fetched bytes;
- content type;
- fetched byte count;
- `authority: none`;
- `external_reference: true`.

The hash and timestamp are intentionally present before the later `Save to Library` bridge is enabled so Library acquisition can preserve provenance instead of reconstructing it from the display layer.

## Deployment direction

Founder may invoke this adapter locally during development, but the preferred vehicle topology is to let the Velour/Librarian node own the network-facing research process and expose only a narrow local service or bridge back to Founder. The UI should never become a general-purpose browser.

A heavyweight JavaScript-capable interactive browser remains a separate future fallback and is not part of this normal research path.
