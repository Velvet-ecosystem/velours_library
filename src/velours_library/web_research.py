"""Controlled network adapter for Velour Web Research.

The adapter is deliberately small and standard-library only. It provides:
- bounded SearXNG JSON search against one explicitly configured endpoint;
- guarded HTTP(S) retrieval for a selected result;
- private/link-local/reserved network blocking;
- bounded redirects, response size, and content types;
- HTML sanitization into inert reference material.

It does not persist material, execute scripts, or grant Velvet authority.
"""
from __future__ import annotations

import argparse
import hashlib
import html
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_SEARCH_BYTES = 512 * 1024
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MAX_RESULTS = 8
_ALLOWED_DOCUMENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
_ALLOWED_SEARCH_TYPES = {"application/json", "text/json"}
_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_STRIP_TAGS_WITH_CONTENT = {"script", "style", "noscript", "iframe", "object", "embed", "svg", "canvas", "template"}
_DROP_TAGS = {"form", "input", "button", "select", "option", "textarea", "meta", "link", "base", "img", "video", "audio", "source", "track"}
_ALLOWED_TAGS = {"p", "br", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "pre", "code", "strong", "b", "em", "i", "u", "s", "hr", "a", "table", "thead", "tbody", "tr", "th", "td"}
_VOID_TAGS = {"br", "hr"}


class WebResearchError(RuntimeError):
    """Raised when a web-research operation cannot be completed safely."""


