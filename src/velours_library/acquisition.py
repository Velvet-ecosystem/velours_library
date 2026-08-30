"""Governed network acquisition for Velour's Library.

The acquisition layer delivers approved remote resources to the existing
Library staging boundary. It never publishes, raises trust, or grants authority.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import mimetypes
import os
import socket
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .catalog import Candidate, Library


POLICY_SCHEMA = "velours.library.acquisition-policy.v1"
RECORD_SCHEMA = "velours.library.acquisition-record.v1"
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_USER_AGENT = "VelourLibraryAcquisition/1.0"


class AcquisitionError(ValueError):
    """Raised when a remote acquisition is denied or fails validation."""


@dataclass(frozen=True)
class SourceRule:
    rule_id: str
    origin: str
    path_prefix: str
    source_label: str
    trust_class: str = "unknown"
    allowed_content_types: Tuple[str, ...] = ()
    allow_private_network: bool = False
    rights_note: Optional[str] = None
    tags: Tuple[str, ...] = ()
    max_bytes: Optional[int] = None


@dataclass(frozen=True)
class AcquisitionRecord:
    acquisition_id: str
    candidate_id: str
    requested_url: str
    final_url: str
    source_rule_id: str
    source_label: str
    trust_class: str
    acquired_at: str
    sha256: str
    bytes: int
    content_type: str
    http_status: int
    etag: Optional[str]
    last_modified: Optional[str]
    authority: str = "none"
    schema: str = RECORD_SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "acquisition_id": self.acquisition_id,
            "candidate_id": self.candidate_id,
            "requested_url": self.requested_url,
            "final_url": self.final_url,
            "source_rule_id": self.source_rule_id,
            "source_label": self.source_label,
            "trust_class": self.trust_class,
            "acquired_at": self.acquired_at,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "content_type": self.content_type,
            "http_status": self.http_status,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "authority": self.authority,
        }


class SourcePolicy:
    """Strict allow-list for acquisition sources."""

    def __init__(
        self,
        rules: Sequence[SourceRule],
        *,
        default_max_bytes: int = DEFAULT_MAX_BYTES,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        if not rules:
            raise AcquisitionError("acquisition policy requires at least one source rule")
        if default_max_bytes < 1:
            raise AcquisitionError("default_max_bytes must be positive")
        self.rules = tuple(rules)
        self.default_max_bytes = int(default_max_bytes)
        self.user_agent = str(user_agent).strip() or DEFAULT_USER_AGENT

    @classmethod
    def load(cls, path: Path) -> "SourcePolicy":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, Mapping):
            raise AcquisitionError("acquisition policy root must be an object")
        if document.get("schema") != POLICY_SCHEMA:
            raise AcquisitionError("unsupported acquisition policy schema")
        allowed_top = {"schema", "default_max_bytes", "user_agent", "sources"}
        unknown = set(document) - allowed_top
        if unknown:
            raise AcquisitionError("unknown acquisition policy fields: %s" % ", ".join(sorted(unknown)))
        raw_sources = document.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise AcquisitionError("sources must be a non-empty list")
        rules = [cls._parse_rule(item) for item in raw_sources]
        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise AcquisitionError("source rule ids must be unique")
        return cls(
            rules,
            default_max_bytes=_positive_int(document.get("default_max_bytes", DEFAULT_MAX_BYTES), "default_max_bytes"),
            user_agent=str(document.get("user_agent", DEFAULT_USER_AGENT)),
        )

    @staticmethod
    def _parse_rule(value: Any) -> SourceRule:
        if not isinstance(value, Mapping):
            raise AcquisitionError("each source rule must be an object")
        allowed = {
            "id", "origin", "path_prefix", "source_label", "trust_class",
            "allowed_content_types", "allow_private_network", "rights_note",
            "tags", "max_bytes",
        }
        unknown = set(value) - allowed
        if unknown:
            raise AcquisitionError("unknown source rule fields: %s" % ", ".join(sorted(unknown)))
        rule_id = _required_text(value, "id")
        origin = _canonical_origin(_required_text(value, "origin"))
        parsed_origin = urlsplit(origin)
        if parsed_origin.scheme not in {"https", "http"}:
            raise AcquisitionError("source origin must use http or https")
        path_prefix = str(value.get("path_prefix", "/")).strip() or "/"
        if not path_prefix.startswith("/"):
            raise AcquisitionError("path_prefix must begin with /")
        content_types = _text_tuple(value.get("allowed_content_types", ()), "allowed_content_types")
        tags = _text_tuple(value.get("tags", ()), "tags")
        max_bytes_raw = value.get("max_bytes")
        max_bytes = None if max_bytes_raw is None else _positive_int(max_bytes_raw, "max_bytes")
        private = value.get("allow_private_network", False)
        if not isinstance(private, bool):
            raise AcquisitionError("allow_private_network must be boolean")
        return SourceRule(
            rule_id=rule_id,
            origin=origin,
            path_prefix=path_prefix,
            source_label=_required_text(value, "source_label"),
            trust_class=str(value.get("trust_class", "unknown")).strip().lower() or "unknown",
            allowed_content_types=content_types,
            allow_private_network=private,
            rights_note=(str(value["rights_note"]).strip() if value.get("rights_note") is not None else None),
            tags=tags,
            max_bytes=max_bytes,
        )

    def match(self, url: str) -> SourceRule:
        canonical = _canonical_url(url)
        parts = urlsplit(canonical)
        origin = _canonical_origin(canonical)
        for rule in self.rules:
            if origin != rule.origin:
                continue
            if _path_matches(parts.path or "/", rule.path_prefix):
                return rule
        raise AcquisitionError("URL is not approved by acquisition policy")


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    def __init__(self, validator: Callable[[str], None]) -> None:
        super().__init__()
        self._validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        self._validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class AcquisitionManager:
    """Fetch one approved resource and hand it to ``Library.stage``."""

    def __init__(
        self,
        library: Library,
        policy: SourcePolicy,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        opener: Any = None,
        resolver: Optional[Callable[[str], Iterable[str]]] = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise AcquisitionError("timeout_seconds must be positive")
        self.library = library
        self.policy = policy
        self.timeout_seconds = float(timeout_seconds)
        self._resolver = resolver or _resolve_host
        self._opener = opener
        self.acquisition_dir = self.library.root / "acquisition"
        self.receipt_path = self.library.receipts_dir / "acquisition-events.jsonl"
        self.acquisition_dir.mkdir(parents=True, exist_ok=True)
        self.library.receipts_dir.mkdir(parents=True, exist_ok=True)

    def authorize(self, url: str) -> SourceRule:
        canonical = _canonical_url(url)
        rule = self.policy.match(canonical)
        host = urlsplit(canonical).hostname
        if not host:
            raise AcquisitionError("URL hostname is required")
        addresses = tuple(self._resolver(host))
        if not addresses:
            raise AcquisitionError("source hostname did not resolve")
        if not rule.allow_private_network:
            for address in addresses:
                if _is_nonpublic_address(address):
                    raise AcquisitionError("source resolves to a non-public address")
        return rule

    def acquire(
        self,
        url: str,
        *,
        title: str,
        language: str = "en",
        tags: Iterable[str] = (),
        version_label: Optional[str] = None,
        stale_after: Optional[str] = None,
        supersedes_item_id: Optional[str] = None,
        expected_sha256: Optional[str] = None,
    ) -> Tuple[Candidate, AcquisitionRecord]:
        if not str(title).strip():
            raise AcquisitionError("title is required")
        requested_url = _canonical_url(url)
        initial_rule = self.authorize(requested_url)

        def validate_redirect(target: str) -> None:
            self.authorize(target)

        opener = self._opener or build_opener(_ValidatingRedirectHandler(validate_redirect))
        request = Request(
            requested_url,
            headers={
                "User-Agent": self.policy.user_agent,
                "Accept": "*/*",
                "Cache-Control": "no-cache",
            },
            method="GET",
        )

        with opener.open(request, timeout=self.timeout_seconds) as response:
            final_url = _canonical_url(response.geturl() if hasattr(response, "geturl") else requested_url)
            final_rule = self.authorize(final_url)
            status = int(getattr(response, "status", 200) or 200)
            if status < 200 or status >= 300:
                raise AcquisitionError("source returned HTTP status %s" % status)
            headers = getattr(response, "headers", {})
            content_type = _normalize_content_type(_header(headers, "Content-Type"))
            if final_rule.allowed_content_types and not _content_type_allowed(
                content_type, final_rule.allowed_content_types
            ):
                raise AcquisitionError("content type is not approved by source rule")
            max_bytes = final_rule.max_bytes or self.policy.default_max_bytes
            max_bytes = min(max_bytes, self.library.max_file_bytes)
            declared_length = _parse_content_length(_header(headers, "Content-Length"))
            if declared_length is not None and declared_length > max_bytes:
                raise AcquisitionError("declared content length exceeds acquisition limit")

            suffix = _safe_suffix(final_url, content_type)
            digest = hashlib.sha256()
            total = 0
            tmp_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix="velour-acquire-",
                    suffix=suffix,
                    dir=str(self.acquisition_dir),
                    delete=False,
                ) as handle:
                    tmp_path = Path(handle.name)
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise AcquisitionError("download exceeds acquisition limit")
                        digest.update(chunk)
                        handle.write(chunk)
                sha256 = digest.hexdigest()
                if expected_sha256:
                    expected = str(expected_sha256).strip().lower()
                    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
                        raise AcquisitionError("expected_sha256 must be 64 lowercase hexadecimal characters")
                    if sha256 != expected:
                        raise AcquisitionError("download checksum does not match expected_sha256")

                merged_tags = tuple(sorted(set(final_rule.tags) | {str(tag).strip() for tag in tags if str(tag).strip()}))
                candidate = self.library.stage(
                    tmp_path,
                    title=str(title).strip(),
                    source=final_rule.source_label,
                    source_uri=final_url,
                    trust_class=final_rule.trust_class,
                    language=str(language).strip() or "en",
                    rights_note=final_rule.rights_note,
                    tags=merged_tags,
                    version_label=version_label,
                    stale_after=stale_after,
                    supersedes_item_id=supersedes_item_id,
                )
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)

        acquired_at = _utc_now()
        acquisition_id = "acq_%s" % hashlib.sha256(
            (candidate.candidate_id + requested_url + acquired_at).encode("utf-8")
        ).hexdigest()[:24]
        record = AcquisitionRecord(
            acquisition_id=acquisition_id,
            candidate_id=candidate.candidate_id,
            requested_url=requested_url,
            final_url=final_url,
            source_rule_id=final_rule.rule_id,
            source_label=final_rule.source_label,
            trust_class=final_rule.trust_class,
            acquired_at=acquired_at,
            sha256=sha256,
            bytes=total,
            content_type=content_type,
            http_status=status,
            etag=_header(headers, "ETag"),
            last_modified=_header(headers, "Last-Modified"),
        )
        self._write_record(record)
        return candidate, record

    def list_records(self) -> List[Dict[str, Any]]:
        if not self.receipt_path.is_file():
            return []
        records: List[Dict[str, Any]] = []
        for line in self.receipt_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict) and value.get("schema") == RECORD_SCHEMA:
                records.append(value)
        return records

    def _write_record(self, record: AcquisitionRecord) -> None:
        line = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        with self.receipt_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass


def _canonical_url(value: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise AcquisitionError("URL is required")
    parts = urlsplit(raw)
    if parts.scheme.lower() not in {"https", "http"}:
        raise AcquisitionError("only http and https acquisition URLs are supported")
    if not parts.hostname:
        raise AcquisitionError("URL hostname is required")
    if parts.username is not None or parts.password is not None:
        raise AcquisitionError("credentials are not permitted in acquisition URLs")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    port = parts.port
    default_port = 443 if parts.scheme.lower() == "https" else 80
    netloc = host if port in (None, default_port) else "%s:%d" % (host, port)
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def _canonical_origin(value: str) -> str:
    parts = urlsplit(_canonical_url(value))
    return "%s://%s" % (parts.scheme, parts.netloc)


def _path_matches(path: str, prefix: str) -> bool:
    if prefix == "/":
        return True
    if path == prefix:
        return True
    normalized = prefix.rstrip("/") + "/"
    return path.startswith(normalized)


def _resolve_host(host: str) -> Iterable[str]:
    results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    seen = set()
    for item in results:
        address = item[4][0]
        if address not in seen:
            seen.add(address)
            yield address


def _is_nonpublic_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _normalize_content_type(value: Optional[str]) -> str:
    if not value:
        return "application/octet-stream"
    return value.split(";", 1)[0].strip().lower() or "application/octet-stream"


def _content_type_allowed(content_type: str, allowed: Sequence[str]) -> bool:
    for pattern in allowed:
        p = pattern.strip().lower()
        if p == "*/*" or p == content_type:
            return True
        if p.endswith("/*") and content_type.startswith(p[:-1]):
            return True
    return False


def _safe_suffix(url: str, content_type: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix and len(suffix) <= 12 and suffix[1:].replace("-", "").isalnum():
        return suffix
    guessed = mimetypes.guess_extension(content_type) or ""
    if guessed and len(guessed) <= 12:
        return guessed
    return ".bin"


def _header(headers: Any, name: str) -> Optional[str]:
    if hasattr(headers, "get"):
        value = headers.get(name)
        return str(value).strip() if value is not None and str(value).strip() else None
    return None


def _parse_content_length(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise AcquisitionError("invalid Content-Length header")
    if result < 0:
        raise AcquisitionError("invalid Content-Length header")
    return result


def _required_text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AcquisitionError("%s must be a non-empty string" % key)
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise AcquisitionError("%s must be a positive integer" % label)
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise AcquisitionError("%s must be a positive integer" % label)
    if result < 1:
        raise AcquisitionError("%s must be a positive integer" % label)
    return result


def _text_tuple(value: Any, label: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise AcquisitionError("%s must be a list" % label)
    result = tuple(str(item).strip() for item in value if str(item).strip())
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Acquire approved remote material into Velour's staging dock")
    parser.add_argument("--root", default="./library-data")
    parser.add_argument("--policy", required=True, help="local acquisition policy JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate whether a URL is approved")
    check.add_argument("url")

    fetch = sub.add_parser("fetch", help="download one approved resource and stage it")
    fetch.add_argument("url")
    fetch.add_argument("--title", required=True)
    fetch.add_argument("--language", default="en")
    fetch.add_argument("--tag", action="append", default=[])
    fetch.add_argument("--version")
    fetch.add_argument("--stale-after")
    fetch.add_argument("--supersedes")
    fetch.add_argument("--sha256", dest="expected_sha256")

    sub.add_parser("records", help="show acquisition records")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    library = Library(Path(args.root))
    policy = SourcePolicy.load(Path(args.policy))
    manager = AcquisitionManager(library, policy)

    if args.command == "check":
        rule = manager.authorize(args.url)
        print(json.dumps({"approved": True, "rule_id": rule.rule_id, "source": rule.source_label}, indent=2))
        return 0
    if args.command == "records":
        print(json.dumps(manager.list_records(), indent=2, sort_keys=True))
        return 0
    if args.command == "fetch":
        candidate, record = manager.acquire(
            args.url,
            title=args.title,
            language=args.language,
            tags=args.tag,
            version_label=args.version,
            stale_after=args.stale_after,
            supersedes_item_id=args.supersedes,
            expected_sha256=args.expected_sha256,
        )
        print(json.dumps({
            "candidate_id": candidate.candidate_id,
            "candidate_state": candidate.state,
            "acquisition": record.to_dict(),
            "published": False,
        }, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
