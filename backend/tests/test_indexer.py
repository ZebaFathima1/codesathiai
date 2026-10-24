"""Tests for codebase indexing and line-number accuracy."""

from app.indexer import CodeIndex

PY_SOURCE = '''"""Module docstring."""
import os


def greet(name):
    """Say hello."""
    return f"hello {name}"


class Greeter:
    """A greeter."""

    def __init__(self, prefix):
        self.prefix = prefix

    def greet(self, name):
        return self.prefix + name
'''


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_line_numbers_are_exact(tmp_path):
    _write(tmp_path, "m.py", PY_SOURCE)
    index = CodeIndex.build(str(tmp_path))
    f = index.get("m.py")
    assert f is not None
    assert f.line_count == len(PY_SOURCE.splitlines())
    # In PY_SOURCE, `def greet` is on line 5 (1-based) and ends on line 7.
    greet = next(s for s in f.symbols if s.name == "greet")
    assert greet.start_line == 5
    assert greet.end_line == 7
    assert greet.kind == "function"
    assert f.lines[4].strip().startswith("def greet")


def test_ast_finds_classes_methods_and_imports(tmp_path):
    _write(tmp_path, "m.py", PY_SOURCE)
    index = CodeIndex.build(str(tmp_path))
    f = index.get("m.py")
    names = {s.name for s in f.symbols}
    assert {"greet", "Greeter", "Greeter.__init__", "Greeter.greet"} <= names
    assert "os" in f.imports
    assert f.parser == "ast"


def test_read_lines_is_inclusive_and_clamped(tmp_path):
    _write(tmp_path, "m.py", PY_SOURCE)
    index = CodeIndex.build(str(tmp_path))
    pairs = index.read_lines("m.py", 5, 7)
    assert [n for n, _ in pairs] == [5, 6, 7]
    # Clamped beyond EOF.
    pairs = index.read_lines("m.py", 100, 200)
    assert pairs == []


def test_python_routes_are_extracted(tmp_path):
    _write(tmp_path, "api.py", '''
from flask import Blueprint
bp = Blueprint("x", __name__)


@bp.route("/login", methods=["POST"])
def login():
    return "ok"
''')
    index = CodeIndex.build(str(tmp_path))
    f = index.get("api.py")
    assert any("/login" in r for r in f.routes)


def test_non_python_uses_regex_fallback(tmp_path):
    _write(tmp_path, "app.js", """
import express from 'express';
const app = express();

function handler(req, res) {
  res.send('hi');
}

class Widget {
  render() {}
}

app.get('/users', handler);
""")
    index = CodeIndex.build(str(tmp_path))
    f = index.get("app.js")
    assert f.parser == "regex"
    names = {s.name for s in f.symbols}
    assert "handler" in names
    assert "Widget" in names
    assert any("/users" in r for r in f.routes)


def test_unsupported_language_is_not_claimed_as_parsed(tmp_path):
    _write(tmp_path, "data.bin", "binary")
    _write(tmp_path, "notes.xyz", "some text")
    index = CodeIndex.build(str(tmp_path))
    assert index.get("notes.xyz") is None  # unknown extension is not indexed


def test_markdown_is_indexed_without_symbols(tmp_path):
    _write(tmp_path, "README.md", "# Title\n\nBody text.\n")
    index = CodeIndex.build(str(tmp_path))
    f = index.get("README.md")
    assert f is not None
    assert f.parser == "none"
    assert f.symbols == []


def test_broken_python_does_not_crash(tmp_path):
    _write(tmp_path, "broken.py", "def oops(:\n    pass\n")
    index = CodeIndex.build(str(tmp_path))
    f = index.get("broken.py")
    assert f is not None
    assert f.symbols == []


def test_file_tree_structure(tmp_path):
    _write(tmp_path, "a/b/c.py", "x = 1")
    _write(tmp_path, "a/d.md", "# d")
    index = CodeIndex.build(str(tmp_path))
    tree = index.file_tree()
    assert tree["type"] == "dir"
    names = {c["name"] for c in tree["children"]}
    assert "a" in names


def test_search_matches_paths_and_symbols(tmp_path):
    _write(tmp_path, "auth/login.py", "def login():\n    pass\n")
    index = CodeIndex.build(str(tmp_path))
    hits = index.search("login")
    assert any(h["kind"] == "file" for h in hits)
    assert any(h["kind"] == "function" for h in hits)


def test_stats_report_parser_coverage(tmp_path):
    _write(tmp_path, "a.py", "def f():\n    pass\n")
    _write(tmp_path, "b.js", "function g() {}\n")
    index = CodeIndex.build(str(tmp_path))
    stats = index.stats()
    assert stats["file_count"] == 2
    assert stats["ast_parsed_files"] == 1
    assert stats["regex_parsed_files"] == 1