@dataclass(frozen=True)
class WebResearchPolicy:
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_search_bytes: int = DEFAULT_MAX_SEARCH_BYTES
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    max_results: int = DEFAULT_MAX_RESULTS
    allow_public_http: bool = False

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_response_bytes < 1 or self.max_search_bytes < 1:
            raise ValueError("response limits must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        if self.max_results < 1 or self.max_results > 25:
            raise ValueError("max_results must be between 1 and 25")


@dataclass(frozen=True)
class FetchedReference:
    url: str
    title: str
    source: str
    content_type: str
    text: str
    html: str
    retrieved_at: str
    content_sha256: str
    byte_length: int


def _is_forbidden_ip(value: ipaddress._BaseAddress) -> bool:
    return bool(value.is_private or value.is_loopback or value.is_link_local or value.is_multicast or value.is_reserved or value.is_unspecified)


def _normalize_host(hostname: str) -> str:
    return hostname.rstrip(".").lower()


def _resolve_public_addresses(hostname: str) -> Tuple[str, ...]:
    host = _normalize_host(hostname)
    if not host or host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise WebResearchError("local hostnames are not valid web-research targets")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if _is_forbidden_ip(literal):
            raise WebResearchError("private or non-routable addresses are blocked")
        return (str(literal),)
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebResearchError("could not resolve target host") from exc
    resolved = []
    for answer in answers:
        raw = answer[4][0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if _is_forbidden_ip(address):
            raise WebResearchError("target resolves to a private or non-routable address")
        rendered = str(address)
        if rendered not in resolved:
            resolved.append(rendered)
    if not resolved:
        raise WebResearchError("target host has no usable public address")
    return tuple(resolved)


def validate_external_url(url: str, *, allow_public_http: bool = False, resolve: bool = True) -> str:
    if not isinstance(url, str) or not url.strip():
        raise WebResearchError("URL must be a non-empty string")
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise WebResearchError("only http and https URLs are supported")
    if scheme == "http" and not allow_public_http:
        raise WebResearchError("public HTTP is disabled; use HTTPS")
    if not parsed.hostname:
        raise WebResearchError("URL requires a host")
    host = _normalize_host(parsed.hostname)
    if host in _BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        raise WebResearchError("local hostnames are not valid web-research targets")
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None and _is_forbidden_ip(literal):
        raise WebResearchError("private or non-routable addresses are blocked")
    if parsed.username is not None or parsed.password is not None:
        raise WebResearchError("credential-bearing URLs are blocked")
    if parsed.fragment:
        parsed = parsed._replace(fragment="")
    if resolve and literal is None:
        _resolve_public_addresses(parsed.hostname)
    return urlunsplit(parsed)


def _content_type(headers: Mapping[str, str]) -> str:
    value = headers.get("Content-Type", "")
    return value.split(";", 1)[0].strip().lower()


def _bounded_read(response: Any, maximum: int) -> bytes:
    length_header = response.headers.get("Content-Length")
    if length_header:
        try:
            declared = int(length_header)
        except ValueError as exc:
            raise WebResearchError("invalid Content-Length") from exc
        if declared < 0 or declared > maximum:
            raise WebResearchError("response exceeds configured maximum")
    payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise WebResearchError("response exceeds configured maximum")
    return payload


def _decode_payload(payload: bytes, headers: Mapping[str, str]) -> str:
    content_type = headers.get("Content-Type", "")
    charset = "utf-8"
    match = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts = []  # type: List[str]
        self.text_parts = []  # type: List[str]
        self._suppressed = []  # type: List[str]
        self._title_depth = 0
        self.title_parts = []  # type: List[str]

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if self._suppressed:
            if tag in _STRIP_TAGS_WITH_CONTENT:
                self._suppressed.append(tag)
            return
        if tag in _STRIP_TAGS_WITH_CONTENT:
            self._suppressed.append(tag)
            return
        if tag == "title":
            self._title_depth += 1
            return
        if tag in _DROP_TAGS or tag not in _ALLOWED_TAGS:
            return
        if tag == "a":
            href = ""
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value.strip()
                    break
            if href.lower().startswith(("http://", "https://")):
                self.parts.append('<a href="%s">' % html.escape(href, quote=True))
            else:
                self.parts.append("<a>")
            return
        self.parts.append("<%s>" % tag)

    def handle_startendtag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in _VOID_TAGS and not self._suppressed:
            self.parts.append("<%s>" % tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._suppressed:
            if tag == self._suppressed[-1]:
                self._suppressed.pop()
            return
        if tag == "title":
            if self._title_depth:
                self._title_depth -= 1
            return
        if tag in _DROP_TAGS or tag not in _ALLOWED_TAGS or tag in _VOID_TAGS:
            return
        if tag == "a":
            self.parts.append("</a>")
            return
        self.parts.append("</%s>" % tag)

    def handle_data(self, data: str) -> None:
        if self._suppressed:
            return
        if self._title_depth:
            self.title_parts.append(data)
            return
        if not data:
            return
        self.parts.append(html.escape(data))
        if data.strip():
            self.text_parts.append(data)


def sanitize_html(document: str) -> Tuple[str, str, str]:
    parser = _Sanitizer()
    parser.feed(document)
    parser.close()
    sanitized = "".join(parser.parts).strip()
    plain_text = " ".join(" ".join(parser.text_parts).split())
    title = " ".join(" ".join(parser.title_parts).split())
    if not sanitized and plain_text:
        sanitized = "<p>%s</p>" % html.escape(plain_text)
    return sanitized, plain_text, title


class _GuardedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, policy: WebResearchPolicy) -> None:
        super().__init__()
        self.policy = policy

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Mapping[str, str], newurl: str) -> Optional[Request]:
        count = int(getattr(req, "_velour_redirect_count", 0)) + 1
        if count > self.policy.max_redirects:
            raise WebResearchError("redirect limit exceeded")
        resolved = urljoin(req.full_url, newurl)
        safe = validate_external_url(resolved, allow_public_http=self.policy.allow_public_http, resolve=True)
        redirected = Request(safe, headers={"User-Agent": req.headers.get("User-agent", "VelourResearch/1.0"), "Accept": req.headers.get("Accept", "text/html,text/plain;q=0.9"), "Connection": "close"}, method="GET")
        setattr(redirected, "_velour_redirect_count", count)
        return redirected


class GuardedWebFetcher:
    def __init__(self, policy: Optional[WebResearchPolicy] = None, opener: Any = None) -> None:
        self.policy = policy or WebResearchPolicy()
        self.opener = opener or build_opener(_GuardedRedirectHandler(self.policy))

    def fetch(self, url: str) -> FetchedReference:
        safe = validate_external_url(url, allow_public_http=self.policy.allow_public_http, resolve=True)
        request = Request(safe, headers={"User-Agent": "VelourResearch/1.0 (+reference-only)", "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9", "Connection": "close"}, method="GET")
        try:
            with self.opener.open(request, timeout=self.policy.timeout_seconds) as response:
                final_url = validate_external_url(response.geturl(), allow_public_http=self.policy.allow_public_http, resolve=True)
                kind = _content_type(response.headers)
                if kind not in _ALLOWED_DOCUMENT_TYPES:
                    raise WebResearchError("unsupported document content type: %s" % (kind or "unknown"))
                payload = _bounded_read(response, self.policy.max_response_bytes)
                text = _decode_payload(payload, response.headers)
        except HTTPError as exc:
            raise WebResearchError("web reference returned HTTP %d" % exc.code) from exc
        except URLError as exc:
            raise WebResearchError("web reference unavailable: %s" % exc.reason) from exc
        except TimeoutError as exc:
            raise WebResearchError("web reference timed out") from exc
        source = _normalize_host(urlsplit(final_url).hostname or "")
        if kind == "text/plain":
            plain = " ".join(text.split())
            sanitized = "<pre>%s</pre>" % html.escape(text)
            title = source
        else:
            sanitized, plain, parsed_title = sanitize_html(text)
            title = parsed_title or source
        if not plain.strip():
            raise WebResearchError("document contains no renderable reference text")
        return FetchedReference(url=final_url, title=title[:300], source=source, content_type=kind, text=plain, html=sanitized, retrieved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), content_sha256=hashlib.sha256(payload).hexdigest(), byte_length=len(payload))


