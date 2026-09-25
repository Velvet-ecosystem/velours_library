"""Federated reference search for Velour's Archive magnifying-glass surface.

The federation owns no authority and does not persist anything. It combines
three bounded reference sources:

* Velour's local Library evidence index;
* an optional loopback-only Kiwix server for ZIM archives;
* an optional explicitly configured SearXNG web-search endpoint.

Failure of one optional source does not suppress results from the others.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, build_opener
from xml.etree import ElementTree

from .catalog import Library
from .web_research import SearxngSearchProvider, WebResearchError, WebResearchPolicy

_SCHEMA = "velour.federated_search.v1"
_ALLOWED_PROVIDERS = {"library", "zim", "web"}
_DEFAULT_LIMIT = 8
_DEFAULT_TIMEOUT = 5.0
_DEFAULT_XML_BYTES = 512 * 1024


class FederatedSearchError(RuntimeError):
    """Raised when the federation request itself is invalid."""


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return "fs_%s" % digest


def _clean_text(value: str, limit: int = 900) -> str:
    rendered = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())
    return rendered[:limit]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first_text(node: ElementTree.Element, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in node.iter():
        if _local_name(child.tag) in wanted:
            text = " ".join("".join(child.itertext()).split())
            if text:
                return text
    return ""


def _result(
    provider: str,
    *,
    title: str,
    source: str,
    uri: str,
    summary: str = "",
    result_id: str = "",
    metadata: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
    if provider not in _ALLOWED_PROVIDERS:
        raise ValueError("unknown provider")
    return {
        "result_id": result_id or _stable_id(provider, uri, title),
        "provider": provider,
        "title": title.strip()[:300],
        "source": source.strip()[:300],
        "uri": uri.strip(),
        "summary": _clean_text(summary),
        "authority": "none",
        "external_reference": True,
        "metadata": dict(metadata or {}),
    }


class KiwixSearchProvider:
    """Small loopback-only client over kiwix-serve's public catalog/search API."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8080",
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT,
        max_response_bytes: int = _DEFAULT_XML_BYTES,
        opener: Any = None,
    ) -> None:
        if timeout_seconds <= 0 or max_response_bytes < 1:
            raise ValueError("Kiwix client limits must be positive")
        self.endpoint = self._validate_endpoint(endpoint)
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)
        self.opener = opener or build_opener()

    @staticmethod
    def _validate_endpoint(endpoint: str) -> str:
        parsed = urlsplit(endpoint.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Kiwix endpoint must be an HTTP(S) loopback URL")
        host = parsed.hostname.rstrip(".").lower()
        allowed = host in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            address = None
        if address is not None:
            allowed = address.is_loopback
        if not allowed:
            raise ValueError("Kiwix endpoint must remain on loopback")
        path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    def _get_xml(self, path: str, params: Mapping[str, object]) -> ElementTree.Element:
        target = self.endpoint + path
        if params:
            target += "?" + urlencode({key: str(value) for key, value in params.items()})
        request = Request(
            target,
            headers={"User-Agent": "VelourFederatedSearch/1.0", "Accept": "application/xml,text/xml;q=0.9", "Connection": "close"},
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout_seconds) as response:
                length_header = response.headers.get("Content-Length")
                if length_header:
                    try:
                        declared = int(length_header)
                    except ValueError as exc:
                        raise FederatedSearchError("Kiwix returned an invalid Content-Length") from exc
                    if declared > self.max_response_bytes:
                        raise FederatedSearchError("Kiwix response exceeds configured maximum")
                payload = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise FederatedSearchError("Kiwix returned HTTP %d" % exc.code) from exc
        except URLError as exc:
            raise FederatedSearchError("Kiwix unavailable: %s" % exc.reason) from exc
        except TimeoutError as exc:
            raise FederatedSearchError("Kiwix timed out") from exc
        if len(payload) > self.max_response_bytes:
            raise FederatedSearchError("Kiwix response exceeds configured maximum")
        try:
            return ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise FederatedSearchError("Kiwix returned invalid XML") from exc

    def _book_names(self, maximum: int = 64) -> List[str]:
        root = self._get_xml("/catalog/v2/entries", {"count": maximum})
        names: List[str] = []
        for node in root.iter():
            if _local_name(node.tag) not in {"entry", "item"}:
                continue
            candidates: List[str] = []
            for child in node.iter():
                if _local_name(child.tag) == "link":
                    href = str(child.attrib.get("href") or "")
                    match = re.search(r"/content/([^/?#]+)", href)
                    if match:
                        candidates.append(match.group(1))
                for key, value in child.attrib.items():
                    if _local_name(key) == "name" and value:
                        candidates.append(str(value))
            for candidate in candidates:
                if candidate not in names:
                    names.append(candidate)
                if len(names) >= maximum:
                    return names
        return names

    def search(self, query: str, limit: int = _DEFAULT_LIMIT) -> List[Dict[str, object]]:
        query = query.strip()
        if not query:
            raise FederatedSearchError("query cannot be empty")
        if limit < 1:
            return []
        results: List[Dict[str, object]] = []
        for book in self._book_names():
            remaining = limit - len(results)
            if remaining <= 0:
                break
            root = self._get_xml(
                "/search",
                {"books.name": book, "pattern": query, "pageLength": remaining, "start": 0, "format": "xml"},
            )
            for node in root.iter():
                if _local_name(node.tag) not in {"entry", "item", "result"}:
                    continue
                title = _first_text(node, {"title"})
                if not title:
                    continue
                href = ""
                for child in node.iter():
                    if _local_name(child.tag) == "link":
                        href = str(child.attrib.get("href") or "").strip() or " ".join("".join(child.itertext()).split())
                        if href:
                            break
                if not href:
                    href = _first_text(node, {"url", "uri"})
                if not href:
                    continue
                uri = urljoin(self.endpoint + "/", href)
                summary = _first_text(node, {"summary", "description", "snippet", "content"})
                results.append(
                    _result(
                        "zim",
                        title=title,
                        source="Kiwix/%s" % book,
                        uri=uri,
                        summary=summary,
                        metadata={"book": book, "loopback_only": True},
                    )
                )
                if len(results) >= limit:
                    return results
        return results


class FederatedSearchEngine:
    """Combine independent reference providers without blending authority."""

    def __init__(
        self,
        library: Library,
        *,
        kiwix_provider: Optional[Any] = None,
        web_provider: Optional[Any] = None,
    ) -> None:
        self.library = library
        self.kiwix_provider = kiwix_provider
        self.web_provider = web_provider

    def _library_results(self, query: str, limit: int) -> List[Dict[str, object]]:
        rendered: List[Dict[str, object]] = []
        for item in self.library.evidence(query, limit):
            rendered.append(
                _result(
                    "library",
                    title=item.title,
                    source=item.source,
                    uri="velour-library:%s" % item.item_id,
                    summary=item.snippet,
                    result_id=_stable_id("library", item.item_id, item.chunk_id or "metadata"),
                    metadata={
                        "item_id": item.item_id,
                        "chunk_id": item.chunk_id,
                        "source_uri": item.source_uri,
                        "trust_class": item.trust_class,
                        "sha256": item.sha256,
                        "score": item.score,
                        "retrieval_method": item.retrieval_method,
                        "location": item.location,
                        "lifecycle_state": item.lifecycle_state,
                        "warnings": list(item.warnings),
                    },
                )
            )
        return rendered

    def search(self, query: str, limit: int = _DEFAULT_LIMIT) -> Dict[str, object]:
        query = query.strip()
        if not query:
            raise FederatedSearchError("query cannot be empty")
        if len(query) > 500:
            raise FederatedSearchError("query is too long")
        if limit < 1 or limit > 25:
            raise FederatedSearchError("limit must be between 1 and 25")

        results: List[Dict[str, object]] = []
        sources: Dict[str, Dict[str, object]] = {}

        try:
            local = self._library_results(query, limit)
            results.extend(local)
            sources["library"] = {"status": "ok", "count": len(local)}
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            sources["library"] = {"status": "error", "count": 0, "message": str(exc)[:300]}

        if self.kiwix_provider is None:
            sources["zim"] = {"status": "disabled", "count": 0}
        else:
            try:
                zim = list(self.kiwix_provider.search(query, limit))
                results.extend(zim)
                sources["zim"] = {"status": "ok", "count": len(zim)}
            except (OSError, RuntimeError, ValueError, FederatedSearchError) as exc:
                sources["zim"] = {"status": "unavailable", "count": 0, "message": str(exc)[:300]}

        if self.web_provider is None:
            sources["web"] = {"status": "disabled", "count": 0}
        else:
            try:
                web_rows = list(self.web_provider.search(query))[:limit]
                web = [
                    _result(
                        "web",
                        title=str(row["title"]),
                        source=str(row["source"]),
                        uri=str(row["url"]),
                        summary=str(row.get("summary") or ""),
                        result_id="web:%s" % str(row["result_id"]),
                    )
                    for row in web_rows
                ]
                results.extend(web)
                sources["web"] = {"status": "ok", "count": len(web)}
            except (OSError, RuntimeError, ValueError, KeyError, WebResearchError) as exc:
                sources["web"] = {"status": "unavailable", "count": 0, "message": str(exc)[:300]}

        return {
            "schema": _SCHEMA,
            "query": query,
            "authority": "none",
            "external_reference": True,
            "sources": sources,
            "results": results,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour-search", description="Federated Velour reference search")
    parser.add_argument("query")
    parser.add_argument("--root", default="library-data")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--kiwix-endpoint")
    parser.add_argument("--web-endpoint")
    parser.add_argument("--allow-loopback-web", action="store_true")
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        library = Library(Path(args.root))
        kiwix = KiwixSearchProvider(args.kiwix_endpoint, timeout_seconds=args.timeout) if args.kiwix_endpoint else None
        web = None
        if args.web_endpoint:
            policy = WebResearchPolicy(timeout_seconds=args.timeout, max_results=args.limit)
            web = SearxngSearchProvider(
                args.web_endpoint,
                policy=policy,
                allow_loopback_endpoint=bool(args.allow_loopback_web),
            )
        payload = FederatedSearchEngine(library, kiwix_provider=kiwix, web_provider=web).search(args.query, args.limit)
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, FederatedSearchError, WebResearchError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
