"""Core archive, catalog, provenance, search, and verification for Velour's Library."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union
from uuid import uuid4

_TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml", ".toml", ".ini", ".log"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_TRUST_CLASSES = {"primary", "scholarly", "secondary", "community", "owner", "generated", "unknown"}


@dataclass(frozen=True)
class LibraryItem:
    item_id: str
    title: str
    source: str
    source_uri: Optional[str]
    trust_class: str
    media_type: str
    language: str
    sha256: str
    storage_path: str
    extracted_text_path: Optional[str]
    imported_at: str
    published_at: Optional[str]
    rights_note: Optional[str]
    tags: Tuple[str, ...]


@dataclass(frozen=True)
class SearchResult:
    item_id: str
    title: str
    source: str
    trust_class: str
    sha256: str
    score: float
    snippet: str


class Library:
    """A shared, model-independent offline library for the Velvet ecosystem."""

    def __init__(self, root: Union[str, Path]) -> None:
        self.root = Path(root)
        self.catalog_dir = self.root / "catalog"
        self.archive_dir = self.root / "archive" / "sha256"
        self.text_dir = self.root / "indexes" / "text"
        self.receipts_dir = self.root / "receipts"
        self.db_path = self.catalog_dir / "library.sqlite3"
        self.receipt_path = self.receipts_dir / "library-events.jsonl"
        self._fts5 = False
        self._prepare()

    def _prepare(self) -> None:
        for path in (self.catalog_dir, self.archive_dir, self.text_dir, self.receipts_dir):
            path.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS items (
                    item_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_uri TEXT,
                    trust_class TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    language TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    extracted_text_path TEXT,
                    imported_at TEXT NOT NULL,
                    published_at TEXT,
                    rights_note TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_items_sha256 ON items(sha256);
                CREATE INDEX IF NOT EXISTS idx_items_title ON items(title);
                CREATE TABLE IF NOT EXISTS tags (
                    item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
                    tag TEXT NOT NULL,
                    PRIMARY KEY (item_id, tag)
                );
                """
            )
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS item_fts USING fts5(item_id UNINDEXED, title, source, tags, body)"
                )
                self._fts5 = True
            except sqlite3.OperationalError:
                self._fts5 = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def add(
        self,
        source_file: Union[str, Path],
        *,
        title: str,
        source: str,
        source_uri: Optional[str] = None,
        trust_class: str = "unknown",
        language: str = "en",
        published_at: Optional[str] = None,
        rights_note: Optional[str] = None,
        tags: Iterable[str] = (),
    ) -> LibraryItem:
        src = Path(source_file)
        if not src.is_file():
            raise FileNotFoundError(str(src))
        if not title.strip() or not source.strip():
            raise ValueError("title and source are required")
        trust_class = trust_class.strip().lower() or "unknown"
        if trust_class not in _TRUST_CLASSES:
            raise ValueError("unknown trust class: %s" % trust_class)

        sha256 = self._sha256(src)
        storage_path = self.archive_dir / sha256[:2] / sha256
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not storage_path.exists():
            shutil.copy2(str(src), str(storage_path))
        elif self._sha256(storage_path) != sha256:
            raise RuntimeError("archive hash collision or corrupted canonical object")

        item_id = "lib_%s" % uuid4().hex
        extracted_path = self._extract_text(src, item_id)
        media_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
        imported_at = self._utc_now()
        clean_tags = tuple(sorted({str(tag).strip() for tag in tags if str(tag).strip()}))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO items (
                    item_id, title, source, source_uri, trust_class, media_type, language,
                    sha256, storage_path, extracted_text_path, imported_at, published_at, rights_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    title.strip(),
                    source.strip(),
                    source_uri.strip() if source_uri else None,
                    trust_class,
                    media_type,
                    language.strip() or "en",
                    sha256,
                    str(storage_path),
                    str(extracted_path) if extracted_path else None,
                    imported_at,
                    published_at,
                    rights_note,
                ),
            )
            conn.executemany("INSERT INTO tags(item_id, tag) VALUES (?, ?)", [(item_id, tag) for tag in clean_tags])
            if self._fts5:
                body = extracted_path.read_text(encoding="utf-8", errors="replace") if extracted_path else ""
                conn.execute(
                    "INSERT INTO item_fts(item_id, title, source, tags, body) VALUES (?, ?, ?, ?, ?)",
                    (item_id, title.strip(), source.strip(), " ".join(clean_tags), body),
                )

        item = self.inspect(item_id)
        self._write_event("add", item, {"source_file": str(src.resolve())})
        return item

    def inspect(self, identifier: str) -> LibraryItem:
        identifier = identifier.strip()
        if not identifier:
            raise KeyError("empty identifier")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM items
                WHERE item_id = ? OR item_id LIKE ? OR sha256 = ? OR sha256 LIKE ?
                ORDER BY item_id
                """,
                (identifier, identifier + "%", identifier, identifier + "%"),
            ).fetchall()
            if not rows:
                raise KeyError(identifier)
            exact = [row for row in rows if row["item_id"] == identifier or row["sha256"] == identifier]
            if exact:
                row = exact[0]
            elif len(rows) == 1:
                row = rows[0]
            else:
                raise KeyError("ambiguous identifier: %s" % identifier)
            tags = tuple(r[0] for r in conn.execute("SELECT tag FROM tags WHERE item_id = ? ORDER BY tag", (row["item_id"],)))
        return self._row_to_item(row, tags)

    def list_items(self) -> List[LibraryItem]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM items ORDER BY imported_at, item_id").fetchall()
            result = []
            for row in rows:
                tags = tuple(r[0] for r in conn.execute("SELECT tag FROM tags WHERE item_id = ? ORDER BY tag", (row["item_id"],)))
                result.append(self._row_to_item(row, tags))
            return result

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        terms = [token.lower() for token in _TOKEN_RE.findall(query)]
        if not terms or limit <= 0:
            return []
        if self._fts5:
            try:
                return self._search_fts(terms, limit)
            except sqlite3.OperationalError:
                pass
        return self._search_fallback(terms, limit)

    def _search_fts(self, terms: Sequence[str], limit: int) -> List[SearchResult]:
        match = " AND ".join('\"%s\"' % term.replace('\"', '\"\"') for term in terms)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT f.item_id, f.title, f.source, i.trust_class, i.sha256,
                       bm25(item_fts, 0.0, 5.0, 4.0, 3.0, 1.0) AS rank,
                       snippet(item_fts, 4, '', '', ' … ', 24) AS snippet
                FROM item_fts AS f
                JOIN items AS i ON i.item_id = f.item_id
                WHERE item_fts MATCH ?
                ORDER BY rank ASC, f.title COLLATE NOCASE ASC, f.item_id ASC
                LIMIT ?
                """,
                (match, limit),
            ).fetchall()
        return [
            SearchResult(
                item_id=row["item_id"],
                title=row["title"],
                source=row["source"],
                trust_class=row["trust_class"],
                sha256=row["sha256"],
                score=float(-row["rank"]),
                snippet=" ".join((row["snippet"] or "").split()),
            )
            for row in rows
        ]

    def _search_fallback(self, terms: Sequence[str], limit: int) -> List[SearchResult]:
        results = []
        for item in self.list_items():
            metadata = " ".join((item.title, item.source, item.trust_class, " ".join(item.tags))).lower()
            body = ""
            if item.extracted_text_path:
                path = Path(item.extracted_text_path)
                if path.is_file():
                    body = path.read_text(encoding="utf-8", errors="replace").lower()
            score = float(sum(metadata.count(term) * 5 + body.count(term) for term in terms))
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    item_id=item.item_id,
                    title=item.title,
                    source=item.source,
                    trust_class=item.trust_class,
                    sha256=item.sha256,
                    score=score,
                    snippet=self._snippet(body or metadata, terms),
                )
            )
        results.sort(key=lambda result: (-result.score, result.title.lower(), result.item_id))
        return results[:limit]

    def verify(self, identifier: str) -> bool:
        item = self.inspect(identifier)
        path = Path(item.storage_path)
        valid = path.is_file() and self._sha256(path) == item.sha256
        self._write_event("verify", item, {"valid": valid})
        return valid

    def remove(self, identifier: str) -> LibraryItem:
        item = self.inspect(identifier)
        with self._connect() as conn:
            if self._fts5:
                conn.execute("DELETE FROM item_fts WHERE item_id = ?", (item.item_id,))
            conn.execute("DELETE FROM items WHERE item_id = ?", (item.item_id,))
            remaining = conn.execute("SELECT COUNT(*) FROM items WHERE sha256 = ?", (item.sha256,)).fetchone()[0]

        if item.extracted_text_path:
            path = Path(item.extracted_text_path)
            if path.is_file():
                path.unlink()
        if remaining == 0:
            payload = Path(item.storage_path)
            if payload.is_file():
                payload.unlink()
        self._write_event("remove", item, {"canonical_payload_removed": remaining == 0})
        return item

    def _extract_text(self, source: Path, item_id: str) -> Optional[Path]:
        suffix = source.suffix.lower()
        text = None
        if suffix in _TEXT_EXTENSIONS:
            text = source.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            text = self._extract_pdf(source)
        if text is None:
            return None
        destination = self.text_dir / (item_id + ".txt")
        destination.write_text(text, encoding="utf-8")
        return destination

    @staticmethod
    def _extract_pdf(source: Path) -> Optional[str]:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return None
        reader = PdfReader(str(source))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n\n".join(parts)

    def _write_event(self, action: str, item: LibraryItem, details: Optional[dict] = None) -> None:
        event = {
            "event_id": "lev_%s" % uuid4().hex,
            "timestamp": self._utc_now(),
            "action": action,
            "item_id": item.item_id,
            "sha256": item.sha256,
            "canonical_receipt": False,
            "receipt_scope": "velours_library_local_evidence",
            "details": details or {},
        }
        with self.receipt_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    @staticmethod
    def _row_to_item(row: sqlite3.Row, tags: Tuple[str, ...]) -> LibraryItem:
        return LibraryItem(
            item_id=row["item_id"],
            title=row["title"],
            source=row["source"],
            source_uri=row["source_uri"],
            trust_class=row["trust_class"],
            media_type=row["media_type"],
            language=row["language"],
            sha256=row["sha256"],
            storage_path=row["storage_path"],
            extracted_text_path=row["extracted_text_path"],
            imported_at=row["imported_at"],
            published_at=row["published_at"],
            rights_note=row["rights_note"],
            tags=tags,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _snippet(text: str, terms: Sequence[str], width: int = 220) -> str:
        positions = [text.find(term) for term in terms if term in text]
        first = min(positions) if positions else 0
        start = max(0, first - width // 3)
        return " ".join(text[start : start + width].split())
