"""Evidence retrieval.

Given a natural-language question (English, Telugu, Tamil, Hindi, or a
code-mixed mix such as "ee project lo login ela work avutundi?") this module
selects the most relevant snippets from the indexed repository.

The retrieval is lexical and deliberately transparent: every snippet carries
the reason it was chosen and its exact line range, so the UI can show *why*
the model was given that code. A small bilingual lexicon bridges common
romanised Indic question words to the English concepts they refer to, which
matters because source code is written in English.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import CONTEXT_CHAR_BUDGET, MAX_SNIPPETS, SNIPPET_MAX_LINES
from .indexer import CodeIndex, IndexedFile, Symbol

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")

_STOPWORDS = {
    "the", "is", "are", "was", "were", "a", "an", "of", "to", "in", "on",
    "for", "and", "or", "how", "what", "where", "which", "who", "why", "when",
    "does", "do", "did", "this", "that", "these", "those", "it", "its", "be",
    "with", "from", "by", "at", "as", "can", "could", "would", "should",
    "explain", "tell", "me", "please", "about", "work", "works", "working",
    "used", "use", "using", "get", "got", "there", "here", "any", "all",
    "project", "code", "file", "files", "function", "functions", "simple",
    "ee", "e", "lo", "ki", "ka", "ku", "ela", "elaa", "chestundi", "avutundi",
    "undi", "unna", "cheyyandi", "chudu", "kya", "kaise", "kahan", "hai",
    "hain", "mein", "me", "ko", "se", "ka", "ki", "eppadi", "epdi", "enge",
    "enna", "irukku", "irukkum", "pannum", "vanakkam",
}

# Romanised Indic question words -> English concepts present in real code.
_LEXICON = {
    "login": {"login", "auth", "authenticate", "signin", "token", "jwt", "session", "credential", "password"},
    "logout": {"logout", "signout", "session"},
    "password": {"password", "bcrypt", "hash", "credential"},
    "auth": {"auth", "login", "token", "jwt", "credential"},
    "database": {"database", "db", "sql", "sqlalchemy", "connection", "engine", "session", "postgres", "mongo"},
    "db": {"database", "db", "sql", "engine", "connection"},
    "config": {"config", "settings", "environment", "env", "configuration"},
    "configuration": {"config", "settings", "environment", "configuration"},
    "route": {"route", "router", "endpoint", "blueprint", "url", "api", "handler", "path"},
    "routes": {"route", "router", "endpoint", "blueprint", "api", "handler"},
    "endpoint": {"endpoint", "route", "api", "handler", "url"},
    "api": {"api", "route", "endpoint", "blueprint", "handler"},
    "model": {"model", "schema", "entity", "table", "orm", "class"},
    "user": {"user", "account", "profile", "customer", "member"},
    "architecture": {"main", "app", "createapp", "server", "index", "bootstrap", "startup", "blueprint", "register"},
    "structure": {"main", "app", "index", "package", "config", "blueprint"},
    "overview": {"readme", "main", "app", "index", "package", "config"},
    "test": {"test", "spec", "assert", "fixture"},
    "error": {"error", "exception", "handler", "try", "except", "catch"},
    "validate": {"validate", "validation", "check", "schema", "sanitize"},
    "upload": {"upload", "file", "multipart", "storage"},
    "order": {"order", "cart", "checkout", "payment", "total", "item"},
    "middleware": {"middleware", "before_request", "after_request", "interceptor"},
}

_ENTRYPOINT_HINTS = ("main", "app", "index", "server", "manage", "wsgi", "asgi", "bootstrap")
_OVERVIEW_WORDS = {"architecture", "structure", "overview", "project", "organization", "layout"}

# A file must clear this score to count as evidence. Without a floor, the
# generic "entry point" and README nudges would return files for any query.
MIN_SCORE = 2.0

# Scores for the two fallback paths, which are chosen by context rather than by
# matching a keyword. They sit above MIN_SCORE so the UI reports them as real
# evidence, and the reason string explains where they came from.
FOCUS_SCORE = 60.0
OVERVIEW_SCORE = 12.0

# A question made only of stopwords ("explain this") names no concept, so it
# has to be interpreted. These hints mark the questions that are really about
# the project as a whole, which the overview fallback can answer.
_OVERVIEW_HINTS = (
    "project", "repo", "repository", "codebase", "architecture", "overview",
    "structure", "organis", "organiz", "summar", "entry point", "entrypoint",
    "folder", "director", "tech stack", "technolog", "purpose", "use case",
    "what does this", "what is this", "how is this", "tell me about this",
)


def looks_like_overview(question: str) -> bool:
    """True when the question asks about the project rather than a symbol."""
    lowered = (question or "").lower()
    return any(hint in lowered for hint in _OVERVIEW_HINTS)

# ...and it must be in the same league as the best match. Measured on a real
# repository, a correct top hit scored 66 while seven irrelevant files scored
# 16-34 purely for mentioning the word in prose. Sending all eight let the
# model answer about the wrong thing. Anything below this fraction of the top
# score is dropped as dilution.
RELATIVE_CUTOFF = 0.45

# How many snippets a single file may contribute. The best-ranked file is
# allowed a second one so a dominant match can also surface its next-most
# relevant function; weaker files get one.
TOP_FILE_SNIPPETS = 2
OTHER_FILE_SNIPPETS = 1

_DOC_EXTENSIONS = (".md", ".markdown", ".rst", ".txt", ".adoc")
_TEST_MARKERS = ("/test/", "/tests/", "/__tests__/", "/spec/", "/specs/")
_CONFIG_EXTENSIONS = (".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
                      ".conf", ".properties", ".env", ".xml")

# Not all files are equally good evidence. For a question about behaviour, the
# implementation is the answer; a test proves intent, and a document only
# describes. Ranking them apart is what stops a README that quotes the
# question from outranking the function that implements it.
ROLE_WEIGHTS = {
    "implementation": 1.0,
    "config": 0.85,
    "test": 0.55,
    "docs": 0.45,
}


def classify_role(path: str) -> str:
    """Classify a file as implementation, config, test or docs."""
    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    if base.endswith(_DOC_EXTENSIONS) or base in {"license", "licence", "notice"}:
        return "docs"
    if base.startswith("test_") or base.endswith("_test.py") or "_test." in base:
        return "test"
    if ".test." in base or ".spec." in base or base.endswith(".test.ts") or base.endswith(".spec.ts"):
        return "test"
    if any(marker in lower for marker in _TEST_MARKERS):
        return "test"
    if base.endswith(_CONFIG_EXTENSIONS):
        return "config"
    return "implementation"


@dataclass
class Snippet:
    """A retrieved region of source code with full provenance."""

    path: str
    start_line: int
    end_line: int
    code: str
    score: float
    reason: str
    language: str = ""
    symbol: str | None = None

    @property
    def citation_id(self) -> str:
        return f"{self.path}:{self.start_line}-{self.end_line}"

    def to_dict(self) -> dict:
        return {
            "citation_id": self.citation_id,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "score": round(self.score, 3),
            "reason": self.reason,
            "language": self.language,
            "symbol": self.symbol,
        }


@dataclass
class RetrievalResult:
    snippets: list[Snippet] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    used_chars: int = 0
    # Explains to the model what the snippets represent: the open file, the
    # previous turn, or a project overview. Empty for an ordinary match.
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "terms": self.terms,
            "used_chars": self.used_chars,
            "note": self.note,
            "snippets": [s.to_dict() for s in self.snippets],
        }


def extract_terms(question: str) -> list[str]:
    """Pull search terms out of a question, expanding Indic hints."""
    tokens = [t.lower() for t in _TOKEN_RE.findall(question or "")]
    terms: list[str] = []
    for tok in tokens:
        if tok in _STOPWORDS or len(tok) < 3:
            continue
        if tok not in terms:
            terms.append(tok)
        for extra in _LEXICON.get(tok, ()):
            if extra not in terms:
                terms.append(extra)
    return terms


def _score_file(f: IndexedFile, terms: list[str], question_lower: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    path_lower = f.path.lower()

    # Structural evidence — the file is *named* after the concept, or declares
    # a symbol with that name. This is strong, specific evidence.
    for term in terms:
        if term in path_lower:
            score += 7.0
            reasons.append(f"filename matches '{term}'")
        if any(term == s.name.lower() for s in f.symbols):
            score += 10.0
            reasons.append(f"symbol named '{term}'")
        elif any(term in s.name.lower() for s in f.symbols):
            score += 5.0
            reasons.append(f"symbol contains '{term}'")
        for imp in f.imports:
            if term in imp.lower():
                score += 1.0
                break
        for route in f.routes:
            if term in route.lower():
                score += 3.0
                reasons.append(f"route matches '{term}'")
                break

    # Textual evidence — the word merely appears somewhere in the file. Weak:
    # it is what makes a README that quotes the question look relevant, so it
    # is deliberately worth much less than a name match.
    body = "\n".join(f.lines).lower()
    for term in terms:
        occurrences = body.count(term)
        if occurrences:
            score += min(occurrences, 5) * 0.7

    # Entry points and docs matter for architecture-level questions.
    stem = path_lower.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if any(h in stem for h in _ENTRYPOINT_HINTS):
        if any(w in question_lower for w in _OVERVIEW_WORDS):
            score += 7.0
            reasons.append("entry-point file for an architecture question")
        else:
            score += 1.0
    if f.path.lower().endswith("readme.md"):
        score += 3.0 if any(w in question_lower for w in _OVERVIEW_WORDS) else 1.0

    if f.language == "Python":
        score += 0.4  # AST-backed files give the most trustworthy symbols

    # Documentation is valuable for "explain the architecture" but should not
    # outrank real code when the question is about behaviour.
    role = classify_role(f.path)
    weight = ROLE_WEIGHTS[role]
    if role == "docs" and any(w in question_lower for w in _OVERVIEW_WORDS):
        weight = 1.0
    score *= weight

    return score, reasons


def _matching_lines(f: IndexedFile, terms: list[str]) -> list[int]:
    hits: list[int] = []
    for idx, line in enumerate(f.lines, start=1):
        low = line.lower()
        if any(t in low for t in terms):
            hits.append(idx)
    return hits


def _ranked_symbols(f: IndexedFile, terms: list[str], hits: list[int]) -> list[Symbol]:
    """Rank the file's symbols by how well they explain the matched lines."""
    ranked: list[tuple[float, Symbol]] = []
    for sym in f.symbols:
        overlap = sum(1 for h in hits if sym.start_line <= h <= sym.end_line)
        name_match = any(t == sym.name.lower() or t in sym.name.lower() for t in terms)
        if overlap == 0 and not name_match:
            continue
        span = max(1, sym.end_line - sym.start_line)
        rank = overlap * 2.0 + (3.0 if name_match else 0.0) - (span / 1000.0)
        ranked.append((rank, sym))
    ranked.sort(key=lambda item: (-item[0], item[1].start_line))
    return [sym for _, sym in ranked]


