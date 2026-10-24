"""Codebase indexing.

Turns a directory of source files into a searchable index that preserves
*exact* original line numbers. Python files are parsed with the standard
``ast`` module, which gives precise function, class, method and import
locations. Every other language falls back to a conservative regex scanner
that finds declarations but does not pretend to be a full parser — each file
records which strategy produced its symbols.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field

from .config import MAX_INDEXED_FILES, MAX_INDEXED_FILE_BYTES
from .security import IGNORED_DIRS

LANGUAGE_BY_EXT = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".cxx": "C++",
    ".hpp": "C++", ".hh": "C++",
    ".cs": "C#", ".go": "Go", ".rb": "Ruby", ".php": "PHP", ".rs": "Rust",
    ".swift": "Swift", ".scala": "Scala", ".sh": "Shell", ".bash": "Shell",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".sass": "Sass", ".less": "Less", ".vue": "Vue", ".svelte": "Svelte",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    ".ini": "INI", ".cfg": "INI", ".conf": "Config", ".properties": "Config",
    ".xml": "XML", ".md": "Markdown", ".markdown": "Markdown", ".rst": "reST",
    ".txt": "Text", ".sql": "SQL",
}


@dataclass
class Symbol:
    """A named declaration inside a file."""

    name: str
    kind: str            # function | method | class | route
    start_line: int      # 1-based, inclusive
    end_line: int        # 1-based, inclusive
    signature: str = ""
    docstring: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "docstring": self.docstring,
        }


@dataclass
class IndexedFile:
    """One indexed source file."""

    path: str                       # POSIX-style, relative to the project root
    language: str
    lines: list[str]
    size: int
    parser: str                     # "ast" | "regex" | "none"
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def line_count(self) -> int:
        return len(self.lines)

    def to_dict(self, include_lines: bool = False) -> dict:
        payload = {
            "path": self.path,
            "language": self.language,
            "line_count": self.line_count,
            "size": self.size,
            "parser": self.parser,
            "truncated": self.truncated,
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": self.imports[:40],
            "routes": self.routes,
        }
        if include_lines:
            payload["lines"] = self.lines
        return payload


# --------------------------------------------------------------------------
# Python: precise AST pass
# --------------------------------------------------------------------------
def _signature_of(node: ast.AST, lines: list[str]) -> str:
    line = lines[node.lineno - 1].strip() if 0 <= node.lineno - 1 < len(lines) else ""
    return line[:200]


def _parse_python(text: str, lines: list[str]) -> tuple[list[Symbol], list[str], list[str]]:
    symbols: list[Symbol] = []
    imports: list[str] = []
    routes: list[str] = []

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols, imports, routes

    route_re = re.compile(r"\.(route|get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]")

    def visit(node: ast.AST, prefix: str = "", owner: str | None = None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = child.lineno
                if child.decorator_list:
                    start = min(d.lineno for d in child.decorator_list)
                end = getattr(child, "end_lineno", child.lineno) or child.lineno
                kind = "method" if owner else "function"
                name = f"{prefix}{child.name}"
                doc = ast.get_docstring(child) or ""
                symbols.append(Symbol(name, kind, start, end,
                                      _signature_of(child, lines), doc[:400]))
                # Flask-style routes declared via decorators.
                for dec in child.decorator_list:
                    seg = ast.get_source_segment(text, dec) or ""
                    m = route_re.search(seg)
                    if m:
                        verb = m.group(1).upper().replace("ROUTE", "ANY")
                        route = m.group(2)
                        routes.append(f"{verb} {route} -> {name}")
                visit(child, prefix=name + ".", owner=name)
            elif isinstance(child, ast.ClassDef):
                start = child.lineno
                if child.decorator_list:
                    start = min(d.lineno for d in child.decorator_list)
                end = getattr(child, "end_lineno", child.lineno) or child.lineno
                name = f"{prefix}{child.name}"
                symbols.append(Symbol(name, "class", start, end,
                                      _signature_of(child, lines),
                                      (ast.get_docstring(child) or "")[:400]))
                visit(child, prefix=name + ".", owner=name)
            elif isinstance(child, ast.Import):
                for alias in child.names:
                    imports.append(alias.name)
            elif isinstance(child, ast.ImportFrom):
                mod = child.module or ""
                imports.append(mod)
                for alias in child.names:
                    imports.append(f"{mod}.{alias.name}" if mod else alias.name)
            else:
                visit(child, prefix=prefix, owner=owner)

    visit(tree)
    return symbols, imports, routes


# --------------------------------------------------------------------------
# Other languages: conservative regex fallback
# --------------------------------------------------------------------------
_REGEX_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
    ("function", re.compile(r"^\s*(?:public|private|protected|static|final|async|\s)*\s*(?:[A-Za-z_$][\w$<>\[\],.\s]*?)\s+([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*(?:throws[\w\s,]*)?\{")),
    ("function", re.compile(r"^\s*(?:def|func|fn)\s+([A-Za-z_$][\w$]*)\s*\(")),
    ("class", re.compile(r"^\s*(?:public|private|abstract|final|\s)*class\s+([A-Za-z_$][\w$]*)")),
    ("class", re.compile(r"^\s*(?:public\s+)?(?:struct|interface|enum|trait|object)\s+([A-Za-z_$][\w$]*)")),
]

_JS_ROUTE_RE = re.compile(r"\.(get|post|put|patch|delete)\s*\(\s*['\"]([^'\"]+)['\"]")


def _parse_regex(text: str, lines: list[str], language: str) -> tuple[list[Symbol], list[str], list[str]]:
    symbols: list[Symbol] = []
    imports: list[str] = []
    routes: list[str] = []

    for idx, line in enumerate(lines, start=1):
        for kind, pattern in _REGEX_PATTERNS:
            m = pattern.match(line)
            if m:
                symbols.append(Symbol(m.group(1), kind, idx, idx, line.strip()[:200]))
                break
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from ") or stripped.startswith("#include"):
            imports.append(stripped[:160])
        elif stripped.startswith("require(") or "require(" in stripped[:40]:
            imports.append(stripped[:160])
        rm = _JS_ROUTE_RE.search(line)
        if rm:
            routes.append(f"{rm.group(1).upper()} {rm.group(2)}")

    return symbols, imports, routes


def index_content(path: str, text: str, size: int | None = None) -> IndexedFile | None:
    """Index one file's text. Returns None when the language is unsupported.

    Shared by the filesystem walk and the database rebuild so both produce
    identical results.
    """
    ext = os.path.splitext(path)[1].lower()
    language = LANGUAGE_BY_EXT.get(ext)
    if language is None:
        return None

    lines = text.splitlines()
    indexed = IndexedFile(
        path=path,
        language=language,
        lines=lines,
        size=size if size is not None else len(text.encode("utf-8")),
        parser="none",
    )

    if language == "Python":
        indexed.parser = "ast"
        indexed.symbols, indexed.imports, indexed.routes = _parse_python(text, lines)
    elif language in {"JSON", "Markdown", "Text", "YAML", "TOML", "INI", "Config", "XML", "reST"}:
        indexed.parser = "none"
    else:
        indexed.parser = "regex"
        indexed.symbols, indexed.imports, indexed.routes = _parse_regex(text, lines, language)

    return indexed


# --------------------------------------------------------------------------
# Index construction
# --------------------------------------------------------------------------
class CodeIndex:
    """Searchable index of a project directory."""

    def __init__(self) -> None:
        self.files: dict[str, IndexedFile] = {}
        self.root: str = ""
        self.total_lines: int = 0
        self.skipped: list[str] = []

    # -- construction ------------------------------------------------------
    @classmethod
    def build(cls, root: str) -> "CodeIndex":
        index = cls()
        index.root = os.path.realpath(root)
        found = 0

        for dirpath, dirnames, filenames in os.walk(index.root):
            dirnames[:] = sorted(
                d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")
            )
            for fname in sorted(filenames):
                if found >= MAX_INDEXED_FILES:
                    index.skipped.append("file_limit_reached")
                    return index
                abspath = os.path.join(dirpath, fname)
                if os.path.islink(abspath):
                    continue
                try:
                    size = os.path.getsize(abspath)
                except OSError:
                    continue

                rel = os.path.relpath(abspath, index.root).replace(os.sep, "/")

                if size > MAX_INDEXED_FILE_BYTES:
                    index.skipped.append(rel)
                    continue

                try:
                    with open(abspath, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    index.skipped.append(rel)
                    continue

                indexed = index_content(rel, text, size)
                if indexed is None:
                    index.skipped.append(rel)
                    continue
                index.files[rel] = indexed
                index.total_lines += indexed.line_count
                found += 1

        return index

    @classmethod
    def from_records(cls, records, root: str = "") -> "CodeIndex":
        """Build an index from ``(path, content)`` pairs held in the database.

        Serverless functions have no persistent filesystem, so the index is
        rebuilt from stored rows on demand. Because indexing is deterministic,
        this produces exactly the same index the file-based path would.
        """
        index = cls()
        index.root = root
        for path, content in records:
            rel = str(path).replace(os.sep, "/")
            text = content or ""
            indexed = index_content(rel, text, len(text.encode("utf-8")))
            if indexed is None:
                index.skipped.append(rel)
                continue
            index.files[rel] = indexed
            index.total_lines += indexed.line_count
        return index

    # -- lookups -----------------------------------------------------------
    def get(self, path: str) -> IndexedFile | None:
        return self.files.get(path.replace("\\", "/").lstrip("/"))

    def has(self, path: str) -> bool:
        return self.get(path) is not None

    def read_lines(self, path: str, start: int, end: int) -> list[tuple[int, str]]:
        """Return ``(line_number, text)`` pairs for an inclusive 1-based range."""
        f = self.get(path)
        if f is None:
            return []
        start = max(1, start)
        end = min(f.line_count, end)
        return [(n, f.lines[n - 1]) for n in range(start, end + 1)]

    def file_tree(self) -> dict:
        """Nested tree of directories and files for the sidebar."""
        root: dict = {"name": "", "path": "", "type": "dir", "children": []}
        dirs: dict[str, dict] = {"": root}

        for path in sorted(self.files):
            parts = path.split("/")
            parent = ""
            for part in parts[:-1]:
                key = f"{parent}/{part}" if parent else part
                if key not in dirs:
                    node = {"name": part, "path": key, "type": "dir", "children": []}
                    dirs[parent]["children"].append(node)
                    dirs[key] = node
                parent = key
            f = self.files[path]
            dirs[parent]["children"].append({
                "name": parts[-1],
                "path": path,
                "type": "file",
                "language": f.language,
                "line_count": f.line_count,
            })
        return root

    def search(self, query: str, limit: int = 40) -> list[dict]:
        """Substring search across paths and symbol names."""
        q = query.strip().lower()
        if not q:
            return []
        hits: list[dict] = []
        for path, f in self.files.items():
            if q in path.lower():
                hits.append({"path": path, "kind": "file", "name": path})
            for sym in f.symbols:
                if q in sym.name.lower():
                    hits.append({
                        "path": path,
                        "kind": sym.kind,
                        "name": sym.name,
                        "start_line": sym.start_line,
                        "end_line": sym.end_line,
                    })
            if len(hits) >= limit:
                break
        return hits[:limit]

    def stats(self) -> dict:
        by_lang: dict[str, int] = {}
        for f in self.files.values():
            by_lang[f.language] = by_lang.get(f.language, 0) + 1
        return {
            "file_count": len(self.files),
            "total_lines": self.total_lines,
            "languages": dict(sorted(by_lang.items(), key=lambda kv: -kv[1])),
            "symbol_count": sum(len(f.symbols) for f in self.files.values()),
            "ast_parsed_files": sum(1 for f in self.files.values() if f.parser == "ast"),
            "regex_parsed_files": sum(1 for f in self.files.values() if f.parser == "regex"),
        }
