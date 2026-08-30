"""Small standard-library client for read-only remote Velour Library retrieval."""
from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .retrieval_service import NODE_ID_RE


class RemoteLibraryError(RuntimeError):
    """Raised when a remote Library request cannot be completed safely."""


class RemoteLibraryClient:
    def __init__(
        self,
        base_url: str,
        *,
        node_id: str,
        token: str,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        base_url = base_url.strip().rstrip("/")
        if not (base_url.startswith("http://") or base_url.startswith("https://")):
            raise ValueError("base_url must use http or https")
        if not NODE_ID_RE.fullmatch(node_id):
            raise ValueError("invalid node_id")
        if len(token.strip()) < 24:
            raise ValueError("token is too short")
        if timeout_seconds <= 0 or max_response_bytes < 1:
            raise ValueError("client limits must be positive")
        self.base_url = base_url
        self.node_id = node_id
        self.token = token.strip()
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)

    @classmethod
    def from_token_file(
        cls,
        base_url: str,
        *,
        node_id: str,
        token_file: Path,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2 * 1024 * 1024,
    ) -> "RemoteLibraryClient":
        path = Path(token_file).expanduser()
        if path.is_symlink() or not path.is_file():
            raise ValueError("token file must be a regular non-symlink file")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ValueError("token file must not be accessible by group or other users")
        token = path.read_text(encoding="utf-8").strip()
        return cls(
            base_url,
            node_id=node_id,
            token=token,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )

    def health(self) -> Dict[str, Any]:
        request = Request(self.base_url + "/v1/health", method="GET")
        return self._send(request)

    def search(self, query: str, limit: int = 10) -> Dict[str, Any]:
        return self._post("/v1/search", query, limit)

    def evidence(self, query: str, limit: int = 10) -> Dict[str, Any]:
        return self._post("/v1/evidence", query, limit)

    def _post(self, path: str, query: str, limit: int) -> Dict[str, Any]:
        document = {"query": query, "limit": limit}
        payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=payload,
            method="POST",
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "X-Velvet-Node-ID": self.node_id,
            },
        )
        return self._send(request)

    def _send(self, request: Request) -> Dict[str, Any]:
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                length_header = response.headers.get("Content-Length")
                if length_header:
                    try:
                        declared = int(length_header)
                    except ValueError as exc:
                        raise RemoteLibraryError("invalid response Content-Length") from exc
                    if declared > self.max_response_bytes:
                        raise RemoteLibraryError("response exceeds client maximum")
                payload = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise RemoteLibraryError("remote Library returned HTTP %d: %s" % (exc.code, detail)) from exc
        except URLError as exc:
            raise RemoteLibraryError("remote Library unavailable: %s" % exc.reason) from exc
        if len(payload) > self.max_response_bytes:
            raise RemoteLibraryError("response exceeds client maximum")
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteLibraryError("remote Library returned invalid JSON") from exc
        if not isinstance(document, dict):
            raise RemoteLibraryError("remote Library response must be a JSON object")
        return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query a remote read-only Velour Library")
    parser.add_argument("--url", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    for name in ("search", "evidence"):
        command = sub.add_parser(name)
        command.add_argument("query")
        command.add_argument("--limit", type=int, default=10)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        client = RemoteLibraryClient.from_token_file(
            args.url,
            node_id=args.node_id,
            token_file=Path(args.token_file),
            timeout_seconds=args.timeout,
        )
        if args.command == "health":
            result = client.health()
        elif args.command == "search":
            result = client.search(args.query, args.limit)
        else:
            result = client.evidence(args.query, args.limit)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, RemoteLibraryError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
