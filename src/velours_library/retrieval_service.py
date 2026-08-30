"""Read-only network retrieval boundary for Velour's Library.

This service exposes published Library search/evidence to approved remote nodes.
It never exposes the SQLite database, archive paths, staged candidates, ingestion,
publication, deletion, acquisition, or execution authority.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import stat
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from uuid import uuid4

from .catalog import Library

SERVICE_SCHEMA = "velours.library.remote-retrieval.v1"
SEARCH_SCHEMA = "velours.library.remote-search.v1"
EVIDENCE_SCHEMA = "velours.library.remote-evidence.v1"
AUDIT_SCHEMA = "velours.library.remote-retrieval-audit.v1"
NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_MAX_REQUEST_BYTES = 16 * 1024
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_QUERY_CHARS = 512
DEFAULT_MAX_RESULTS = 50


class RetrievalServiceError(ValueError):
    """Raised when retrieval service configuration or input is invalid."""


class PeerSecretStore:
    """Deployment-local per-node bearer secrets.

    Each approved node has one file named ``<node_id>.token``. Files must be
    regular, non-symlink files and must not be readable/writable/executable by
    group or other users. The secret directory itself is deployment state and
    must never be committed to the Library repository.
    """

    def __init__(self, root: Path) -> None:
        raw = Path(root).expanduser()
        if raw.is_symlink():
            raise RetrievalServiceError("peer secret directory must not be a symlink")
        self.root = raw.resolve()
        if not self.root.is_dir():
            raise RetrievalServiceError("peer secret directory does not exist")
        try:
            mode = stat.S_IMODE(self.root.stat().st_mode)
        except OSError as exc:
            raise RetrievalServiceError("cannot inspect peer secret directory") from exc
        if mode & 0o077:
            raise RetrievalServiceError("peer secret directory must not be accessible by group or other users")

    def token_for(self, node_id: str) -> Optional[str]:
        if not NODE_ID_RE.fullmatch(node_id):
            return None
        path = self.root / (node_id + ".token")
        try:
            if path.is_symlink() or not path.is_file():
                return None
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                return None
            token = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if len(token) < 24 or len(token) > 4096:
            return None
        return token


class RetrievalAudit:
    """Privacy-minimal local audit log for remote retrieval requests."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(
        self,
        *,
        query_id: str,
        node_id: str,
        endpoint: str,
        query: str,
        limit: int,
        result_count: int,
        status: str,
    ) -> None:
        record = {
            "schema": AUDIT_SCHEMA,
            "query_id": query_id,
            "node_id": node_id,
            "endpoint": endpoint,
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "limit": limit,
            "result_count": result_count,
            "status": status,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "raw_query_recorded": False,
            "authority": "none",
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()


def _json_bytes(document: Dict[str, Any], max_bytes: int) -> bytes:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > max_bytes:
        raise RetrievalServiceError("response exceeds configured maximum")
    return payload


def _parse_query(document: Any, max_query_chars: int, max_results: int) -> tuple[str, int]:
    if not isinstance(document, dict):
        raise RetrievalServiceError("request body must be a JSON object")
    unknown = set(document) - {"query", "limit"}
    if unknown:
        raise RetrievalServiceError("unknown request fields: %s" % ", ".join(sorted(unknown)))
    query = document.get("query")
    if not isinstance(query, str) or not query.strip():
        raise RetrievalServiceError("query must be a non-empty string")
    query = query.strip()
    if len(query) > max_query_chars:
        raise RetrievalServiceError("query exceeds configured character limit")
    limit = document.get("limit", 10)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= max_results:
        raise RetrievalServiceError("limit must be an integer between 1 and %d" % max_results)
    return query, limit


def build_handler(
    library: Library,
    secrets: PeerSecretStore,
    audit: RetrievalAudit,
    *,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    max_query_chars: int = DEFAULT_MAX_QUERY_CHARS,
    max_results: int = DEFAULT_MAX_RESULTS,
):
    """Build an HTTP handler bound to one Library and deployment secret store."""

    class RetrievalHandler(BaseHTTPRequestHandler):
        server_version = "VelourReadOnlyRetrieval/1.0"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _send(self, status: int, document: Dict[str, Any]) -> None:
            try:
                payload = _json_bytes(document, max_response_bytes)
            except RetrievalServiceError:
                status = 413
                payload = b'{"error":"response_too_large"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def _authenticate(self) -> Optional[str]:
            node_id = (self.headers.get("X-Velvet-Node-ID") or "").strip()
            auth = self.headers.get("Authorization") or ""
            if not auth.startswith("Bearer "):
                return None
            supplied = auth[7:].strip()
            expected = secrets.token_for(node_id)
            if expected is None or not supplied:
                return None
            if not hmac.compare_digest(supplied, expected):
                return None
            return node_id

        def _audit_failure(self, query_id: str, node_id: str, query: str, limit: int, status: str) -> None:
            try:
                audit.write(
                    query_id=query_id,
                    node_id=node_id,
                    endpoint=self.path,
                    query=query,
                    limit=limit,
                    result_count=0,
                    status=status,
                )
            except OSError:
                pass

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/v1/health":
                self._send(404, {"error": "not_found"})
                return
            self._send(
                200,
                {
                    "schema": SERVICE_SCHEMA,
                    "service": "velours-library-remote-retrieval",
                    "status": "ok",
                    "read_only": True,
                    "reference_only": True,
                    "authority": "none",
                },
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in {"/v1/search", "/v1/evidence"}:
                self._send(404, {"error": "not_found"})
                return
            node_id = self._authenticate()
            if node_id is None:
                self._send(401, {"error": "unauthorized"})
                return
            content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self._send(415, {"error": "content_type_must_be_application_json"})
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                self._send(400, {"error": "invalid_content_length"})
                return
            if length < 1 or length > max_request_bytes:
                self._send(413, {"error": "request_size_out_of_bounds"})
                return
            raw = self.rfile.read(length)
            try:
                document = json.loads(raw.decode("utf-8"))
                query, limit = _parse_query(document, max_query_chars, max_results)
            except (UnicodeDecodeError, json.JSONDecodeError, RetrievalServiceError) as exc:
                self._send(400, {"error": "invalid_request", "detail": str(exc)})
                return

            query_id = "rq_%s" % uuid4().hex
            try:
                if self.path == "/v1/search":
                    results = library.search(query, limit)
                    response = {
                        "schema": SEARCH_SCHEMA,
                        "query_id": query_id,
                        "node_id": node_id,
                        "read_only": True,
                        "reference_only": True,
                        "authority": "none",
                        "results": [asdict(result) for result in results],
                    }
                    result_count = len(results)
                else:
                    bundle = library.evidence_bundle(query, limit)
                    results_raw = bundle.get("results", []) if isinstance(bundle, dict) else []
                    response = {
                        "schema": EVIDENCE_SCHEMA,
                        "query_id": query_id,
                        "node_id": node_id,
                        "read_only": True,
                        "reference_only": True,
                        "authority": "none",
                        "evidence": bundle,
                    }
                    result_count = len(results_raw) if isinstance(results_raw, list) else 0
                audit.write(
                    query_id=query_id,
                    node_id=node_id,
                    endpoint=self.path,
                    query=query,
                    limit=limit,
                    result_count=result_count,
                    status="ok",
                )
                self._send(200, response)
            except (ValueError, KeyError, RuntimeError):
                self._audit_failure(query_id, node_id, query, limit, "failed")
                self._send(400, {"error": "retrieval_failed", "query_id": query_id})
            except Exception:
                self._audit_failure(query_id, node_id, query, limit, "internal_error")
                self._send(500, {"error": "retrieval_internal_error", "query_id": query_id})

    return RetrievalHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve Velour Library evidence read-only to approved nodes")
    parser.add_argument("--root", default="library-data")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--peer-secret-dir", required=True)
    parser.add_argument("--audit-path")
    parser.add_argument("--max-request-bytes", type=int, default=DEFAULT_MAX_REQUEST_BYTES)
    parser.add_argument("--max-response-bytes", type=int, default=DEFAULT_MAX_RESPONSE_BYTES)
    parser.add_argument("--max-query-chars", type=int, default=DEFAULT_MAX_QUERY_CHARS)
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")
    if min(args.max_request_bytes, args.max_response_bytes, args.max_query_chars, args.max_results) < 1:
        raise SystemExit("service limits must be positive")
    library = Library(Path(args.root))
    secrets = PeerSecretStore(Path(args.peer_secret_dir))
    audit_path = Path(args.audit_path) if args.audit_path else Path(args.root) / "audit" / "remote-retrieval.jsonl"
    audit = RetrievalAudit(audit_path)
    handler = build_handler(
        library,
        secrets,
        audit,
        max_request_bytes=args.max_request_bytes,
        max_response_bytes=args.max_response_bytes,
        max_query_chars=args.max_query_chars,
        max_results=args.max_results,
    )
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