class Retriever:
    """Selects evidence snippets from a :class:`CodeIndex`."""

    def __init__(self, index: CodeIndex):
        self.index = index

    def retrieve(self, question: str, max_snippets: int = MAX_SNIPPETS,
                 char_budget: int = CONTEXT_CHAR_BUDGET) -> RetrievalResult:
        terms = extract_terms(question)
        question_lower = (question or "").lower()
        result = RetrievalResult(terms=terms)

        if not terms:
            return result

        scored: list[tuple[float, IndexedFile, list[str]]] = []
        for f in self.index.files.values():
            s, reasons = _score_file(f, terms, question_lower)
            if s >= MIN_SCORE:
                scored.append((s, f, reasons))

        scored.sort(key=lambda item: (-item[0], item[1].path))
        if not scored:
            return result

        # Drop the long tail. A correct top match should not be diluted by a
        # crowd of files that merely mention the word somewhere.
        cutoff = max(MIN_SCORE, scored[0][0] * RELATIVE_CUTOFF)
        top_score = scored[0][0]

        used = 0
        seen: set[str] = set()

        for base_score, f, reasons in scored:
            if base_score < cutoff:
                break
            if len(result.snippets) >= max_snippets or used >= char_budget:
                break

            hits = _matching_lines(f, terms)
            symbols = _ranked_symbols(f, terms, hits)

            # The dominant file may contribute more than one function; weaker
            # ones get a single snippet so they cannot crowd out the best hit.
            if base_score >= top_score * 0.7:
                allowance = TOP_FILE_SNIPPETS
            else:
                allowance = OTHER_FILE_SNIPPETS

            emitted = 0
            for sym in symbols[:allowance]:
                start, end = sym.start_line, sym.end_line
                if end - start + 1 > SNIPPET_MAX_LINES:
                    end = start + SNIPPET_MAX_LINES - 1
                pairs = self.index.read_lines(f.path, start, end)
                if not pairs:
                    continue
                code = "\n".join(text for _, text in pairs)
                key = f"{f.path}:{start}-{end}"
                if key in seen:
                    continue
                seen.add(key)
                result.snippets.append(Snippet(
                    path=f.path, start_line=start, end_line=end, code=code,
                    score=base_score + 2.0, language=f.language,
                    reason=f"enclosing {sym.kind} '{sym.name}'", symbol=sym.name,
                ))
                used += len(code)
                emitted += 1
                if len(result.snippets) >= max_snippets or used >= char_budget:
                    break

            if emitted or (not symbols and not hits):
                # No symbol or line matched: show the head of a file that was
                # selected on the strength of its name alone.
                if not symbols and not hits:
                    start, end = 1, min(f.line_count, 25)
                    pairs = self.index.read_lines(f.path, start, end)
                    if pairs:
                        code = "\n".join(text for _, text in pairs)
                        key = f"{f.path}:{start}-{end}"
                        if key not in seen:
                            seen.add(key)
                            result.snippets.append(Snippet(
                                path=f.path, start_line=start, end_line=end, code=code,
                                score=base_score, language=f.language,
                                reason=reasons[0] if reasons else "relevant file",
                            ))
                            used += len(code)
                continue

            # Symbol matches were found but every one was already emitted.
            if not symbols and hits:
                first = hits[0]
                start = max(1, first - 4)
                end = min(f.line_count, start + SNIPPET_MAX_LINES - 1)
                pairs = self.index.read_lines(f.path, start, end)
                if not pairs:
                    continue
                code = "\n".join(text for _, text in pairs)
                key = f"{f.path}:{start}-{end}"
                if key in seen:
                    continue
                seen.add(key)
                result.snippets.append(Snippet(
                    path=f.path, start_line=start, end_line=end, code=code,
                    score=base_score, language=f.language,
                    reason=f"line {first} mentions {', '.join(terms[:3])}",
                ))
                used += len(code)

        result.used_chars = used
        return result

    # ------------------------------------------------------------------
    # Context fallbacks
    # ------------------------------------------------------------------
    def retrieve_focus(self, path: str, start_line: int | None = None,
                       end_line: int | None = None,
                       max_snippets: int = 2,
                       char_budget: int = CONTEXT_CHAR_BUDGET) -> RetrievalResult:
        """Evidence for an anaphoric question such as "explain this".

        The words carry no searchable term, so the code the user is actually
        looking at — a selected range, or the file they have open — is what the
        question refers to. The enclosing symbol is added when the selection is
        only part of a function, so the model sees the whole unit.
        """
        focused = self.index.get(path)
        result = RetrievalResult(terms=[])
        if focused is None:
            return result

        symbol = None
        if start_line is None or end_line is None:
            first = focused.symbols[0] if focused.symbols else None
            if first is not None and first.end_line - first.start_line + 1 <= SNIPPET_MAX_LINES:
                start, end, symbol = first.start_line, first.end_line, first
            else:
                start, end = 1, min(focused.line_count, SNIPPET_MAX_LINES)
            reason = "the file you have open"
        else:
            start = max(1, min(start_line, focused.line_count))
            end = max(start, min(end_line, focused.line_count))
            if end - start + 1 > SNIPPET_MAX_LINES:
                end = start + SNIPPET_MAX_LINES - 1
            symbol = next(
                (s for s in focused.symbols if s.start_line <= start <= s.end_line),
                None,
            )
            reason = "the lines you selected"

        pairs = self.index.read_lines(focused.path, start, end)
        if not pairs:
            return result
        code = "\n".join(text for _, text in pairs)
        result.snippets.append(Snippet(
            path=focused.path, start_line=start, end_line=end, code=code,
            score=FOCUS_SCORE, reason=reason, language=focused.language,
            symbol=symbol.name if symbol else None,
        ))
        used = len(code)

        if (symbol is not None and len(result.snippets) < max_snippets
                and used < char_budget):
            outer_start = symbol.start_line
            outer_end = min(symbol.end_line, outer_start + SNIPPET_MAX_LINES - 1)
            if (outer_start, outer_end) != (start, end) and outer_end >= outer_start:
                outer = self.index.read_lines(focused.path, outer_start, outer_end)
                if outer:
                    body = "\n".join(text for _, text in outer)
                    result.snippets.append(Snippet(
                        path=focused.path, start_line=outer_start, end_line=outer_end,
                        code=body, score=FOCUS_SCORE - 1.0,
                        reason=f"the enclosing {symbol.kind} '{symbol.name}'",
                        language=focused.language, symbol=symbol.name,
                    ))
                    used += len(body)

        result.used_chars = used
        return result

    def retrieve_overview(self, max_snippets: int = 4,
                          char_budget: int = CONTEXT_CHAR_BUDGET) -> RetrievalResult:
        """Evidence for a project-level question that matched no keyword.

        A README, the entry points and the files richest in symbols are what
        make a repository describable when the question names no symbol at all.
        """
        result = RetrievalResult(terms=[])

        def rank(f: IndexedFile) -> float:
            lower = f.path.lower()
            stem = lower.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            score = 0.0
            if stem.startswith("readme") or lower.endswith((".md", ".rst")):
                score += 30.0
            if any(hint in stem for hint in _ENTRYPOINT_HINTS):
                score += 20.0
            if classify_role(f.path) == "config":
                score += 4.0
            score += min(len(f.symbols), 8) * 1.5
            if f.language == "Python":
                score += 1.0
            return score

        ranked = sorted(self.index.files.values(), key=lambda f: (-rank(f), f.path))
        used = 0
        for f in ranked:
            if len(result.snippets) >= max_snippets or used >= char_budget:
                break
            if rank(f) <= 1.5:
                continue
            first = f.symbols[0] if f.symbols else None
            if first is not None:
                start = first.start_line
                end = min(first.end_line, start + SNIPPET_MAX_LINES - 1)
                reason = f"project overview: {first.kind} '{first.name}'"
            else:
                start, end = 1, min(f.line_count, 30)
                reason = "project overview"
            pairs = self.index.read_lines(f.path, start, end)
            if not pairs:
                continue
            code = "\n".join(text for _, text in pairs)
            result.snippets.append(Snippet(
                path=f.path, start_line=start, end_line=end, code=code,
                score=OVERVIEW_SCORE, reason=reason, language=f.language,
                symbol=first.name if first else None,
            ))
            used += len(code)

        result.used_chars = used
        return result

    def suggestions(self, limit: int = 4) -> list[dict]:
        """Clickable starting points built from this repository's own symbols.

        Returned with every answer, so a question that cannot be grounded ends
        with something the user can click instead of a dead end.
        """
        out: list[dict] = []
        seen: set[str] = set()

        def add(label: str, question: str, key: str) -> bool:
            if key in seen or len(out) >= limit:
                return False
            seen.add(key)
            out.append({"label": label, "question": question})
            return True

        for f in sorted(self.index.files.values(), key=lambda x: x.path):
            for sym in f.symbols:
                if sym.kind not in {"function", "class", "method", "route"}:
                    continue
                if len(sym.name) < 3 or sym.name.startswith("_"):
                    continue
                add(f"How does {sym.name}() work?",
                    f"How does {sym.name}() work in {f.path}?", sym.name.lower())
                if len(out) >= limit:
                    return out

        for f in sorted(self.index.files.values(), key=lambda x: x.path):
            if classify_role(f.path) == "docs":
                continue
            filename = f.path.rsplit("/", 1)[-1]
            add(f"What does {filename} do?", f"What does {f.path} do?", f.path)
            if len(out) >= limit:
                return out

        add("What does this project do?", "What does this project do?", "__overview__")
        return out
