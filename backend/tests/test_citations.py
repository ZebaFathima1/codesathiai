"""Tests for citation validation."""

from app.citations import (
    Citation,
    locate_quote,
    parse_citations,
    validate_citation,
    validate_citations,
)
from app.indexer import CodeIndex

SOURCE = "line one\nline two\nline three\nline four\nline five\n"


def _index(tmp_path):
    p = tmp_path / "mod.py"
    p.write_text(SOURCE, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "other.py").write_text("a = 1\n", encoding="utf-8")
    return CodeIndex.build(str(tmp_path))


def test_valid_citation_is_verified(tmp_path):
    index = _index(tmp_path)
    c = Citation("mod.py", 1, 3, quote="line one\nline two")
    ok, reason = validate_citation(c, index)
    assert ok is True


def test_unknown_file_is_rejected(tmp_path):
    index = _index(tmp_path)
    ok, reason = validate_citation(Citation("nope.py", 1, 2), index)
    assert ok is False
    assert "not a file" in reason


def test_line_beyond_eof_is_rejected(tmp_path):
    index = _index(tmp_path)
    ok, reason = validate_citation(Citation("mod.py", 99, 120), index)
    assert ok is False
    assert "beyond the end" in reason


def test_reversed_range_is_rejected(tmp_path):
    index = _index(tmp_path)
    ok, reason = validate_citation(Citation("mod.py", 4, 2), index)
    assert ok is False
    assert "before start" in reason


def test_zero_start_is_rejected(tmp_path):
    index = _index(tmp_path)
    ok, reason = validate_citation(Citation("mod.py", 0, 0), index)
    assert ok is False


def test_quote_mismatch_is_rejected(tmp_path):
    index = _index(tmp_path)
    c = Citation("mod.py", 1, 2, quote="this text is definitely not in the file")
    ok, reason = validate_citation(c, index)
    assert ok is False
    assert "quoted text" in reason


def test_quote_matching_across_whitespace_is_accepted(tmp_path):
    index = _index(tmp_path)
    c = Citation("mod.py", 1, 2, quote="line one   line two")
    ok, _ = validate_citation(c, index)
    assert ok is True


def test_traversal_path_is_rejected(tmp_path):
    index = _index(tmp_path)
    ok, _ = validate_citation(Citation("../../etc/passwd", 1, 2), index)
    assert ok is False


def test_context_flag_marks_out_of_context_but_verifies(tmp_path):
    index = _index(tmp_path)
    c = Citation("mod.py", 1, 2)
    ok, reason = validate_citation(c, index, context_ids={"mod.py:4-5"})
    assert ok is True
    assert "outside the retrieved context" in reason


def test_validate_citations_splits_lists(tmp_path):
    index = _index(tmp_path)
    citations = [
        Citation("mod.py", 1, 2),
        Citation("missing.py", 1, 2),
    ]
    verified, rejected = validate_citations(citations, index)
    assert len(verified) == 1
    assert len(rejected) == 1
    assert rejected[0]["verified"] is False
    assert "rejection_reason" in rejected[0]


def test_parse_citations_handles_loose_shapes():
    parsed = parse_citations([
        {"file": "a.py", "start": "3", "end": "5", "snippet": "x"},
        {"path": "b.py"},
        "garbage",
        42,
    ])
    assert len(parsed) == 2
    assert parsed[0].path == "a.py"
    assert parsed[0].start_line == 3
    assert parsed[1].start_line == 0


def test_parse_citations_ignores_non_list():
    assert parse_citations(None) == []
    assert parse_citations(42) == []
    assert parse_citations("not a citation") == []


def test_parse_citations_accepts_a_single_object():
    # Models sometimes return one object instead of an array of one.
    parsed = parse_citations({"path": "a.py", "lines": "3-5"})
    assert len(parsed) == 1
    assert parsed[0].start_line == 3
    assert parsed[0].end_line == 5


def test_parse_citations_handles_the_lines_string_shape():
    # Observed live: the model labels the range as "lines": "39-39".
    parsed = parse_citations([
        {"path": "auth/login.py", "quote": "token = generate_token(user)", "lines": "56-56"},
        {"path": "app.py", "quote": "x", "line_range": "26 to 31"},
        {"path": "b.py", "quote": "y", "line": 7},
    ])
    assert [(c.start_line, c.end_line) for c in parsed] == [(56, 56), (26, 31), (7, 7)]


def test_parse_citations_handles_bare_path_strings():
    parsed = parse_citations(["auth/login.py:39-61", "src/app.py", "just some prose"])
    assert len(parsed) == 2
    assert parsed[0].path == "auth/login.py"
    assert (parsed[0].start_line, parsed[0].end_line) == (39, 61)


def test_locate_quote_finds_a_single_line():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "m.py").write_text(SOURCE, encoding="utf-8")
        index = CodeIndex.build(tmp)
        assert locate_quote(index, "m.py", "line three") == (3, 3)
        assert locate_quote(index, "m.py", "line two line three") == (2, 3)
        assert locate_quote(index, "m.py", "not present at all") is None
        assert locate_quote(index, "missing.py", "line three") is None


def test_citation_without_lines_is_recovered_from_its_quote():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "m.py").write_text(SOURCE, encoding="utf-8")
        index = CodeIndex.build(tmp)
        # No line numbers at all, but a quote we can locate.
        ok, _ = validate_citation(Citation("m.py", 0, 0, quote="line four"), index)
        assert ok is True


def test_citation_with_no_lines_and_no_quote_is_rejected():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "m.py").write_text(SOURCE, encoding="utf-8")
        index = CodeIndex.build(tmp)
        ok, reason = validate_citation(Citation("m.py", 0, 0), index)
        assert ok is False
        assert "missing or invalid start line" in reason


def test_leading_slash_is_stripped():
    parsed = parse_citations([{"path": "/src/a.py", "start_line": 1, "end_line": 2}])
    assert parsed[0].path == "src/a.py"
