"""Build bounded contiguous evidence windows from one canonical Library item.

Search ranking finds a useful seed chunk. Conversation often needs a little more
of the same source than the ranked snippet alone. This module may extend that
seed into nearby indexed chunks from the same item, but it never crosses item
identity, canonical SHA-256 identity, or the configured character/chunk bounds.

The returned text is still reference-only Library evidence. Windowing changes
how much contiguous source text is returned, not its trust or authority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

DEFAULT_MAX_WINDOW_CHARACTERS = 480
DEFAULT_MAX_WINDOW_CHUNKS = 3
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "could",
        "did", "do", "does", "for", "from", "has", "have", "how", "in",
        "is", "it", "its", "library", "may", "of", "on", "or", "should",
        "the", "this", "to", "velour", "what", "when", "where", "which",
        "who", "why", "with", "would",
    }
)


@dataclass(frozen=True)
class _ChunkSpan:
    chunk_id: str
    ordinal: int
    body: str
    start: int
    end: int


def expand_evidence_bundle(
    library: Any,
    query: str,
    bundle: Mapping[str, Any],
    *,
    max_characters: int = DEFAULT_MAX_WINDOW_CHARACTERS,
    max_chunks: int = DEFAULT_MAX_WINDOW_CHUNKS,
) -> Dict[str, Any]:
    """Expand text evidence results into bounded same-source windows.

    Failure is deliberately soft: a result that cannot be proven safe for
    expansion is returned unchanged rather than making retrieval unavailable.
    """
    if not isinstance(bundle, Mapping):
        raise TypeError("evidence bundle must be a mapping")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty text")
    if isinstance(max_characters, bool) or not isinstance(max_characters, int) or max_characters < 80:
        raise ValueError("max_characters must be an integer >= 80")
    if isinstance(max_chunks, bool) or not isinstance(max_chunks, int) or not 1 <= max_chunks <= 8:
        raise ValueError("max_chunks must be an integer between 1 and 8")

    output = dict(bundle)
    results = bundle.get("results")
    if not isinstance(results, list):
        return output

    expanded = []
    for raw in results:
        if not isinstance(raw, Mapping):
            expanded.append(raw)
            continue
        try:
            expanded.append(
                _expand_result(
                    library,
                    query,
                    raw,
                    max_characters=max_characters,
                    max_chunks=max_chunks,
                )
            )
        except (KeyError, TypeError, ValueError, OSError, RuntimeError):
            expanded.append(dict(raw))
    output["results"] = expanded
    return output


def _expand_result(
    library: Any,
    query: str,
    result: Mapping[str, Any],
    *,
    max_characters: int,
    max_chunks: int,
) -> Dict[str, Any]:
    current = dict(result)
    if current.get("retrieval_method") == "metadata":
        return current

    item_id = _required_text(current, "item_id")
    chunk_id = _required_text(current, "chunk_id")
    expected_sha = _required_text(current, "sha256").lower()
    if len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        return current

    # Read only from the local catalog. The seed result must still name the
    # same canonical item/hash before any neighboring text is considered.
    with library._connect() as conn:  # package-internal boundary
        item = conn.execute(
            "SELECT sha256 FROM items WHERE item_id=?",
            (item_id,),
        ).fetchone()
        if item is None or str(item["sha256"]).lower() != expected_sha:
            return current
        seed = conn.execute(
            "SELECT ordinal FROM chunks WHERE item_id=? AND chunk_id=?",
            (item_id, chunk_id),
        ).fetchone()
        if seed is None:
            return current
        seed_ordinal = int(seed["ordinal"])

        # Fetch enough nearby context to locate a section boundary. The final
        # returned overlap is separately capped to max_chunks.
        radius = max_chunks
        rows = conn.execute(
            """SELECT chunk_id, ordinal, body
               FROM chunks
               WHERE item_id=? AND ordinal BETWEEN ? AND ?
               ORDER BY ordinal""",
            (item_id, max(0, seed_ordinal - radius), seed_ordinal + radius),
        ).fetchall()

    spans, combined = _assemble_spans(rows)
    if not spans or not combined:
        return current

    seed_span = next((span for span in spans if span.chunk_id == chunk_id), None)
    if seed_span is None:
        return current

    start, end, truncated = _select_window(
        combined,
        query,
        seed_span,
        max_characters=max_characters,
    )
    bounded = _enforce_chunk_bound(
        spans,
        start,
        end,
        seed_span,
        max_chunks=max_chunks,
        max_characters=max_characters,
    )
    if bounded is None:
        return current
    start, end, chunk_truncated = bounded
    truncated = truncated or chunk_truncated
    if end <= start:
        return current

    snippet = combined[start:end].strip()
    if not snippet:
        return current
    if len(snippet) > max_characters:
        snippet = _clip_exact(snippet, max_characters)
        truncated = True

    chunk_ids = tuple(
        span.chunk_id
        for span in spans
        if span.end > start and span.start < end
    )
    if not chunk_ids or len(chunk_ids) > max_chunks:
        return current

    # Do not replace a longer useful ranked snippet with a smaller window unless
    # the new window captured explicit Markdown section structure.
    original = str(current.get("snippet") or "").strip()
    if original and len(snippet) < len(original) and not _contains_heading(snippet):
        return current

    current["snippet"] = snippet
    current["chunk_ids"] = list(chunk_ids)
    current["windowed"] = True
    current["window_truncated"] = bool(truncated)
    return current


def _assemble_spans(rows: Sequence[Any]) -> Tuple[Tuple[_ChunkSpan, ...], str]:
    spans = []
    parts = []
    offset = 0
    for row in rows:
        body = str(row["body"])
        if parts:
            parts.append("\n")
            offset += 1
        start = offset
        parts.append(body)
        offset += len(body)
        spans.append(
            _ChunkSpan(
                chunk_id=str(row["chunk_id"]),
                ordinal=int(row["ordinal"]),
                body=body,
                start=start,
                end=offset,
            )
        )
    return tuple(spans), "".join(parts)


def _select_window(
    text: str,
    query: str,
    seed: _ChunkSpan,
    *,
    max_characters: int,
) -> Tuple[int, int, bool]:
    query_tokens = _meaningful_tokens(query)
    section = _matching_markdown_section(text, query_tokens, seed)
    if section is not None:
        start, end = section
        if end - start <= max_characters:
            return start, end, False
        clipped_end = _snap_end(text, start, start + max_characters)
        return start, clipped_end, True

    anchor = _find_anchor(text, query, query_tokens, seed)
    before = max_characters // 4
    start = max(0, anchor - before)
    end = min(len(text), start + max_characters)
    if end - start < max_characters:
        start = max(0, end - max_characters)
    start = _snap_start(text, start)
    end = _snap_end(text, start, end)
    return start, end, start > 0 or end < len(text)


def _matching_markdown_section(
    text: str,
    query_tokens: Tuple[str, ...],
    seed: _ChunkSpan,
) -> Optional[Tuple[int, int]]:
    if not query_tokens:
        return None
    headings = list(_HEADING_RE.finditer(text))
    for index, match in enumerate(headings):
        heading_tokens = set(_meaningful_tokens(match.group(2)))
        if not set(query_tokens).issubset(heading_tokens):
            continue
        section_end = _section_end(headings, index, text)
        if not (
            seed.start <= match.start() <= seed.end
            or match.start() <= seed.start < section_end
        ):
            continue
        return match.start(), _rstrip_index(text, match.start(), section_end)
    return None


def _section_end(headings: Sequence[Any], index: int, text: str) -> int:
    level = len(headings[index].group(1))
    for following in headings[index + 1 :]:
        if len(following.group(1)) <= level:
            return following.start()
    return len(text)


def _find_anchor(
    text: str,
    query: str,
    query_tokens: Tuple[str, ...],
    seed: _ChunkSpan,
) -> int:
    folded = text.casefold()
    phrase = " ".join(query.split()).casefold()
    position = folded.find(phrase, seed.start, seed.end)
    if position >= 0:
        return position
    for token in query_tokens:
        position = folded.find(token.casefold(), seed.start, seed.end)
        if position >= 0:
            return position
    return seed.start + max(0, (seed.end - seed.start) // 2)


def _enforce_chunk_bound(
    spans: Sequence[_ChunkSpan],
    start: int,
    end: int,
    seed: _ChunkSpan,
    *,
    max_chunks: int,
    max_characters: int,
) -> Optional[Tuple[int, int, bool]]:
    overlapping = [span for span in spans if span.end > start and span.start < end]
    if not overlapping:
        return None
    if len(overlapping) <= max_chunks:
        return start, min(end, start + max_characters), False

    try:
        seed_index = next(i for i, span in enumerate(overlapping) if span.chunk_id == seed.chunk_id)
    except StopIteration:
        return None
    first = max(0, min(seed_index, len(overlapping) - max_chunks))
    chosen = overlapping[first : first + max_chunks]
    bounded_start = max(start, chosen[0].start)
    bounded_end = min(end, chosen[-1].end, bounded_start + max_characters)
    return bounded_start, bounded_end, True


def _meaningful_tokens(value: str) -> Tuple[str, ...]:
    tokens = tuple(token.casefold() for token in _TOKEN_RE.findall(value))
    reduced = tuple(token for token in tokens if token not in _STOPWORDS and len(token) > 1)
    return reduced or tokens


def _snap_start(text: str, start: int) -> int:
    if start <= 0:
        return 0
    newline = text.find("\n", start, min(len(text), start + 80))
    if newline >= 0:
        return newline + 1
    space = text.find(" ", start, min(len(text), start + 40))
    return space + 1 if space >= 0 else start


def _snap_end(text: str, start: int, end: int) -> int:
    end = min(len(text), end)
    if end >= len(text):
        return len(text)
    floor = max(start + 1, end - 80)
    newline = text.rfind("\n", floor, end)
    if newline > start:
        return newline
    space = text.rfind(" ", floor, end)
    return space if space > start else end


def _rstrip_index(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def _clip_exact(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    floor = max(1, limit - 80)
    newline = value.rfind("\n", floor, limit)
    if newline > 0:
        return value[:newline].rstrip()
    space = value.rfind(" ", floor, limit)
    if space > 0:
        return value[:space].rstrip()
    return value[:limit]


def _contains_heading(value: str) -> bool:
    return _HEADING_RE.search(value) is not None


def _required_text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be non-empty text" % key)
    return value.strip()
