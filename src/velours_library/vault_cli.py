# SPDX-License-Identifier: GPL-3.0-only
"""Fail-closed command wrapper for the production Velvet vault mount."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .vault import DEFAULT_VAULT_ROOT, main as vault_main


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
    return path.resolve(strict=False) == DEFAULT_VAULT_ROOT.resolve(strict=False)


def main(argv: Optional[Sequence[str]] = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)

    # Help must remain available even when the vault is physically absent.
    if "-h" in values or "--help" in values:
        return vault_main(values)

    root = _selected_root(values)
    if _is_production_root(root) and not os.path.ismount(str(root)):
        print(
            json.dumps(
                {
                    "schema": "velvet.vault.preflight.v1",
                    "state": "vault-unavailable",
                    "reason": "production-root-not-mounted",
                    "root": str(root),
                    "authority": "none",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3

    return vault_main(values)


if __name__ == "__main__":
    raise SystemExit(main())
