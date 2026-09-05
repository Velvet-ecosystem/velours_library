"""Guarded bulk document ingestion and richer local extraction.

This module deliberately feeds the existing ``Library.stage() -> publish()``
boundary instead of creating a second catalog or bypassing review.  Canonical
source bytes remain owned by :mod:`velours_library.catalog`; the helpers here
only discover batches, derive conservative metadata, and provide optional
search-text extraction for formats the minimal Library does not understand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote

from .catalog import Candidate, Library, LibraryItem

_TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml", ".toml", ".ini", ".log"}
_HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
_OFFICE_EXTENSIONS = {".docx", ".odt", ".epub"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED_DOCUMENT_EXTENSIONS = _TEXT_EXTENSIONS | _HTML_EXTENSIONS | _OFFICE_EXTENSIONS | _IMAGE_EXTENSIONS | {".pdf"}
SIDECAR_SUFFIX = ".velour.json"
_SIDECAR_FIELDS = {
    "ignore",
    "title",
    "source",
    "source_uri",
    "trust",
    "trust_class",
    "language",
    "rights_note",
    "tags",
    "version",
    "version_label",
    "stale_after",
    "supersedes",
    "supersedes_item_id",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_title(stem: str) -> str:
    value = re.sub(r"[_]+", " ", stem).strip()
    return value or stem


def _safe_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _xml_first_text(root: ET.Element, names: Set[str]) -> Optional[str]:
    for node in root.iter():
        if _local_name(node.tag) in names:
            text = _safe_text(node.text)
            if text:
                return text
    return None


class _HTMLTextParser(HTMLParser):
    _BLOCK = {
        "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "figure",
        "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol",
        "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
    _SKIP = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        HTMLParser.__init__(self, convert_charrefs=True)
        self.parts: List[str] = []
        self.skip_depth = 0
        self.title_parts: List[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if lowered == "title":
            self.in_title = True
        if lowered in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in self._SKIP:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if lowered == "title":
            self.in_title = False
        if lowered in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        if data:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = []
        for line in raw.splitlines():
            compact = re.sub(r"[ \t\r\f\v]+", " ", line).strip()
            if compact:
                lines.append(compact)
        return "\n".join(lines)

    def title(self) -> Optional[str]:
        return _safe_text(" ".join(part.strip() for part in self.title_parts if part.strip()))


def _parse_html(raw: str) -> Tuple[str, Optional[str]]:
    parser = _HTMLTextParser()
    parser.feed(raw)
    parser.close()
    return parser.text(), parser.title()


def _read_zip_member(zf: zipfile.ZipFile, name: str, limit: int) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > limit:
        raise ValueError("archive member exceeds extraction limit: %s" % name)
    return zf.read(name)


def _zip_budget_ok(zf: zipfile.ZipFile, limit: int) -> bool:
    total = 0
    for info in zf.infolist():
        total += int(info.file_size)
        if total > limit:
            return False
    return True


def _docx_text(path: Path, limit: int) -> str:
    with zipfile.ZipFile(str(path)) as zf:
        if not _zip_budget_ok(zf, limit * 4):
            raise ValueError("DOCX expanded size exceeds extraction budget")
        root = ET.fromstring(_read_zip_member(zf, "word/document.xml", limit * 2))
    paragraphs: List[str] = []
    for node in root.iter():
        if _local_name(node.tag) != "p":
            continue
        parts: List[str] = []
        for child in node.iter():
            name = _local_name(child.tag)
            if name == "t" and child.text:
                parts.append(child.text)
            elif name == "tab":
                parts.append("\t")
            elif name == "br":
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _odt_text(path: Path, limit: int) -> str:
    with zipfile.ZipFile(str(path)) as zf:
        if not _zip_budget_ok(zf, limit * 4):
            raise ValueError("ODT expanded size exceeds extraction budget")
        root = ET.fromstring(_read_zip_member(zf, "content.xml", limit * 2))
    paragraphs: List[str] = []
    for node in root.iter():
        if _local_name(node.tag) not in {"p", "h"}:
            continue
        text = "".join(node.itertext()).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _epub_opf(zf: zipfile.ZipFile, limit: int) -> Tuple[str, ET.Element]:
    container = ET.fromstring(_read_zip_member(zf, "META-INF/container.xml", limit))
    rootfile = None
    for node in container.iter():
        if _local_name(node.tag) == "rootfile":
            rootfile = node.attrib.get("full-path")
            if rootfile:
                break
    if not rootfile:
        raise ValueError("EPUB container has no rootfile")
    return rootfile, ET.fromstring(_read_zip_member(zf, rootfile, limit * 2))


def _epub_text(path: Path, limit: int) -> str:
    with zipfile.ZipFile(str(path)) as zf:
        if not _zip_budget_ok(zf, limit * 6):
            raise ValueError("EPUB expanded size exceeds extraction budget")
        opf_path, opf = _epub_opf(zf, limit)
        base = PurePosixPath(opf_path).parent
        manifest: Dict[str, str] = {}
        for node in opf.iter():
            if _local_name(node.tag) == "item" and node.attrib.get("id") and node.attrib.get("href"):
                manifest[node.attrib["id"]] = node.attrib["href"]
        spine_ids = [
            node.attrib.get("idref")
            for node in opf.iter()
            if _local_name(node.tag) == "itemref" and node.attrib.get("idref")
        ]
        names: List[str] = []
        for item_id in spine_ids:
            href = manifest.get(str(item_id))
            if href:
                names.append(str(base / PurePosixPath(href)))
        if not names:
            names = sorted(
                name for name in zf.namelist()
                if PurePosixPath(name).suffix.lower() in _HTML_EXTENSIONS
            )
        sections: List[str] = []
        consumed = 0
        for name in names:
            try:
                info = zf.getinfo(name)
            except KeyError:
                continue
            consumed += int(info.file_size)
            if consumed > limit * 3:
                raise ValueError("EPUB text content exceeds extraction budget")
            raw = zf.read(name).decode("utf-8", errors="replace")
            text, _ = _parse_html(raw)
            if text:
                sections.append(text)
    return "\n\n".join(sections)


def _embedded_metadata(path: Path) -> Dict[str, object]:
    suffix = path.suffix.lower()
    data: Dict[str, object] = {}
    try:
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore
            except ImportError:
                return data
            reader = PdfReader(str(path))
            metadata = reader.metadata or {}
            title = _safe_text(metadata.get("/Title"))
            author = _safe_text(metadata.get("/Author"))
            subject = _safe_text(metadata.get("/Subject"))
            if title:
                data["title"] = title
            if author:
                data["author"] = author
            if subject:
                data["subject"] = subject
        elif suffix in _HTML_EXTENSIONS:
            raw = path.read_text(encoding="utf-8", errors="replace")
            _, title = _parse_html(raw)
            if title:
                data["title"] = title
        elif suffix == ".docx":
            with zipfile.ZipFile(str(path)) as zf:
                if "docProps/core.xml" in zf.namelist():
                    root = ET.fromstring(_read_zip_member(zf, "docProps/core.xml", 1024 * 1024))
                    title = _xml_first_text(root, {"title"})
                    creator = _xml_first_text(root, {"creator"})
                    if title:
                        data["title"] = title
                    if creator:
                        data["author"] = creator
        elif suffix == ".epub":
            with zipfile.ZipFile(str(path)) as zf:
                opf_path, root = _epub_opf(zf, 4 * 1024 * 1024)
                del opf_path
                mapping = {
                    "title": {"title"},
                    "author": {"creator"},
                    "publisher": {"publisher"},
                    "language": {"language"},
                    "rights_note": {"rights"},
                }
                for key, names in mapping.items():
                    value = _xml_first_text(root, names)
                    if value:
                        data[key] = value
        elif suffix == ".odt":
            with zipfile.ZipFile(str(path)) as zf:
                if "meta.xml" in zf.namelist():
                    root = ET.fromstring(_read_zip_member(zf, "meta.xml", 2 * 1024 * 1024))
                    title = _xml_first_text(root, {"title"})
                    creator = _xml_first_text(root, {"creator", "initial-creator"})
                    language = _xml_first_text(root, {"language"})
                    if title:
                        data["title"] = title
                    if creator:
                        data["author"] = creator
                    if language:
                        data["language"] = language
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return {}
    return data


def _load_sidecar(path: Path) -> Dict[str, object]:
    sidecar = path.with_name(path.name + SIDECAR_SUFFIX)
    if not sidecar.is_file():
        return {}
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("sidecar must be a JSON object: %s" % sidecar)
    unknown = sorted(set(raw) - _SIDECAR_FIELDS)
    if unknown:
        raise ValueError("unknown sidecar fields for %s: %s" % (path.name, ", ".join(unknown)))
    tags = raw.get("tags")
    if tags is not None and (not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags)):
        raise ValueError("sidecar tags must be a list of strings: %s" % sidecar)
    return dict(raw)


@dataclass(frozen=True)
class DocumentMetadata:
    title: str
    source: str
    source_uri: Optional[str]
    trust_class: str
    language: str
    rights_note: Optional[str]
    tags: Tuple[str, ...]
    version_label: Optional[str]
    stale_after: Optional[str]
    supersedes_item_id: Optional[str]
    ignore: bool = False

    def stage_kwargs(self) -> Dict[str, object]:
        return {
            "title": self.title,
            "source": self.source,
            "source_uri": self.source_uri,
            "trust_class": self.trust_class,
            "language": self.language,
            "rights_note": self.rights_note,
            "tags": self.tags,
            "version_label": self.version_label,
            "stale_after": self.stale_after,
            "supersedes_item_id": self.supersedes_item_id,
        }


def probe_metadata(
    path: Path,
    *,
    source: str,
    trust_class: str = "unknown",
    language: str = "en",
    rights_note: Optional[str] = None,
    tags: Iterable[str] = (),
    source_uri: Optional[str] = None,
) -> DocumentMetadata:
    embedded = _embedded_metadata(path)
    sidecar = _load_sidecar(path)
    title = _safe_text(sidecar.get("title")) or _safe_text(embedded.get("title")) or _clean_title(path.stem)
    chosen_source = _safe_text(sidecar.get("source")) or source.strip()
    if not chosen_source:
        raise ValueError("source is required")
    chosen_uri = _safe_text(sidecar.get("source_uri")) or source_uri
    chosen_trust = _safe_text(sidecar.get("trust_class")) or _safe_text(sidecar.get("trust")) or trust_class
    chosen_language = _safe_text(sidecar.get("language")) or _safe_text(embedded.get("language")) or language
    chosen_rights = _safe_text(sidecar.get("rights_note")) or _safe_text(embedded.get("rights_note")) or rights_note
    tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}
    for tag in sidecar.get("tags", []):
        if str(tag).strip():
            tag_set.add(str(tag).strip())
    tag_set.add("format:%s" % (path.suffix.lower().lstrip(".") or "unknown"))
    author = _safe_text(embedded.get("author"))
    publisher = _safe_text(embedded.get("publisher"))
    if author:
        tag_set.add("author:%s" % author)
    if publisher:
        tag_set.add("publisher:%s" % publisher)
    return DocumentMetadata(
        title=title,
        source=chosen_source,
        source_uri=chosen_uri,
        trust_class=chosen_trust or "unknown",
        language=chosen_language or "en",
        rights_note=chosen_rights,
        tags=tuple(sorted(tag_set)),
        version_label=_safe_text(sidecar.get("version_label")) or _safe_text(sidecar.get("version")),
        stale_after=_safe_text(sidecar.get("stale_after")),
        supersedes_item_id=_safe_text(sidecar.get("supersedes_item_id")) or _safe_text(sidecar.get("supersedes")),
        ignore=bool(sidecar.get("ignore", False)),
    )


class DocumentLibrary(Library):
    """Library variant with optional richer extraction, preserving core semantics."""

    def __init__(
        self,
        root: Path,
        *,
        ocr: bool = False,
        ocr_language: str = "eng",
        ocr_page_timeout: int = 180,
        ocr_process_timeout: int = 1800,
        **kwargs: object
    ) -> None:
        self.ocr_enabled = bool(ocr)
        self.ocr_language = ocr_language.strip() or "eng"
        self.ocr_page_timeout = max(1, int(ocr_page_timeout))
        self.ocr_process_timeout = max(30, int(ocr_process_timeout))
        super().__init__(root, **kwargs)

    def _store_extracted(self, item_id: str, text: str) -> Optional[Path]:
        if not text.strip():
            return None
        encoded = text.encode("utf-8")
        if len(encoded) > self.max_extract_bytes:
            return None
        destination = self.text_dir / (item_id + ".txt")
        destination.write_text(text, encoding="utf-8")
        return destination

    @staticmethod
    def _pdf_text_is_sparse(pages: List[str]) -> bool:
        if not pages:
            return True
        characters = sum(len(re.sub(r"\s+", "", page)) for page in pages)
        nonempty = sum(1 for page in pages if len(re.sub(r"\s+", "", page)) >= 24)
        return characters < 80 or nonempty < max(1, len(pages) // 4)

    def _ocr_pdf_pages(self, source: Path) -> Optional[List[str]]:
        executable = shutil.which("ocrmypdf")
        if not executable:
            raise RuntimeError("OCR is required for this PDF but ocrmypdf is not installed")
        with tempfile.TemporaryDirectory(prefix="velour-ocr-") as temp_dir:
            output = Path(temp_dir) / "ocr.pdf"
            command = [
                executable,
                "--mode", "skip",
                "--output-type", "pdf",
                "--tesseract-timeout", str(self.ocr_page_timeout),
                "--skip-big", "50",
                "-l", self.ocr_language,
                str(source),
                str(output),
            ]
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.ocr_process_timeout,
                check=False,
            )
            if completed.returncode != 0 or not output.is_file():
                detail = (completed.stderr or completed.stdout or "OCRmyPDF failed").strip()[-500:]
                raise RuntimeError("OCRmyPDF failed: %s" % detail)
            return self._extract_pdf_pages(output)

    def _ocr_image(self, source: Path) -> Optional[str]:
        executable = shutil.which("tesseract")
        if not executable:
            raise RuntimeError("OCR is required for this image but tesseract is not installed")
        completed = subprocess.run(
            [executable, str(source), "stdout", "-l", self.ocr_language, "--psm", "3"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=self.ocr_process_timeout,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or "Tesseract failed").strip()[-500:]
            raise RuntimeError("Tesseract failed: %s" % detail)
        return completed.stdout

    def _extract_text(self, source: Path, item_id: str) -> Optional[Path]:
        suffix = self._detect_suffix(source)
        if suffix in _TEXT_EXTENSIONS:
            return super()._extract_text(source, item_id)
        if suffix == ".pdf":
            if source.stat().st_size > self.max_pdf_bytes:
                return None
            pages = self._extract_pdf_pages(source)
            if pages is None:
                return None
            if self.ocr_enabled and self._pdf_text_is_sparse(pages):
                pages = self._ocr_pdf_pages(source) or pages
            text = "\f".join(pages)
            return self._store_extracted(item_id, text)
        if suffix in _HTML_EXTENSIONS:
            if source.stat().st_size > self.max_extract_bytes:
                return None
            raw = source.read_text(encoding="utf-8", errors="replace")
            text, _ = _parse_html(raw)
            return self._store_extracted(item_id, text)
        if suffix == ".docx":
            return self._store_extracted(item_id, _docx_text(source, self.max_extract_bytes))
        if suffix == ".odt":
            return self._store_extracted(item_id, _odt_text(source, self.max_extract_bytes))
        if suffix == ".epub":
            return self._store_extracted(item_id, _epub_text(source, self.max_extract_bytes))
        if suffix in _IMAGE_EXTENSIONS:
            if not self.ocr_enabled:
                return None
            return self._store_extracted(item_id, self._ocr_image(source) or "")
        return super()._extract_text(source, item_id)


@dataclass(frozen=True)
class IngestResult:
    path: str
    action: str
    reason: Optional[str] = None
    sha256: Optional[str] = None
    candidate_id: Optional[str] = None
    item_id: Optional[str] = None
    title: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "action": self.action,
            "reason": self.reason,
            "sha256": self.sha256,
            "candidate_id": self.candidate_id,
            "item_id": self.item_id,
            "title": self.title,
        }


class BulkIngestor:
    """Recursively stage or explicitly publish a bounded document batch."""

    def __init__(
        self,
        library: DocumentLibrary,
        *,
        source: str,
        trust_class: str = "unknown",
        language: str = "en",
        rights_note: Optional[str] = None,
        tags: Iterable[str] = (),
        source_uri_base: Optional[str] = None,
        include_hidden: bool = False,
        all_files: bool = False,
        keep_duplicates: bool = False,
    ) -> None:
        self.library = library
        self.source = source
        self.trust_class = trust_class
        self.language = language
        self.rights_note = rights_note
        self.tags = tuple(tags)
        self.source_uri_base = source_uri_base.rstrip("/") if source_uri_base else None
        self.include_hidden = bool(include_hidden)
        self.all_files = bool(all_files)
        self.keep_duplicates = bool(keep_duplicates)

    def _iter_files(self, input_path: Path) -> Iterator[Path]:
        if input_path.is_file():
            yield input_path
            return
        if not input_path.is_dir():
            raise FileNotFoundError(str(input_path))
        for path in sorted(input_path.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(input_path)
            if not self.include_hidden and any(part.startswith(".") for part in relative.parts):
                continue
            if path.name.endswith(SIDECAR_SUFFIX):
                continue
            if not self.all_files and path.suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
                continue
            yield path

    def _source_uri(self, base_path: Path, path: Path) -> Optional[str]:
        if not self.source_uri_base:
            return None
        relative = path.name if base_path.is_file() else path.relative_to(base_path).as_posix()
        return self.source_uri_base + "/" + quote(relative)

    def _duplicate(self, sha: str, metadata: DocumentMetadata) -> bool:
        if self.keep_duplicates:
            return False
        for item in self.library.list_items():
            if item.sha256 == sha and item.source == metadata.source and item.source_uri == metadata.source_uri:
                return True
        for candidate in self.library.list_candidates():
            if candidate.state != "rejected" and candidate.sha256 == sha and candidate.source == metadata.source and candidate.source_uri == metadata.source_uri:
                return True
        return False

    def ingest(self, input_path: Path, *, publish: bool = False, dry_run: bool = False) -> List[IngestResult]:
        input_path = input_path.resolve()
        results: List[IngestResult] = []
        for path in self._iter_files(input_path):
            display = str(path if input_path.is_file() else path.relative_to(input_path))
            try:
                metadata = probe_metadata(
                    path,
                    source=self.source,
                    trust_class=self.trust_class,
                    language=self.language,
                    rights_note=self.rights_note,
                    tags=self.tags,
                    source_uri=self._source_uri(input_path, path),
                )
                if metadata.ignore:
                    results.append(IngestResult(display, "skipped", reason="sidecar_ignore", title=metadata.title))
                    continue
                size = path.stat().st_size
                if size > self.library.max_file_bytes:
                    results.append(IngestResult(display, "skipped", reason="file_too_large", title=metadata.title))
                    continue
                sha = _sha256(path)
                if self._duplicate(sha, metadata):
                    results.append(IngestResult(display, "skipped", reason="already_present", sha256=sha, title=metadata.title))
                    continue
                if dry_run:
                    results.append(IngestResult(display, "planned_publish" if publish else "planned_stage", sha256=sha, title=metadata.title))
                    continue
                candidate = self.library.stage(path, **metadata.stage_kwargs())
                if not publish:
                    results.append(IngestResult(display, "staged", sha256=sha, candidate_id=candidate.candidate_id, title=metadata.title))
                    continue
                item = self.library.publish(candidate.candidate_id)
                results.append(IngestResult(display, "published", sha256=sha, candidate_id=candidate.candidate_id, item_id=item.item_id, title=metadata.title))
            except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, ET.ParseError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                results.append(IngestResult(display, "error", reason=str(exc)))
        return results


def _summary(results: List[IngestResult]) -> Dict[str, object]:
    counts: Dict[str, int] = {}
    for result in results:
        counts[result.action] = counts.get(result.action, 0) + 1
    return {
        "counts": dict(sorted(counts.items())),
        "total": len(results),
        "results": [result.as_dict() for result in results],
        "reference_only": True,
        "canonical_receipt": False,
        "authority": "none",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="velour-ingest", description="Guarded batch intake for Velour's Library")
    parser.add_argument("--root", default="library-data", help="Velour Library data root")
    parser.add_argument("path", help="File or directory to ingest")
    parser.add_argument("--source", required=True, help="Provider/source label; never inferred as trust")
    parser.add_argument("--trust", default="unknown")
    parser.add_argument("--language", default="en")
    parser.add_argument("--rights-note")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--source-uri-base", help="Optional non-secret URI prefix applied to relative batch paths")
    parser.add_argument("--publish", action="store_true", help="Explicitly publish after staging; default is quarantine only")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--all-files", action="store_true", help="Archive unsupported files as metadata-only candidates")
    parser.add_argument("--keep-duplicates", action="store_true", help="Keep repeat provenance records instead of idempotent batch skipping")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR fallback for sparse PDFs and images")
    parser.add_argument("--ocr-language", default="eng", help="Tesseract language code, e.g. eng or eng+fra")
    parser.add_argument("--ocr-page-timeout", type=int, default=180)
    parser.add_argument("--ocr-process-timeout", type=int, default=1800)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    library = DocumentLibrary(
        Path(args.root),
        ocr=args.ocr,
        ocr_language=args.ocr_language,
        ocr_page_timeout=args.ocr_page_timeout,
        ocr_process_timeout=args.ocr_process_timeout,
    )
    ingestor = BulkIngestor(
        library,
        source=args.source,
        trust_class=args.trust,
        language=args.language,
        rights_note=args.rightights_note if hasattr(args, "rightights_note") else args.rights_note,
        tags=args.tag,
        source_uri_base=args.source_uri_base,
        include_hidden=args.include_hidden,
        all_files=args.all_files,
        keep_duplicates=args.keep_duplicates,
    )
    results = ingestor.ingest(Path(args.path), publish=args.publish, dry_run=args.dry_run)
    print(json.dumps(_summary(results), indent=2, sort_keys=True))
    return 2 if any(result.action == "error" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
