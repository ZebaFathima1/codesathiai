"""Tests for the storage layer: index rebuild, limits, and housekeeping."""
import pytest
from sqlalchemy import select

from app import config, repository
from app.db import session_scope
from app.indexer import CodeIndex
from app.models import Project, ProjectFile
from app.repository import get_project
from tests.conftest import file_entries

SOURCE = {
    "auth/login.py": (
        "def login(email, password):\n"
        "    user = User.query.filter_by(email=email).first()\n"
        "    if user is None:\n"
        "        return None\n"
        "    return generate_token(user)\n\n\n"
        "def generate_token(user):\n"
        "    return jwt.encode({'sub': user.id}, SECRET)\n"
    ),
    "config/database.py": (
        "from sqlalchemy import create_engine\n\n\n"
        "def init_db(app):\n"
        "    return create_engine(app.config['DATABASE_URL'])\n"
    ),
}


def _make_project(client, files=None, name="demo"):
    return client.post("/api/projects", json={
        "name": name, "files": file_entries(files or SOURCE),
    }).get_json()


# ---------------------------------------------------------------------------
# The rebuilt index must be identical to the filesystem-built one
# ---------------------------------------------------------------------------
def test_index_rebuilt_from_the_database_matches_the_filesystem(tmp_path, auth_client):
    """Indexing is deterministic, so the stateless rebuild must be exact.

    This is what lets a serverless function serve a project it has never seen
    in memory: it reconstructs the index from rows instead of from disk.
    """
    for path, content in SOURCE.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    from_disk = CodeIndex.build(str(tmp_path))

    _make_project(auth_client)
    with session_scope() as db:
        project = db.execute(select(Project)).scalars().first()
        from_db = repository.build_index(db, project)

    assert from_db.stats() == from_disk.stats()
    assert set(from_db.files) == set(from_disk.files)
    for path, indexed in from_disk.files.items():
        rebuilt = from_db.files[path]
        assert rebuilt.language == indexed.language
        assert rebuilt.parser == indexed.parser
        assert rebuilt.lines == indexed.lines
        assert [(s.name, s.start_line, s.end_line) for s in rebuilt.symbols] == \
               [(s.name, s.start_line, s.end_line) for s in indexed.symbols]


def test_rebuilt_index_keeps_exact_line_numbers(auth_client):
    pid = _make_project(auth_client)["project_id"]
    body = auth_client.get(f"/api/projects/{pid}/file?path=auth/login.py").get_json()
    assert body["line_count"] == len(SOURCE["auth/login.py"].splitlines())
    login = next(s for s in body["symbols"] if s["name"] == "login")
    assert login["start_line"] == 1
    assert login["end_line"] == 5
    # Line 3 of the stored file must be the third source line.
    assert body["lines"][2]["text"].strip().startswith("if user is None")


def test_index_cache_is_invalidated_when_files_change(auth_client):
    created = auth_client.post("/api/projects", json={"name": "growing"}).get_json()
    pid = created["project_id"]

    auth_client.post(f"/api/projects/{pid}/files",
                     json={"files": file_entries({"a.py": "a = 1\n"})})
    with session_scope() as db:
        first = repository.build_index(db, db.get(Project, pid))
    assert len(first.files) == 1

    auth_client.post(f"/api/projects/{pid}/files",
                     json={"files": file_entries({"b.py": "b = 2\n"})})
    with session_scope() as db:
        second = repository.build_index(db, db.get(Project, pid))
    assert set(second.files) == {"a.py", "b.py"}, "the cache must not go stale"


def test_duplicate_paths_are_not_stored_twice(auth_client):
    created = auth_client.post("/api/projects", json={"name": "dupes"}).get_json()
    pid = created["project_id"]
    auth_client.post(f"/api/projects/{pid}/files",
                     json={"files": file_entries({"a.py": "a = 1\n"})})
    auth_client.post(f"/api/projects/{pid}/files",
                     json={"files": file_entries({"a.py": "a = 999\n"})})
    with session_scope() as db:
        rows = db.execute(select(ProjectFile).where(ProjectFile.project_id == pid)).scalars().all()
        assert len(rows) == 1
        assert "999" not in rows[0].content


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
def test_storage_limit_is_enforced(auth_client, monkeypatch):
    monkeypatch.setattr(config, "MAX_STORED_BYTES", 200)
    created = auth_client.post("/api/projects", json={"name": "huge"}).get_json()
    pid = created["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/files", json={
        "files": [{"path": f"f{i}.py", "content": "x = '" + ("y" * 100) + "'\n"}
                  for i in range(10)],
    })
    assert response.status_code == 400
    assert response.get_json()["code"] == "project_too_large"


def test_oversized_single_files_are_skipped(auth_client, monkeypatch):
    monkeypatch.setattr(config, "MAX_INDEXED_FILE_BYTES", 50)
    body = auth_client.post("/api/projects", json={
        "name": "mixed",
        "files": [{"path": "big.py", "content": "x = '" + ("y" * 500) + "'\n"},
                  {"path": "small.py", "content": "s = 1\n"}],
    }).get_json()
    assert body["stats"]["file_count"] == 1


def test_unsafe_paths_are_refused(auth_client):
    for bad in ["../../etc/passwd", "/etc/passwd", "a/../../b.py", ".."]:
        response = auth_client.post("/api/projects", json={
            "name": "evil", "files": [{"path": bad, "content": "x = 1\n"}],
        })
        assert response.status_code == 400, bad
        assert response.get_json()["code"] == "unsafe_path"


def test_windows_style_paths_are_refused(auth_client):
    """A drive letter is not a path inside the project."""
    response = auth_client.post("/api/projects", json={
        "name": "win", "files": [{"path": "C:/windows/system32/a.py", "content": "x = 1\n"}],
    })
    assert response.status_code == 400
    assert response.get_json()["code"] == "unsafe_path"


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------
def test_expired_projects_are_cleaned_up(auth_client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(config, "PROJECT_TTL_SECONDS", 0)
    pid = _make_project(auth_client, name="old")["project_id"]

    with session_scope() as db:
        project = db.get(Project, pid)
        project.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        removed = repository.cleanup_expired(db)
    assert removed == 1
    assert auth_client.get(f"/api/projects/{pid}/files").status_code == 404


def test_cleanup_never_removes_the_sample_project(auth_client, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_TTL_SECONDS", 0)
    sample = auth_client.post("/api/projects/sample").get_json()["project_id"]
    with session_scope() as db:
        repository.cleanup_expired(db)
    assert auth_client.get(f"/api/projects/{sample}/files").status_code == 200


def test_project_summary_never_leaks_another_users_id(auth_client):
    created = _make_project(auth_client)
    assert "user_id" not in created
    assert set(created) >= {"project_id", "name", "source", "status", "stats"}


def test_missing_files_are_reported_clearly(auth_client):
    response = auth_client.post("/api/projects", json={"name": "x"})
    pid = response.get_json()["project_id"]
    bad = auth_client.post(f"/api/projects/{pid}/files", json={"files": "nope"})
    assert bad.status_code == 400
    assert bad.get_json()["code"] == "no_files"
