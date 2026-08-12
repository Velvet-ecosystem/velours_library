"""Core archive, catalog, provenance, quarantine, and retrieval evidence for Velour's Library."""
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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union
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
class Candidate:
    candidate_id: str
    title: str
    source: str
    source_uri: Optional[str]
    trust_class: str
    language: str
    sha256: str
    staged_path: str
    staged_at: str
    state: str
    published_at: Optional[str]
    rights_note: Optional[str]
    tags: Tuple[str, ...]
    rejection_reason: Optional[str]


@dataclass(frozen=True)
class EvidenceResult:
    result_id: str
    item_id: str
    chunk_id: Optional[str]
    title: str
    source: str
    source_uri: Optional[str]
    trust_class: str
    sha256: str
    score: float
    snippet: str
    retrieval_method: str
    location: Dict[str, object]
    reference_only: bool = True
    canonical_receipt: bool = False


@dataclass(frozen=True)
class SearchResult:
    item_id: str
    title: str
    source: str
    trust_class: str
    sha256: str
    score: float
    snippet: str
    chunk_id: Optional[str] = None
    retrieval_method: str = "metadata"
    location: Optional[Dict[str, object]] = None


class Library:
    """A shared, model-independent offline library for the Velvet ecosystem."""

    def __init__(
        self,
        root: Union[str, Path],
        *,
        max_file_bytes: int = 256 * 1024 * 1024,
        max_extract_bytes: int = 16 * 1024 * 1024,
        max_pdf_bytes: int = 64 * 1024 * 1024,
        chunk_lines: int = 40,
    ) -> None:
        self.root = Path(root)
        self.catalog_dir = self.root / "catalog"
        self.incoming_dir = self.root / "incoming"
        self.archive_dir = self.root / "archive" / "sha256"
        self.text_dir = self.root / "indexes" / "text"
        self.receipts_dir = self.root / "receipts"
        self.db_path = self.catalog_dir / "library.sqlite3"
        self.receipt_path = self.receipts_dir / "library-events.jsonl"
        self.max_file_bytes = max_file_bytes
        self.max_extract_bytes = max_extract_bytes
        self.max_pdf_bytes = max_pdf_bytes
        self.chunk_lines = max(1, int(chunk_lines))
        self._fts5 = False
        self._prepare()

    def _prepare(self) -> None:
        for path in (self.catalog_dir, self.incoming_dir, self.archive_dir, self.text_dir, self.receipts_dir):
            path.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS items(
                    item_id TEXT PRIMARY KEY,title TEXT NOT NULL,source TEXT NOT NULL,source_uri TEXT,
                    trust_class TEXT NOT NULL,media_type TEXT NOT NULL,language TEXT NOT NULL,
                    sha256 TEXT NOT NULL,storage_path TEXT NOT NULL,extracted_text_path TEXT,
                    imported_at TEXT NOT NULL,published_at TEXT,rights_note TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_items_sha256 ON items(sha256);
                CREATE TABLE IF NOT EXISTS tags(
                    item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
                    tag TEXT NOT NULL,PRIMARY KEY(item_id,tag)
                );
                CREATE TABLE IF NOT EXISTS candidates(
                    candidate_id TEXT PRIMARY KEY,title TEXT NOT NULL,source TEXT NOT NULL,source_uri TEXT,
                    trust_class TEXT NOT NULL,language TEXT NOT NULL,sha256 TEXT NOT NULL,staged_path TEXT NOT NULL,
                    staged_at TEXT NOT NULL,state TEXT NOT NULL,published_at TEXT,rights_note TEXT,
                    tags_json TEXT NOT NULL,rejection_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_sha256 ON candidates(sha256);
                CREATE TABLE IF NOT EXISTS chunks(
                    item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
                    chunk_id TEXT NOT NULL,ordinal INTEGER NOT NULL,body TEXT NOT NULL,
                    location_json TEXT NOT NULL,text_sha256 TEXT NOT NULL,
                    PRIMARY KEY(item_id,chunk_id)
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_item_ordinal ON chunks(item_id,ordinal);
                """
            )
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING "
                    "fts5(item_id UNINDEXED,chunk_id UNINDEXED,title,source,tags,body)"
                )
                self._fts5 = True
            except sqlite3.OperationalError:
                self._fts5 = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def stage(
        self,
        source_file: Union[str, Path],
        *,
        title: str,
        source: str,
        source_uri: Optional[str] = None,
        trust_class: str = "unknown",
        language: str = "en",
        rights_note: Optional[str] = None,
        tags: Iterable[str] = (),
    ) -> Candidate:
        src = Path(source_file)
        if not src.is_file():
            raise FileNotFoundError(str(src))
        if not title.strip() or not source.strip():
            raise ValueError("title and source are required")
        size = src.stat().st_size
        if size > self.max_file_bytes:
            raise ValueError("source exceeds max_file_bytes")
        trust_class = trust_class.strip().lower() or "unknown"
        if trust_class not in _TRUST_CLASSES:
            raise ValueError("unknown trust class: %s" % trust_class)
        sha = self._sha256(src)
        candidate_id = "cand_%s" % uuid4().hex
        staged = self.incoming_dir / (candidate_id + src.suffix.lower())
        shutil.copy2(str(src), str(staged))
        clean_tags = tuple(sorted({str(tag).strip() for tag in tags if str(tag).strip()}))
        now = self._utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO candidates(
                    candidate_id,title,source,source_uri,trust_class,language,sha256,staged_path,staged_at,
                    state,published_at,rights_note,tags_json,rejection_reason
                ) VALUES(?,?,?,?,?,?,?,?,?,'staged',NULL,?,?,NULL)""",
                (
                    candidate_id,title.strip(),source.strip(),source_uri.strip() if source_uri else None,
                    trust_class,language.strip() or "en",sha,str(staged),now,rights_note,json.dumps(clean_tags),
                ),
            )
        candidate = self.inspect_candidate(candidate_id)
        self._write_candidate_event("stage", candidate, {"source_file": str(src.resolve()), "bytes": size})
        return candidate

    def publish(self, candidate_id: str, *, published_at: Optional[str] = None) -> LibraryItem:
        candidate = self.inspect_candidate(candidate_id)
        if candidate.state != "staged":
            raise ValueError("candidate is not staged")
        staged = Path(candidate.staged_path)
        if not staged.is_file():
            raise RuntimeError("staged payload missing")
        if self._sha256(staged) != candidate.sha256:
            raise RuntimeError("staged payload checksum mismatch")
        storage = self.archive_dir / candidate.sha256[:2] / candidate.sha256
        storage.parent.mkdir(parents=True, exist_ok=True)
        if not storage.exists():
            shutil.copy2(str(staged), str(storage))
        elif self._sha256(storage) != candidate.sha256:
            raise RuntimeError("archive hash collision or corrupted canonical object")

        item_id = "lib_%s" % uuid4().hex
        extracted = self._extract_text(staged, item_id)
        media = mimetypes.guess_type(staged.name)[0] or "application/octet-stream"
        if self._detect_suffix(staged) == ".pdf":
            media = "application/pdf"
        now = self._utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO items(
                    item_id,title,source,source_uri,trust_class,media_type,language,sha256,storage_path,
                    extracted_text_path,imported_at,published_at,rights_note
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item_id,candidate.title,candidate.source,candidate.source_uri,candidate.trust_class,media,
                    candidate.language,candidate.sha256,str(storage),str(extracted) if extracted else None,
                    now,published_at,candidate.rights_note,
                ),
            )
            conn.executemany("INSERT INTO tags(item_id,tag) VALUES(?,?)", [(item_id, tag) for tag in candidate.tags])
            conn.execute("UPDATE candidates SET state='published',published_at=? WHERE candidate_id=?", (now, candidate.candidate_id))
        staged.unlink(missing_ok=True)
        item = self.inspect(item_id)
        self._index_item(item)
        self._write_event("publish", item, {"candidate_id": candidate.candidate_id})
        return item

    def reject(self, candidate_id: str, reason: str) -> Candidate:
        candidate = self.inspect_candidate(candidate_id)
        if candidate.state != "staged":
            raise ValueError("candidate is not staged")
        Path(candidate.staged_path).unlink(missing_ok=True)
        with self._connect() as conn:
            conn.execute(
                "UPDATE candidates SET state='rejected',rejection_reason=? WHERE candidate_id=?",
                (reason.strip() or "rejected", candidate.candidate_id),
            )
        updated = self.inspect_candidate(candidate.candidate_id)
        self._write_candidate_event("reject", updated, {"reason": updated.rejection_reason})
        return updated

    def add(self, source_file: Union[str, Path], **kwargs) -> LibraryItem:
        published_at = kwargs.pop("published_at", None)
        candidate = self.stage(source_file, **kwargs)
        return self.publish(candidate.candidate_id, published_at=published_at)

    def inspect_candidate(self, identifier: str) -> Candidate:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM candidates WHERE candidate_id=? OR candidate_id LIKE ? OR sha256=? OR sha256 LIKE ? ORDER BY candidate_id",
                (identifier, identifier + "%", identifier, identifier + "%"),
            ).fetchall()
        if not rows:
            raise KeyError(identifier)
        exact = [row for row in rows if row["candidate_id"] == identifier or row["sha256"] == identifier]
        row = exact[0] if exact else rows[0] if len(rows) == 1 else None
        if row is None:
            raise KeyError("ambiguous identifier: %s" % identifier)
        return self._row_to_candidate(row)

    def list_candidates(self, state: Optional[str] = None) -> List[Candidate]:
        with self._connect() as conn:
            query = "SELECT * FROM candidates" + (" WHERE state=?" if state else "") + " ORDER BY staged_at,candidate_id"
            rows = conn.execute(query, (state,) if state else ()).fetchall()
        return [self._row_to_candidate(row) for row in rows]

    def inspect(self, identifier: str) -> LibraryItem:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM items WHERE item_id=? OR item_id LIKE ? OR sha256=? OR sha256 LIKE ? ORDER BY item_id",
                (identifier, identifier + "%", identifier, identifier + "%"),
            ).fetchall()
            if not rows:
                raise KeyError(identifier)
            exact = [row for row in rows if row["item_id"] == identifier or row["sha256"] == identifier]
            row = exact[0] if exact else rows[0] if len(rows) == 1 else None
            if row is None:
                raise KeyError("ambiguous identifier: %s" % identifier)
            tags = tuple(r[0] for r in conn.execute("SELECT tag FROM tags WHERE item_id=? ORDER BY tag", (row["item_id"],)))
        return self._row_to_item(row, tags)

    def list_items(self) -> List[LibraryItem]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM items ORDER BY imported_at,item_id").fetchall()
            items = []
            for row in rows:
                tags = tuple(r[0] for r in conn.execute("SELECT tag FROM tags WHERE item_id=? ORDER BY tag", (row["item_id"],)))
                items.append(self._row_to_item(row, tags))
        return items

    def evidence(self, query: str, limit: int = 10) -> List[EvidenceResult]:
        terms = [token.lower() for token in _TOKEN_RE.findall(query)]
        if not terms or limit <= 0:
            return []
        chunk_results = self._evidence_chunks(terms, limit)
        if len(chunk_results) >= limit:
            return chunk_results[:limit]
        seen_items = {result.item_id for result in chunk_results}
        metadata_results = self._evidence_metadata(terms, limit - len(chunk_results), seen_items)
        return (chunk_results + metadata_results)[:limit]

    def evidence_bundle(self, query: str, limit: int = 10) -> Dict[str, object]:
        results = self.evidence(query, limit)
        return {
            "query_id": "q_%s" % uuid4().hex,
            "query": query,
            "reference_only": True,
            "canonical_receipt": False,
            "results": [self._evidence_to_dict(result) for result in results],
        }

    def search(self, query: str, limit: int = 10) -> List[SearchResult]:
        return [
            SearchResult(
                item_id=result.item_id,
                title=result.title,
                source=result.source,
                trust_class=result.trust_class,
                sha256=result.sha256,
                score=result.score,
                snippet=result.snippet,
                chunk_id=result.chunk_id,
                retrieval_method=result.retrieval_method,
                location=result.location,
            )
            for result in self.evidence(query, limit)
        ]

    def reindex(self, identifier: Optional[str] = None) -> int:
        items = [self.inspect(identifier)] if identifier else self.list_items()
        total = 0
        for item in items:
            total += self._index_item(item)
        return total

    def _index_item(self, item: LibraryItem) -> int:
        chunks = self._build_chunks(item)
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE item_id=?", (item.item_id,))
            if self._fts5:
                conn.execute("DELETE FROM chunk_fts WHERE item_id=?", (item.item_id,))
            for ordinal, chunk_id, body, location, text_sha in chunks:
                conn.execute(
                    "INSERT INTO chunks(item_id,chunk_id,ordinal,body,location_json,text_sha256) VALUES(?,?,?,?,?,?)",
                    (item.item_id, chunk_id, ordinal, body, json.dumps(location, sort_keys=True), text_sha),
                )
                if self._fts5:
                    conn.execute(
                        "INSERT INTO chunk_fts(item_id,chunk_id,title,source,tags,body) VALUES(?,?,?,?,?,?)",
                        (item.item_id, chunk_id, item.title, item.source, " ".join(item.tags), body),
                    )
        return len(chunks)

    def _build_chunks(self, item: LibraryItem) -> List[Tuple[int, str, str, Dict[str, object], str]]:
        if not item.extracted_text_path:
            return []
        path = Path(item.extracted_text_path)
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks: List[Tuple[int, str, str, Dict[str, object], str]] = []
        ordinal = 0
        if item.media_type == "application/pdf" or "\f" in text:
            for page_number, page_text in enumerate(text.split("\f"), start=1):
                clean = page_text.strip()
                if not clean:
                    continue
                text_sha = hashlib.sha256(clean.encode("utf-8")).hexdigest()
                chunk_id = self._chunk_id(item.sha256, "page:%d" % page_number, text_sha)
                chunks.append((ordinal, chunk_id, clean, {"kind": "page", "page": page_number}, text_sha))
                ordinal += 1
            return chunks

        lines = text.splitlines()
        for start in range(0, len(lines), self.chunk_lines):
            end = min(len(lines), start + self.chunk_lines)
            body = "\n".join(lines[start:end]).strip()
            if not body:
                continue
            text_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
            location = {"kind": "lines", "start_line": start + 1, "end_line": end}
            chunk_id = self._chunk_id(item.sha256, "lines:%d-%d" % (start + 1, end), text_sha)
            chunks.append((ordinal, chunk_id, body, location, text_sha))
            ordinal += 1
        return chunks

    def _evidence_chunks(self, terms: Sequence[str], limit: int) -> List[EvidenceResult]:
        if self._fts5:
            try:
                match = " AND ".join('\"%s\"' % term.replace('\"', '\"\"') for term in terms)
                with self._connect() as conn:
                    rows = conn.execute(
                        """SELECT f.item_id,f.chunk_id,i.title,i.source,i.source_uri,i.trust_class,i.sha256,
                                  bm25(chunk_fts,0.0,0.0,5.0,4.0,3.0,1.0) rank,
                                  snippet(chunk_fts,5,'','',' … ',28) snippet,c.location_json
                           FROM chunk_fts f JOIN items i ON i.item_id=f.item_id
                           JOIN chunks c ON c.item_id=f.item_id AND c.chunk_id=f.chunk_id
                           WHERE chunk_fts MATCH ?
                           ORDER BY rank ASC,i.title COLLATE NOCASE ASC,f.item_id,f.chunk_id LIMIT ?""",
                        (match, limit),
                    ).fetchall()
                return [
                    EvidenceResult(
                        result_id="r_%s" % uuid4().hex,
                        item_id=row["item_id"],chunk_id=row["chunk_id"],title=row["title"],source=row["source"],
                        source_uri=row["source_uri"],trust_class=row["trust_class"],sha256=row["sha256"],
                        score=float(-row["rank"]),snippet=" ".join((row["snippet"] or "").split()),
                        retrieval_method="full_text_fts5",location=json.loads(row["location_json"]),
                    )
                    for row in rows
                ]
            except sqlite3.OperationalError:
                pass

        results: List[EvidenceResult] = []
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT c.*,i.title,i.source,i.source_uri,i.trust_class,i.sha256
                   FROM chunks c JOIN items i ON i.item_id=c.item_id
                   ORDER BY i.title COLLATE NOCASE,c.ordinal,c.chunk_id"""
            ).fetchall()
        for row in rows:
            body = row["body"].lower()
            score = float(sum(body.count(term) for term in terms))
            if score <= 0:
                continue
            results.append(
                EvidenceResult(
                    result_id="r_%s" % uuid4().hex,item_id=row["item_id"],chunk_id=row["chunk_id"],
                    title=row["title"],source=row["source"],source_uri=row["source_uri"],
                    trust_class=row["trust_class"],sha256=row["sha256"],score=score,
                    snippet=self._snippet(body, terms),retrieval_method="full_text_deterministic",
                    location=json.loads(row["location_json"]),
                )
            )
        results.sort(key=lambda result: (-result.score, result.title.lower(), result.item_id, result.chunk_id or ""))
        return results[:limit]

    def _evidence_metadata(self, terms: Sequence[str], limit: int, seen_items: set) -> List[EvidenceResult]:
        results: List[EvidenceResult] = []
        for item in self.list_items():
            if item.item_id in seen_items:
                continue
            metadata = " ".join((item.title, item.source, item.trust_class, " ".join(item.tags))).lower()
            score = float(sum(metadata.count(term) * 5 for term in terms))
            if score <= 0:
                continue
            results.append(
                EvidenceResult(
                    result_id="r_%s" % uuid4().hex,item_id=item.item_id,chunk_id=None,title=item.title,
                    source=item.source,source_uri=item.source_uri,trust_class=item.trust_class,sha256=item.sha256,
                    score=score,snippet=self._snippet(metadata, terms),retrieval_method="metadata",
                    location={"kind": "metadata"},
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
                conn.execute("DELETE FROM chunk_fts WHERE item_id=?", (item.item_id,))
            conn.execute("DELETE FROM items WHERE item_id=?", (item.item_id,))
            remaining = conn.execute("SELECT COUNT(*) FROM items WHERE sha256=?", (item.sha256,)).fetchone()[0]
        if item.extracted_text_path:
            Path(item.extracted_text_path).unlink(missing_ok=True)
        if remaining == 0:
            Path(item.storage_path).unlink(missing_ok=True)
        self._write_event("remove", item, {"canonical_payload_removed": remaining == 0})
        return item

    def _extract_text(self, source: Path, item_id: str) -> Optional[Path]:
        size = source.stat().st_size
        suffix = self._detect_suffix(source)
        if size > self.max_extract_bytes and suffix != ".pdf":
            return None
        text: Optional[str] = None
        if suffix in _TEXT_EXTENSIONS:
            text = source.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            if size > self.max_pdf_bytes:
                return None
            pages = self._extract_pdf_pages(source)
            if pages is not None:
                text = "\f".join(pages)
        if text is None:
            return None
        destination = self.text_dir / (item_id + ".txt")
        destination.write_text(text, encoding="utf-8")
        return destination

    @staticmethod
    def _detect_suffix(source: Path) -> str:
        try:
            with source.open("rb") as handle:
                head = handle.read(5)
        except OSError:
            return source.suffix.lower()
        if head == b"%PDF-":
            return ".pdf"
        return source.suffix.lower()

    @staticmethod
    def _extract_pdf_pages(source: Path) -> Optional[List[str]]:
        try:
            from pypdf import PdfReader  # type: ignore
        except ImportError:
            return None
        reader = PdfReader(str(source))
        return [(page.extract_text() or "") for page in reader.pages]

    def _write_event(self, action: str, item: LibraryItem, details: Optional[dict] = None) -> None:
        self._append_event({
            "event_id": "lev_%s" % uuid4().hex,"timestamp": self._utc_now(),"action": action,
            "item_id": item.item_id,"sha256": item.sha256,"canonical_receipt": False,
            "receipt_scope": "velours_library_local_evidence","details": details or {},
        })

    def _write_candidate_event(self, action: str, candidate: Candidate, details: Optional[dict] = None) -> None:
        self._append_event({
            "event_id": "lev_%s" % uuid4().hex,"timestamp": self._utc_now(),"action": action,
            "candidate_id": candidate.candidate_id,"sha256": candidate.sha256,"canonical_receipt": False,
            "receipt_scope": "velours_library_local_evidence","details": details or {},
        })

    def _append_event(self, event: dict) -> None:
        with self.receipt_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    @staticmethod
    def _row_to_item(row: sqlite3.Row, tags: Tuple[str, ...]) -> LibraryItem:
        return LibraryItem(
            row["item_id"],row["title"],row["source"],row["source_uri"],row["trust_class"],row["media_type"],
            row["language"],row["sha256"],row["storage_path"],row["extracted_text_path"],row["imported_at"],
            row["published_at"],row["rights_note"],tags,
        )

    @staticmethod
    def _row_to_candidate(row: sqlite3.Row) -> Candidate:
        return Candidate(
            row["candidate_id"],row["title"],row["source"],row["source_uri"],row["trust_class"],row["language"],
            row["sha256"],row["staged_path"],row["staged_at"],row["state"],row["published_at"],row["rights_note"],
            tuple(json.loads(row["tags_json"])),row["rejection_reason"],
        )

    @staticmethod
    def _evidence_to_dict(result: EvidenceResult) -> Dict[str, object]:
        return {
            "result_id": result.result_id,"item_id": result.item_id,"chunk_id": result.chunk_id,
            "title": result.title,"source": result.source,"source_uri": result.source_uri,
            "trust_class": result.trust_class,"sha256": result.sha256,"score": result.score,
            "snippet": result.snippet,"retrieval_method": result.retrieval_method,"location": result.location,
            "reference_only": result.reference_only,"canonical_receipt": result.canonical_receipt,
        }

    @staticmethod
    def _chunk_id(source_sha256: str, location_key: str, text_sha256: str) -> str:
        digest = hashlib.sha256((source_sha256 + "|" + location_key + "|" + text_sha256).encode("utf-8")).hexdigest()
        return "chk_%s" % digest[:24]

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
        return " ".join(text[start:start + width].split())
