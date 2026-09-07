# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed command wrapper for the production Velvet vault mount."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .filesystem_identity import FilesystemIdentityError, verified_filesystem
from .vault import DEFAULT_VAULT_ROOT, _production_root, main as vault_main


def _selected_root(argv: Sequence[str]) -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("VELVET_VAULT_ROOT", str(DEFAULT_VAULT_ROOT))),
    )
    parsed, _ = parser.parse_known_args(list(argv))
    return parsed.root.expanduser()


def _is_production_root(path: Path) -> bool:
    return _production_root(path)


def _selected_uuid(argv: Sequence[str]) -> Optional[str]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--expected-filesystem-uuid", default=os.environ.get("VELVET_VAULT_FILESYSTEM_UUID"))
    parsed, _ = parser.parse_known_args(list(argv))
    return parsed.expected_filesystem_uuid


def main(argv: Optional[Sequence[str]] = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)

    # Help must remain available even when the vault is physically absent.
    if "-h" in values or "--help" in values:
        return vault_main(values)

    root = _selected_root(values)
    expected_uuid = _selected_uuid(values)
    try:
        if _is_production_root(root) or expected_uuid is not None:
            with verified_filesystem(root, expected_uuid):
                return vault_main(values)
        return vault_main(values)
    except FilesystemIdentityError as exc:
        print(
            json.dumps(
                {
                    "schema": "velvet.vault.preflight.v1",
                    "state": "vault-unavailable",
                    "reason": str(exc),
                    "root": str(root),
                    "authority": "none",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
