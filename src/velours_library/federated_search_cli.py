"""Failure-isolated CLI wrapper for Velour's federated reference search."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .catalog import Library
from .federated_search import (
    FederatedSearchEngine,
    FederatedSearchError,
    KiwixSearchProvider,
    build_parser,
)
from .web_research import SearxngSearchProvider, WebResearchError, WebResearchPolicy


class _UnavailableLibrary:
    """Duck-typed Library seam that reports an unavailable local shelf."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason)[:300]

    def evidence(self, query: str, limit: int):
        raise OSError(self.reason)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        try:
            library = Library(Path(args.root))
        except (OSError, RuntimeError, ValueError) as exc:
            library = _UnavailableLibrary("Library unavailable at %s: %s" % (args.root, exc))

        kiwix = (
            KiwixSearchProvider(args.kiwix_endpoint, timeout_seconds=args.timeout)
            if args.kiwix_endpoint
            else None
        )
        web = None
        if args.web_endpoint:
            policy = WebResearchPolicy(timeout_seconds=args.timeout, max_results=args.limit)
            web = SearxngSearchProvider(
                args.web_endpoint,
                policy=policy,
                allow_loopback_endpoint=bool(args.allow_loopback_web),
            )

        payload = FederatedSearchEngine(
            library,
            kiwix_provider=kiwix,
            web_provider=web,
        ).search(args.query, args.limit)
        if isinstance(library, _UnavailableLibrary):
            payload["sources"]["library"]["status"] = "unavailable"
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, FederatedSearchError, WebResearchError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
