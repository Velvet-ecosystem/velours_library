"""External Kiwix/ZIM shelf for very large offline reference archives.

ZIM archives are intentionally *not* copied into the Library's SHA-addressed
canonical object store.  Multi-gigabyte encyclopedias are managed as a bounded
external shelf under the Library root and served read-only by ``kiwix-serve``.
This prevents a 90 GB Wikipedia file from being duplicated merely to make it
available offline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

_SPLIT_ROOT_RE = re.compile(r"\.zimaa$", re.IGNORECASE)
_SPLIT_PART_RE = re.compile(r"\.zim[a-z]{2}$", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ZimArchive:
    root_path: str
    parts: List[str]
    total_bytes: int
    hashes: Optional[Dict[str, str]] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "root_path": self.root_path,
            "parts": list(self.parts),
            "part_count": len(self.parts),
            "total_bytes": self.total_bytes,
            "sha256_parts": dict(self.hashes) if self.hashes is not None else None,
        }


class ZimShelf:
    """Inventory and safely launch a read-only Kiwix server for local ZIMs."""

    def __init__(self, library_root: Path) -> None:
        self.library_root = Path(library_root)
        self.shelf_dir = self.library_root / "external" / "zim"
        self.catalog_dir = self.library_root / "catalog"
        self.inventory_path = self.catalog_dir / "zim-shelf.json"

    def prepare(self) -> None:
        self.shelf_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_dir.mkdir(parents=True, exist_ok=True)

    def _root_files(self) -> List[Path]:
        if not self.shelf_dir.is_dir():
            return []
        roots: List[Path] = []
        for path in sorted(self.shelf_dir.rglob("*")):
            if not path.is_file():
                continue
            lowered = path.name.lower()
            if lowered.endswith(".zim") or _SPLIT_ROOT_RE.search(lowered):
                roots.append(path)
        return roots

    @staticmethod
    def _parts(root: Path) -> List[Path]:
        if root.name.lower().endswith(".zim"):
            return [root]
        if not _SPLIT_ROOT_RE.search(root.name):
            return [root]
        prefix = root.name[:-2]
        parts = [
            path for path in sorted(root.parent.iterdir())
            if path.is_file() and path.name.startswith(prefix) and _SPLIT_PART_RE.search(path.name.lower())
        ]
        return parts or [root]

    def scan(self, *, hash_files: bool = False) -> List[ZimArchive]:
        archives: List[ZimArchive] = []
        for root in self._root_files():
            parts = self._parts(root)
            hashes = None
            if hash_files:
                hashes = {str(path.relative_to(self.library_root)): _sha256(path) for path in parts}
            archives.append(ZimArchive(
                root_path=str(root.relative_to(self.library_root)),
                parts=[str(path.relative_to(self.library_root)) for path in parts],
                total_bytes=sum(path.stat().st_size for path in parts),
                hashes=hashes,
            ))
        return archives

    def write_inventory(self, *, hash_files: bool = False) -> Dict[str, object]:
        self.prepare()
        archives = self.scan(hash_files=hash_files)
        payload = {
            "schema": "velour.zim-shelf.v1",
            "generated_at": _utc_now(),
            "library_root": str(self.library_root),
            "archives": [archive.as_dict() for archive in archives],
            "hashes_included": bool(hash_files),
            "read_only_reference_shelf": True,
            "canonical_receipt": False,
            "authority": "none",
        }
        temporary = self.inventory_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.inventory_path)
        return payload

    def status(self) -> Dict[str, object]:
        archives = self.scan(hash_files=False)
        executable = shutil.which("kiwix-serve")
        return {
            "shelf": str(self.shelf_dir),
            "archive_count": len(archives),
            "total_bytes": sum(archive.total_bytes for archive in archives),
            "kiwix_serve": executable,
            "ready": bool(executable and archives),
            "default_bind": "127.0.0.1",
            "read_only_reference_shelf": True,
            "authority": "none",
        }

    def serve_command(
        self,
        *,
        address: str = "127.0.0.1",
        port: int = 8080,
        threads: int = 4,
        search_limit: int = 0,
        block_external: bool = True,
        allow_network: bool = False,
    ) -> List[str]:
        executable = shutil.which("kiwix-serve")
        if not executable:
            raise RuntimeError("kiwix-serve is not installed")
        roots = self._root_files()
        if not roots:
            raise RuntimeError("no ZIM archives found under %s" % self.shelf_dir)
        if address not in {"127.0.0.1", "::1", "localhost"} and not allow_network:
            raise ValueError("non-loopback Kiwix binding requires explicit --allow-network")
        if not 1 <= int(port) <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if int(threads) < 1:
            raise ValueError("threads must be positive")
        if int(search_limit) < 0:
            raise ValueError("search limit cannot be negative")
        command = [
            executable,
            "--address=%s" % address,
            "--port=%d" % int(port),
            "--threads=%d" % int(threads),
            "--searchLimit=%d" % int(search_limit),
        ]
        if block_external:
            command.append("--blockexternal")
        command.extend(str(path) for path in roots)
        return command

    def serve(self, **kwargs: object) -> None:
        command = self.serve_command(**kwargs)
        os.execv(command[0], command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour-zim", description="Manage Velour's external Kiwix/ZIM reference shelf")
    parser.add_argument("--root", default="library-data")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create the external ZIM shelf directories")
    sub.add_parser("status", help="Report installed ZIMs and kiwix-serve availability")
    inventory = sub.add_parser("inventory", help="Write a deterministic local ZIM shelf inventory")
    inventory.add_argument("--hash", action="store_true", help="SHA-256 every ZIM part; expensive for large archives")
    serve = sub.add_parser("serve", help="Run kiwix-serve against the local shelf")
    serve.add_argument("--address", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--threads", type=int, default=4)
    serve.add_argument("--search-limit", type=int, default=0)
    serve.add_argument("--allow-network", action="store_true", help="Permit binding beyond loopback")
    serve.add_argument("--allow-external-links", action="store_true", help="Do not ask Kiwix to block direct external navigation")
    serve.add_argument("--print-command", action="store_true", help="Show the fixed argv without starting the server")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    shelf = ZimShelf(Path(args.root))
    try:
        if args.command == "init":
            shelf.prepare(); print(str(shelf.shelf_dir)); return 0
        if args.command == "status":
            print(json.dumps(shelf.status(), indent=2, sort_keys=True)); return 0
        if args.command == "inventory":
            print(json.dumps(shelf.write_inventory(hash_files=args.hash), indent=2, sort_keys=True)); return 0
        if args.command == "serve":
            kwargs = {
                "address": args.address,
                "port": args.port,
                "threads": args.threads,
                "search_limit": args.search_limit,
                "block_external": not args.allow_external_links,
                "allow_network": args.allow_network,
            }
            command = shelf.serve_command(**kwargs)
            if args.print_command:
                print(json.dumps(command)); return 0
            os.execv(command[0], command)
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc)); return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
