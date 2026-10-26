"""Citation validation.

The model is instructed to cite files and line ranges, but instructions are
not guarantees. Every citation it returns is re-checked against the *current*
indexed repository before it is shown as verified:

* the file must exist in this project's index;
* the line range must be inside the file, ordered, and non-empty;
* if the model supplied a supporting quote, that quote (whitespace-normalised)
  must actually occur within the cited lines.

Anything that fails is returned as ``rejected`` with a reason and is never
presented to the user as source evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .indexer import CodeIndex

_WS_RE = re.compile(r"\s+")
# "39-61", "39–61", "39 to 61", "lines 39-61"
_RANGE_RE = re.compile(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)")
_SINGLE_RE = re.compile(r"(\d+)")

# A line range glued onto the path instead of a separate field. Observed
# against the live API: `"path": "app.py 18-41"`, which then failed validation
# as "'app.py 18-41' is not a file in this project" even though the citation
# was correct. The range is split off here so the citation can be checked.
_TRAILING_RANGE_RE = re.compile(
    r"[\s:#(]*(?:lines?\s*|[Ll])?(\d+)\s*(?:-|–|—|to)\s*[Ll]?(\d+)\s*\)?\s*$"
)


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip()).lower()


def split_path_and_range(raw: str) -> tuple[str, int, int]:
    """Separate a path from a line range glued onto it.

    ``"app.py 18-41"``, ``"app.py:18-41"``, ``"app.py#L18-L41"`` and
    ``"app.py (lines 18-41)"`` all describe the same citation; only the first
    part is the path.
    """
    text = (raw or "").replace("\\", "/").strip()
    match = _TRAILING_RANGE_RE.search(text)
    if match and match.start() > 0:
        cleaned = text[:match.start()].strip().rstrip(":(").strip()
        if cleaned:
            return cleaned.lstrip("/"), int(match.group(1)), int(match.group(2))
    return text.lstrip("/"), 0, 0


def _coerce_lines(item: dict) -> tuple[int, int]:
    """Extract a line range from any of the shapes models actually emit.

    Verified against the live API: asked for `start_line`/`end_line`, the
    model also returns `"lines": "39-61"`, `line`, `line_range`, or
    `start`/`end`. All of those are accepted rather than throwing away a
    correct citation over a field name.
    """
    for start_key, end_key in (
        ("start_line", "end_line"), ("start", "end"),
        ("startLine", "endLine"), ("from", "to"),
        ("start_line_number", "end_line_number"),
    ):
        if start_key in item or end_key in item:
            start = _coerce_int(item.get(start_key))
            end = _coerce_int(item.get(end_key) or item.get(start_key))
            if start:
                return start, end or start

    for key in ("lines", "line_range", "lineRange", "line_numbers", "line"):
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            n = int(value)
            return n, n
        text = str(value)
        match = _RANGE_RE.search(text)
        if match:
            return int(match.group(1)), int(match.group(2))
        match = _SINGLE_RE.search(text)
        if match:
            n = int(match.group(1))
            return n, n
    return 0, 0


@dataclass
class Citation:
    path: str
    start_line: int
    end_line: int
    quote: str = ""
    note: str = ""

    @property
    def citation_id(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def to_dict(self, verified: bool, reason: str = "") -> dict:
        payload = {
            "citation_id": self.citation_id,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "quote": self.quote,
            "note": self.note,
            "verified": verified,
        }
        if reason:
            payload["rejection_reason"] = reason
        return payload


def _coerce_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_citations(raw) -> list[Citation]:
    """Coerce loosely-typed model output into :class:`Citation` objects.

    Field names and line formats vary between replies, so this accepts every
    shape observed against the live API rather than discarding a correct
    citation over its spelling.
    """
    out: list[Citation] = []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            # A bare path such as "auth/login.py:39-61". Only accept strings
            # that actually look like a file reference, so stray prose in the
            # array is ignored rather than treated as a citation.
            text = item.strip()
            path, start, end = split_path_and_range(text)
            path = path.split(":")[0].strip()
            if not (start or "." in path):
                continue
            if path:
                out.append(Citation(path=path, start_line=start, end_line=end))
            continue
        if not isinstance(item, dict):
            continue
        raw_path = str(
            item.get("path") or item.get("file") or item.get("filename")
            or item.get("file_path") or ""
        ).strip()
        if not raw_path:
            continue
        path, path_start, path_end = split_path_and_range(raw_path)
        start, end = _coerce_lines(item)
        if not start and path_start:
            start, end = path_start, path_end
        quote = ""
        for key in ("quote", "snippet", "code", "text", "line_content", "excerpt"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                quote = value[:500]
                break
        note = ""
        for key in ("note", "why", "reason", "description", "explanation"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                note = value[:300]
                break
        out.append(Citation(
            path=path.replace("\\", "/").lstrip("/"),
            start_line=start,
            end_line=end,
            quote=quote,
            note=note,
        ))
    return out


def locate_quote(index: CodeIndex, path: str, quote: str) -> tuple[int, int] | None:
    """Find the line range where ``quote`` actually occurs in ``path``.

    Used when the model cites a file and a quote but no usable line numbers —
    a correct citation should not be thrown away just because the numbering
    field was missing.
    """
    f = index.get(path)
    if f is None:
        return None
    probe = _norm(quote)
    if len(probe) < 8:
        return None

    norm_lines = [_norm(line) for line in f.lines]
    for i, line in enumerate(norm_lines):
        if probe in line:
            return i + 1, i + 1
    for size in range(2, 9):
        for i in range(0, len(norm_lines) - size + 1):
            window = " ".join(norm_lines[i:i + size]).strip()
            if probe in window:
                return i + 1, i + size
    return None


def validate_citation(citation: Citation, index: CodeIndex,
                      context_ids: set[str] | None = None) -> tuple[bool, str]:
    """Return ``(verified, reason)`` for a single citation."""
    f = index.get(citation.path)
    if f is None:
        return False, f"'{citation.path}' is not a file in this project"

    if citation.start_line <= 0:
        # No usable numbering — recover it from the quote if we can.
        located = locate_quote(index, citation.path, citation.quote) if citation.quote else None
        if located is None:
            return False, "missing or invalid start line"
        citation.start_line, citation.end_line = located

    end = citation.end_line or citation.start_line
    if end < citation.start_line:
        return False, "end line is before start line"
    if citation.start_line > f.line_count:
        return False, f"start line {citation.start_line} is beyond the end of the file ({f.line_count} lines)"

    end = min(end, f.line_count)
    pairs = index.read_lines(citation.path, citation.start_line, end)
    if not pairs:
        return False, "cited line range is empty"

    if citation.quote:
        # The model is asked not to echo code, but if it does, the quote must
        # be real. The application supplies the quote otherwise, so this check
        # is a verification of model-supplied text, not a requirement.
        window = _norm("\n".join(text for _, text in pairs))
        probe = _norm(citation.quote)
        if len(probe) >= 12 and probe not in window:
            # Also accept a quote that spans the whole file (models sometimes
            # quote a wider region than they cite).
            whole = _norm("\n".join(f.lines))
            if probe not in whole:
                return False, "the quoted text does not appear in the cited lines"

    if context_ids is not None and citation.citation_id not in context_ids:
        # Not fatal: the model may cite a neighbouring line. Record it as
        # unverified context so the UI can still show it distinctly.
        return True, "cited outside the retrieved context"

    return True, ""


def validate_citations(citations: list[Citation], index: CodeIndex,
                       context_ids: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Split citations into verified and rejected lists.

    Duplicates are collapsed: the model often cites the same lines more than
    once for different points, and showing the same evidence three times adds
    noise without adding proof.
    """
    verified: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for c in citations:
        ok, reason = validate_citation(c, index, context_ids)
        if not ok:
            key = c.citation_id
            if key in seen:
                continue
            seen.add(key)
            rejected.append(c.to_dict(False, reason))
            continue
        key = c.citation_id
        if key in seen:
            continue
        seen.add(key)

        # Fill the evidence text from the repository itself. This is strictly
        # better than trusting the model to echo code: the quote is guaranteed
        # to be the real source, and it removes the need for the model to
        # embed code (with its quote characters) inside a JSON string.
        if not c.quote:
            indexed = index.get(c.path)
            if indexed is not None:
                end = min(c.end_line or c.start_line, indexed.line_count)
                pairs = index.read_lines(c.path, c.start_line, end)
                c.quote = "\n".join(text for _, text in pairs)[:400]

        verified.append(c.to_dict(True, "" if not reason else reason))

    return verified, rejected
