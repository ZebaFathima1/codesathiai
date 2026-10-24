"""Tests for evidence retrieval."""

from app.indexer import CodeIndex
from app.retrieval import Retriever, extract_terms

SAMPLE = {
    "auth/login.py": '''
from models.user import User
from utils.security import check_password


def login(email, password):
    user = User.query.filter_by(email=email).first()
    if user is None or not check_password(password, user.password_hash):
        return None
    return issue_token(user)
''',
    "config/database.py": '''
from sqlalchemy import create_engine


def init_db(app):
    engine = create_engine(app.config["DATABASE_URL"])
    return engine
''',
    "models/user.py": '''
class User:
    __tablename__ = "users"
    email = None
    password_hash = None
''',
    "README.md": "# Project\n\nA small service.\n",
}


def _index(tmp_path):
    for name, content in SAMPLE.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return CodeIndex.build(str(tmp_path))


def test_terms_are_extracted_and_expanded():
    terms = extract_terms("Ee project lo login process ela work avutundi?")
    assert "login" in terms
    assert "password" in terms      # lexicon expansion
    assert "ela" not in terms       # stopword removed


def test_retrieval_finds_login_code(tmp_path):
    retriever = Retriever(_index(tmp_path))
    result = retriever.retrieve("How does login work?")
    assert result.snippets
    assert result.snippets[0].path == "auth/login.py"
    assert result.snippets[0].start_line <= 6 <= result.snippets[0].end_line


def test_retrieval_finds_database_config(tmp_path):
    retriever = Retriever(_index(tmp_path))
    result = retriever.retrieve("Where is the database configured?")
    paths = [s.path for s in result.snippets]
    assert "config/database.py" in paths


def test_snippets_carry_provenance(tmp_path):
    retriever = Retriever(_index(tmp_path))
    result = retriever.retrieve("Explain the User model")
    for snippet in result.snippets:
        assert snippet.path in SAMPLE
        assert 1 <= snippet.start_line <= snippet.end_line
        assert snippet.citation_id == f"{snippet.path}:{snippet.start_line}-{snippet.end_line}"
        assert snippet.reason


def test_snippet_code_matches_source_lines(tmp_path):
    retriever = Retriever(_index(tmp_path))
    result = retriever.retrieve("How does login work?")
    snippet = result.snippets[0]
    source = SAMPLE[snippet.path].splitlines()
    expected = "\n".join(source[snippet.start_line - 1:snippet.end_line])
    assert snippet.code == expected


def test_respects_max_snippets(tmp_path):
    retriever = Retriever(_index(tmp_path))
    result = retriever.retrieve("login database user project", max_snippets=2)
    assert len(result.snippets) <= 2


def test_respects_char_budget(tmp_path):
    retriever = Retriever(_index(tmp_path))
    result = retriever.retrieve("login database user", char_budget=200)
    assert result.used_chars <= 400  # one snippet may overshoot slightly


def test_irrelevant_question_returns_nothing(tmp_path):
    retriever = Retriever(_index(tmp_path))
    result = retriever.retrieve("zzzzqqqq")
    assert result.snippets == []


def test_no_snippet_exceeds_line_cap(tmp_path):
    retriever = Retriever(_index(tmp_path))
    result = retriever.retrieve("login database user project", max_snippets=8)
    for snippet in result.snippets:
        assert snippet.end_line - snippet.start_line + 1 <= 60


# --------------------------------------------------------------------------
# Regression: the retriever must not let documentation that *mentions* the
# question outrank the code that *implements* it.
#
# This reproduces a real reported bug: a repository whose README contained the
# demo question ("Ee project lo login process ela work avutundi?") made the
# model answer about the tooling instead of the login flow.
# --------------------------------------------------------------------------
from app.retrieval import classify_role  # noqa: E402

DOCS_AND_CODE = {
    "auth/login.py": (
        "def login(email, password):\n"
        "    user = User.query.filter_by(email=email).first()\n"
        "    if user is None or not check_password(password, user.password_hash):\n"
        "        return None\n"
        "    return generate_token(user)\n\n\n"
        "def generate_token(user):\n"
        "    return jwt.encode({'sub': user.id}, SECRET, algorithm='HS256')\n"
    ),
    "README.md": (
        "# The Tool\n\n"
        "## Demo script\n\n"
        "Ask: Ee project lo login process ela work avutundi?\n\n"
        "The login process is explained by the login function. Login login login.\n"
        "Login is verified with a password and a token and a session and auth.\n"
    ),
    "tests/test_login.py": (
        "def test_login_rejects_a_bad_password():\n"
        "    assert login('a@b.c', 'wrong') is None\n"
    ),
}


def _mixed_index(tmp_path):
    for name, content in DOCS_AND_CODE.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return CodeIndex.build(str(tmp_path))


def test_role_classification():
    assert classify_role("auth/login.py") == "implementation"
    assert classify_role("README.md") == "docs"
    assert classify_role("docs/guide.rst") == "docs"
    assert classify_role("tests/test_api.py") == "test"
    assert classify_role("api/users.test.ts") == "test"
    assert classify_role("config/settings.yaml") == "config"


def test_implementation_outranks_documentation_that_quotes_the_question(tmp_path):
    retriever = Retriever(_mixed_index(tmp_path))
    result = retriever.retrieve("Ee project lo login process ela work avutundi?")

    paths = [s.path for s in result.snippets]
    assert "auth/login.py" in paths, "the implementing file must be retrieved"
    assert result.snippets[0].path == "auth/login.py"
    # The README mentions "login" more often than the code does, but it must
    # not be sent as evidence for a question about behaviour.
    assert "README.md" not in paths


def test_diluting_files_are_dropped(tmp_path):
    retriever = Retriever(_mixed_index(tmp_path))
    result = retriever.retrieve("Ee project lo login process ela work avutundi?")
    # A focused question should yield a focused context, not every file that
    # happens to contain the word.
    assert len(result.snippets) <= 3
    for snippet in result.snippets:
        assert snippet.score >= result.snippets[0].score * 0.45


def test_dominant_file_contributes_more_than_one_function(tmp_path):
    retriever = Retriever(_mixed_index(tmp_path))
    result = retriever.retrieve("How does login work?")
    symbols = {s.symbol for s in result.snippets if s.path == "auth/login.py"}
    assert "login" in symbols
    assert "generate_token" in symbols


def test_overview_question_still_allows_documentation(tmp_path):
    retriever = Retriever(_mixed_index(tmp_path))
    result = retriever.retrieve("Explain the project architecture and structure")
    paths = [s.path for s in result.snippets]
    assert paths, "an overview question should still retrieve something"
    assert any(p.endswith(".md") or p.endswith(".py") for p in paths)


def test_no_snippet_is_returned_twice(tmp_path):
    retriever = Retriever(_mixed_index(tmp_path))
    result = retriever.retrieve("login token password auth session")
    ids = [s.citation_id for s in result.snippets]
    assert len(ids) == len(set(ids))