class SearxngSearchProvider:
    """Bounded search against one explicit SearXNG JSON endpoint."""

    def __init__(self, endpoint: str, *, policy: Optional[WebResearchPolicy] = None, opener: Any = None, allow_loopback_endpoint: bool = False) -> None:
        self.policy = policy or WebResearchPolicy()
        self.allow_loopback_endpoint = bool(allow_loopback_endpoint)
        self.endpoint = self._validate_endpoint(endpoint)
        self.opener = opener or build_opener(_GuardedRedirectHandler(self.policy))

    def _validate_endpoint(self, endpoint: str) -> str:
        parsed = urlsplit(endpoint.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("search endpoint must be an http or https URL")
        host = _normalize_host(parsed.hostname)
        loopback = host in _BLOCKED_HOSTNAMES
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            address = None
        if address is not None and address.is_loopback:
            loopback = True
        if loopback:
            if not self.allow_loopback_endpoint:
                raise ValueError("loopback search endpoint requires explicit opt-in")
            return urlunsplit(parsed._replace(fragment=""))
        if parsed.scheme != "https" and not self.policy.allow_public_http:
            raise ValueError("remote search endpoint must use HTTPS")
        validate_external_url(urlunsplit(parsed._replace(fragment="")), allow_public_http=self.policy.allow_public_http, resolve=True)
        return urlunsplit(parsed._replace(fragment=""))

    def search(self, query: str) -> List[Dict[str, str]]:
        query = query.strip()
        if not query:
            raise WebResearchError("research query cannot be empty")
        if len(query) > 500:
            raise WebResearchError("research query is too long")
        parsed = urlsplit(self.endpoint)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params.update({"q": query, "format": "json", "categories": "general", "safesearch": "1"})
        target = urlunsplit(parsed._replace(query=urlencode(params)))
        request = Request(target, headers={"User-Agent": "VelourResearch/1.0 (+reference-only)", "Accept": "application/json", "Connection": "close"}, method="GET")
        try:
            with self.opener.open(request, timeout=self.policy.timeout_seconds) as response:
                kind = _content_type(response.headers)
                if kind not in _ALLOWED_SEARCH_TYPES:
                    raise WebResearchError("search provider returned unsupported content type")
                payload = _bounded_read(response, self.policy.max_search_bytes)
        except HTTPError as exc:
            raise WebResearchError("search provider returned HTTP %d" % exc.code) from exc
        except URLError as exc:
            raise WebResearchError("search provider unavailable: %s" % exc.reason) from exc
        except TimeoutError as exc:
            raise WebResearchError("search provider timed out") from exc
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebResearchError("search provider returned invalid JSON") from exc
        raw_results = document.get("results") if isinstance(document, dict) else None
        if not isinstance(raw_results, list):
            raise WebResearchError("search provider response is missing results")
        results = []
        for item in raw_results:
            if len(results) >= self.policy.max_results:
                break
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            try:
                safe_url = validate_external_url(url, allow_public_http=self.policy.allow_public_http, resolve=False)
            except WebResearchError:
                continue
            host = _normalize_host(urlsplit(safe_url).hostname or "")
            summary = str(item.get("content") or item.get("description") or "").strip()
            summary = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", summary)).split())
            result_id = hashlib.sha256(safe_url.encode("utf-8")).hexdigest()[:20]
            results.append({"result_id": result_id, "title": title[:300], "source": host, "url": safe_url, "summary": summary[:700]})
        return results


def _print_json(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Controlled Velour web-research adapter")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_RESPONSE_BYTES)
    parser.add_argument("--max-redirects", type=int, default=DEFAULT_MAX_REDIRECTS)
    parser.add_argument("--allow-public-http", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search", help="search through an explicit SearXNG JSON endpoint")
    search.add_argument("query")
    search.add_argument("--endpoint", required=True)
    search.add_argument("--limit", type=int, default=DEFAULT_MAX_RESULTS)
    search.add_argument("--allow-loopback-endpoint", action="store_true")
    fetch = sub.add_parser("fetch", help="fetch and sanitize one explicitly selected URL")
    fetch.add_argument("url")
    fetch.add_argument("--result-id", default="")
    fetch.add_argument("--title", default="")
    fetch.add_argument("--source", default="")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        policy = WebResearchPolicy(timeout_seconds=args.timeout, max_response_bytes=args.max_bytes, max_redirects=args.max_redirects, max_results=getattr(args, "limit", DEFAULT_MAX_RESULTS), allow_public_http=bool(args.allow_public_http))
        if args.command == "search":
            provider = SearxngSearchProvider(args.endpoint, policy=policy, allow_loopback_endpoint=bool(args.allow_loopback_endpoint))
            results = provider.search(args.query)
            _print_json({"schema": "velour.web_research.search.v1", "authority": "none", "external_reference": True, "query": args.query, "results": results})
            return 0
        reference = GuardedWebFetcher(policy).fetch(args.url)
        result_id = args.result_id.strip() or hashlib.sha256(reference.url.encode("utf-8")).hexdigest()[:20]
        _print_json({"schema": "velour.web_research.document.v1", "authority": "none", "external_reference": True, "result_id": result_id, "title": args.title.strip() or reference.title, "source": args.source.strip() or reference.source, "url": reference.url, "text": reference.text, "html": reference.html, "retrieved_at": reference.retrieved_at, "content_sha256": reference.content_sha256, "content_type": reference.content_type, "byte_length": reference.byte_length})
        return 0
    except (ValueError, WebResearchError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
