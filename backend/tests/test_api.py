"""End-to-end tests for the HTTP API."""
import json

import pytest

from tests.conftest import file_entries, zip_upload

SAMPLE_FILES = {
    "src/login.py": (
        "from utils.security import check_password\n\n\n"
        "def login(email, password):\n"
        "    user = find_user(email)\n"
        "    if not check_password(password, user.hash):\n"
        "        return None\n"
        "    return issue_token(user)\n"
    ),
    "src/database.py": (
        "from sqlalchemy import create_engine\n\n\n"
        "def init_db(url):\n"
        "    return create_engine(url)\n"
    ),
    "README.md": "# Demo project\n\nLogin and database demo.\n",
}


def _upload_archive(client, files=None, name="demo"):
    """Upload via the server-side ZIP path."""
    data = {"file": zip_upload(files or SAMPLE_FILES)}
    if name:
        data["name"] = name
    return client.post("/api/projects/upload", data=data,
                       content_type="multipart/form-data")


def _upload_batch(client, files=None, name="demo"):
    """Upload the way the browser does: JSON batches."""
    return client.post("/api/projects", json={
        "name": name, "files": file_entries(files or SAMPLE_FILES),
    })


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
def test_health_reports_configuration_without_secrets(client):
    body = client.get("/api/health").get_json()
    assert body["status"] == "ok"
    assert body["sarvam"]["configured"] is False
    assert body["auth"]["password_signup"] is True
    assert body["storage"]["backend"].startswith("sqlite")
    assert "sk_" not in json.dumps(body)
    assert set(body["languages"]) >= {"te-IN", "en-IN", "hi-IN", "ta-IN"}


def test_health_reports_configured_when_key_present(client, configured_key):
    assert client.get("/api/health").get_json()["sarvam"]["configured"] is True


def test_health_flags_ephemeral_storage_only_on_a_host(client, monkeypatch):
    """A local SQLite file persists; one on a host does not, and the UI says so."""
    storage = client.get("/api/health").get_json()["storage"]
    assert storage["backend"].startswith("sqlite")
    assert storage["ephemeral"] is False

    monkeypatch.setenv("RENDER", "1")
    assert client.get("/api/health").get_json()["storage"]["ephemeral"] is True


# ---------------------------------------------------------------------------
# Sample project
# ---------------------------------------------------------------------------
def test_sample_project_is_public_and_seeded(client):
    body = client.post("/api/projects/sample").get_json()
    assert body["source"] == "sample"
    assert body["stats"]["file_count"] > 0
    assert body["stats"]["ast_parsed_files"] > 0


def test_sample_project_is_not_duplicated_on_reload(client):
    first = client.post("/api/projects/sample").get_json()["project_id"]
    second = client.post("/api/projects/sample").get_json()["project_id"]
    assert first == second


def test_sample_project_files_and_tree(client, sample_project):
    pid = sample_project["project_id"]
    body = client.get(f"/api/projects/{pid}/files").get_json()
    assert body["tree"]["type"] == "dir"
    paths = {f["path"] for f in body["files"]}
    assert "auth/login.py" in paths
    assert "config/database.py" in paths


# ---------------------------------------------------------------------------
# Upload — server-side ZIP
# ---------------------------------------------------------------------------
def test_archive_upload_indexes_repository(auth_client):
    response = _upload_archive(auth_client)
    assert response.status_code == 201, response.get_json()
    body = response.get_json()
    assert body["stats"]["file_count"] == 3
    assert body["name"] == "demo"
    assert body["status"] == "ready"


def test_archive_upload_requires_authentication(client):
    assert _upload_archive(client).status_code == 401


def test_archive_upload_requires_a_file(auth_client):
    response = auth_client.post("/api/projects/upload", data={},
                                content_type="multipart/form-data")
    assert response.status_code == 400
    assert response.get_json()["code"] == "missing_file"


def test_archive_upload_rejects_non_zip(auth_client):
    response = auth_client.post(
        "/api/projects/upload",
        data={"file": zip_upload({"a.py": "x"}, "notes.txt")},
        content_type="multipart/form-data")
    assert response.status_code == 400
    assert response.get_json()["code"] == "unsupported_filetype"


def test_archive_upload_rejects_only_binaries(auth_client):
    response = _upload_archive(auth_client, {"logo.png": "x", "app.exe": "y"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "no_source_files"


def test_archive_upload_ignores_dependency_folders(auth_client):
    response = _upload_archive(auth_client, {
        "node_modules/x/index.js": "x",
        ".git/config": "x",
        "src/main.py": "print(1)\n",
    })
    assert response.status_code == 201
    assert response.get_json()["stats"]["file_count"] == 1


def test_archive_upload_recovers_a_deeply_nested_single_folder(auth_client):
    """A ZIP of a folder usually nests everything one level down."""
    response = _upload_archive(auth_client, {"my-project/src/app.py": "print(1)\n"})
    assert response.status_code == 201
    pid = response.get_json()["project_id"]
    paths = {f["path"] for f in auth_client.get(f"/api/projects/{pid}/files").get_json()["files"]}
    assert paths == {"my-project/src/app.py"}


# ---------------------------------------------------------------------------
# Upload — browser batches (the Vercel path)
# ---------------------------------------------------------------------------
def test_batch_upload_creates_and_finalizes(auth_client):
    created = auth_client.post("/api/projects", json={
        "name": "batched",
        "files": file_entries({"src/a.py": "a = 1\n"}),
    })
    assert created.status_code == 201
    pid = created.get_json()["project_id"]
    assert created.get_json()["status"] == "ready"

    appended = auth_client.post(f"/api/projects/{pid}/files", json={
        "files": file_entries({"src/b.py": "b = 2\n"}),
    })
    assert appended.status_code == 400
    assert appended.get_json()["code"] == "project_already_finalized"


def test_multi_batch_upload_then_finalize(auth_client):
    """The exact sequence the browser performs for a large repository."""
    created = auth_client.post("/api/projects", json={
        "name": "big", "files": file_entries({"src/a.py": "a = 1\n"}),
    })
    assert created.status_code == 201
    pid = created.get_json()["project_id"]

    # A second batch requires the project to still be open, so create one
    # without files first.
    opened = auth_client.post("/api/projects", json={"name": "big2"}).get_json()
    pid = opened["project_id"]
    assert opened["status"] == "uploading"

    for i in range(3):
        response = auth_client.post(f"/api/projects/{pid}/files", json={
            "files": file_entries({f"src/mod{i}.py": f"value = {i}\n"}),
        })
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["stored_files"] == 1

    done = auth_client.post(f"/api/projects/{pid}/finalize")
    assert done.status_code == 200
    assert done.get_json()["status"] == "ready"
    assert done.get_json()["stats"]["file_count"] == 3


def test_finalize_rejects_an_empty_project(auth_client):
    pid = auth_client.post("/api/projects", json={"name": "empty"}).get_json()["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/finalize")
    assert response.status_code == 400
    assert response.get_json()["code"] == "no_source_files"


def test_batch_upload_skips_unsupported_files(auth_client):
    body = auth_client.post("/api/projects", json={
        "name": "mixed",
        "files": [{"path": "a.py", "content": "x = 1\n"},
                  {"path": "image.png", "content": "binary-ish"},
                  {"path": "notes.xyz", "content": "unknown language"}],
    }).get_json()
    assert body["stats"]["file_count"] == 1


def test_batch_upload_rejects_path_traversal(auth_client):
    response = auth_client.post("/api/projects", json={
        "name": "evil",
        "files": [{"path": "../../etc/passwd", "content": "root:x:0:0"}],
    })
    assert response.status_code == 400
    assert response.get_json()["code"] == "unsafe_path"


def test_creating_a_project_without_files_starts_a_batched_upload(auth_client):
    """An empty create is legitimate: batches follow, then finalize."""
    response = auth_client.post("/api/projects", json={"name": "none", "files": []})
    assert response.status_code == 201
    assert response.get_json()["status"] == "uploading"
    assert response.get_json()["stats"] == {}


def test_appending_to_someone_elses_project_is_refused(auth_client, second_client):
    pid = auth_client.post("/api/projects", json={"name": "mine"}).get_json()["project_id"]
    response = second_client.post(f"/api/projects/{pid}/files", json={
        "files": file_entries({"x.py": "x = 1"}),
    })
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# File access
# ---------------------------------------------------------------------------
def test_file_content_has_line_numbers(auth_client):
    pid = _upload_batch(auth_client).get_json()["project_id"]
    body = auth_client.get(f"/api/projects/{pid}/file?path=src/login.py").get_json()
    assert body["lines"][0]["number"] == 1
    assert body["lines"][0]["text"].startswith("from utils.security")


def test_file_range_query(auth_client):
    pid = _upload_batch(auth_client).get_json()["project_id"]
    body = auth_client.get(
        f"/api/projects/{pid}/file?path=src/login.py&start=4&end=5").get_json()
    assert [ln["number"] for ln in body["lines"]] == [4, 5]


def test_file_path_outside_project_is_rejected(auth_client):
    pid = _upload_batch(auth_client).get_json()["project_id"]
    for bad in ["../../etc/passwd", "/etc/passwd", "does/not/exist.py"]:
        response = auth_client.get(f"/api/projects/{pid}/file?path={bad}")
        assert response.status_code == 400
        assert response.get_json()["code"] == "path_not_in_project"


def test_file_requires_path_param(auth_client):
    pid = _upload_batch(auth_client).get_json()["project_id"]
    response = auth_client.get(f"/api/projects/{pid}/file")
    assert response.status_code == 400
    assert response.get_json()["code"] == "missing_path"


def test_search_endpoint(auth_client):
    pid = _upload_batch(auth_client).get_json()["project_id"]
    body = auth_client.get(f"/api/projects/{pid}/search?q=login").get_json()
    assert any(h["path"] == "src/login.py" for h in body["results"])


def test_search_requires_two_chars(auth_client):
    pid = _upload_batch(auth_client).get_json()["project_id"]
    assert auth_client.get(f"/api/projects/{pid}/search?q=a").status_code == 400


# ---------------------------------------------------------------------------
# Project id validation
# ---------------------------------------------------------------------------
def test_invalid_project_id_is_rejected(client):
    response = client.get("/api/projects/not-a-uuid/files")
    assert response.status_code == 400
    assert response.get_json()["code"] == "bad_project_id"


def test_unknown_project_id_is_404(client):
    response = client.get("/api/projects/123e4567-e89b-12d3-a456-426614174000/files")
    assert response.status_code == 404
    assert response.get_json()["code"] == "project_not_found"


def test_delete_project(auth_client):
    pid = _upload_batch(auth_client).get_json()["project_id"]
    assert auth_client.delete(f"/api/projects/{pid}").status_code == 200
    assert auth_client.get(f"/api/projects/{pid}/files").status_code == 404


def test_deleting_a_project_removes_its_files(auth_client):
    from sqlalchemy import select
    from app.db import session_scope
    from app.models import ProjectFile

    pid = _upload_batch(auth_client).get_json()["project_id"]
    auth_client.delete(f"/api/projects/{pid}")
    with session_scope() as db:
        remaining = db.execute(
            select(ProjectFile).where(ProjectFile.project_id == pid)
        ).scalars().all()
        assert remaining == []


# ---------------------------------------------------------------------------
# Ask: validation
# ---------------------------------------------------------------------------
def test_ask_requires_question(auth_client, sample_project):
    pid = sample_project["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask", json={"question": "  "})
    assert response.status_code == 400
    assert response.get_json()["code"] == "missing_question"


def test_ask_rejects_unsupported_language(auth_client, sample_project):
    pid = sample_project["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask",
                                json={"question": "how does login work?",
                                      "language": "fr-FR"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "unsupported_language"


def test_ask_rejects_bad_history(auth_client, sample_project):
    pid = sample_project["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask",
                                json={"question": "login?", "history": "nope"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "bad_history"


def test_ask_rejects_non_object_body(auth_client, sample_project):
    pid = sample_project["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask", data="[]",
                                content_type="application/json")
    assert response.status_code == 400


def test_ask_rejects_overlong_question(auth_client, sample_project):
    pid = sample_project["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask", json={"question": "x" * 3000})
    assert response.status_code == 400
    assert response.get_json()["code"] == "question_too_long"


# ---------------------------------------------------------------------------
# Ask: no-key behaviour must be honest
# ---------------------------------------------------------------------------
def test_ask_without_api_key_returns_setup_error(auth_client, sample_project):
    pid = sample_project["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask",
                                json={"question": "How does login work?",
                                      "language": "en-IN"})
    assert response.status_code == 503
    body = response.get_json()
    assert body["code"] == "sarvam_not_configured"
    assert "SARVAM_API_KEY" in body["error"]


def test_ask_with_no_evidence_does_not_call_sarvam(auth_client, configured_key, monkeypatch):
    called = {"n": 0}

    class Exploding:
        def __init__(self, *a, **k):
            called["n"] += 1
            raise AssertionError("Sarvam must not be called with no evidence")

    monkeypatch.setattr("app.routes.SarvamClient", Exploding)

    pid = _upload_batch(auth_client).get_json()["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask",
                                json={"question": "zzzqqqxyw", "language": "en-IN"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["sarvam_called"] is False
    assert body["answer"] is None
    assert "No relevant source code" in body["uncertainty"]
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Ask: happy path with a stubbed Sarvam
# ---------------------------------------------------------------------------
class StubSarvam:
    """Records the request and returns a well-formed structured answer."""

    last_kwargs = None

    def __init__(self, *args, **kwargs):
        pass

    def answer(self, question, language, retrieval, history=None):
        StubSarvam.last_kwargs = {
            "question": question, "language": language,
            "snippets": retrieval.snippets, "history": history,
        }
        snippet = retrieval.snippets[0]
        payload = {
            "answer": "Login checks the password hash and issues a token.",
            "steps": [{"title": "Look up the user", "detail": "By email."}],
            "key_files": [{"path": snippet.path, "symbol": "login", "role": "entry point"}],
            "citations": [{
                "path": snippet.path,
                "start_line": snippet.start_line,
                "end_line": snippet.end_line,
                "note": "login function",
            }],
            "uncertainty": "",
            "followups": ["Where is the token verified?"],
        }
        return {"model": "sarvam-105b", "finish_reason": "stop",
                "raw_text": json.dumps(payload), "structured": payload,
                "usage": {"total_tokens": 123}, "truncated": False}


def test_ask_happy_path_returns_verified_citations(auth_client, configured_key, monkeypatch):
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    pid = _upload_batch(auth_client).get_json()["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask",
                                json={"question": "How does login work?",
                                      "language": "te-IN"})
    assert response.status_code == 200
    body = response.get_json()

    assert body["sarvam_called"] is True
    assert body["structured"] is True
    assert body["answer"].startswith("Login checks")
    assert body["language"] == "te-IN"
    assert body["model"] == "sarvam-105b"
    assert body["usage"]["total_tokens"] == 123

    assert len(body["citations"]) == 1
    cit = body["citations"][0]
    assert cit["verified"] is True
    assert cit["path"] == "src/login.py"
    # The quote is filled in from the file, not supplied by the model.
    assert cit["quote"].strip()
    assert cit["quote"].strip() in SAMPLE_FILES["src/login.py"]

    assert body["evidence"]
    assert all("citation_id" in s for s in body["evidence"])
    assert StubSarvam.last_kwargs["language"] == "te-IN"


def test_hallucinated_citation_is_flagged_not_verified(auth_client, configured_key, monkeypatch):
    class Liar(StubSarvam):
        def answer(self, question, language, retrieval, history=None):
            payload = {
                "answer": "It uses a secret database.",
                "steps": [], "key_files": [],
                "citations": [
                    {"path": "totally/made_up.py", "start_line": 1, "end_line": 9,
                     "quote": "invented()", "note": "made up"},
                ],
                "uncertainty": "", "followups": [],
            }
            return {"model": "sarvam-105b", "finish_reason": "stop",
                    "raw_text": json.dumps(payload), "structured": payload,
                    "usage": None, "truncated": False}

    monkeypatch.setattr("app.routes.SarvamClient", Liar)

    pid = _upload_batch(auth_client).get_json()["project_id"]
    body = auth_client.post(f"/api/projects/{pid}/ask",
                            json={"question": "How does login work?"}).get_json()

    assert body["citations"] == []
    assert len(body["rejected_citations"]) == 1
    assert body["rejected_citations"][0]["verified"] is False
    assert "not a file" in body["rejected_citations"][0]["rejection_reason"]


def test_prose_only_reply_reports_no_verified_citations(auth_client, configured_key, monkeypatch):
    class Prose(StubSarvam):
        def answer(self, question, language, retrieval, history=None):
            return {"model": "sarvam-105b", "finish_reason": "stop",
                    "raw_text": "Login probably works somehow.",
                    "structured": None, "usage": None, "truncated": False}

    monkeypatch.setattr("app.routes.SarvamClient", Prose)

    pid = _upload_batch(auth_client).get_json()["project_id"]
    body = auth_client.post(f"/api/projects/{pid}/ask",
                            json={"question": "How does login work?"}).get_json()

    assert body["structured"] is False
    assert body["citations"] == []
    assert "machine-checkable" in body["uncertainty"]


def test_upstream_failure_is_surfaced_not_hidden(auth_client, configured_key, monkeypatch):
    from app.errors import SarvamRateLimited

    class Failing(StubSarvam):
        def answer(self, question, language, retrieval, history=None):
            raise SarvamRateLimited("slow down")

    monkeypatch.setattr("app.routes.SarvamClient", Failing)

    pid = _upload_batch(auth_client).get_json()["project_id"]
    response = auth_client.post(f"/api/projects/{pid}/ask",
                                json={"question": "How does login work?"})
    assert response.status_code == 429
    assert response.get_json()["code"] == "sarvam_rate_limited"


def test_truncated_reply_is_reported(auth_client, configured_key, monkeypatch):
    class Truncating(StubSarvam):
        def answer(self, question, language, retrieval, history=None):
            return {"model": "sarvam-105b", "finish_reason": "length",
                    "raw_text": '{"answer": "partial"}',
                    "structured": {"answer": "partial"}, "usage": None,
                    "truncated": True}

    monkeypatch.setattr("app.routes.SarvamClient", Truncating)
    pid = _upload_batch(auth_client).get_json()["project_id"]
    body = auth_client.post(f"/api/projects/{pid}/ask",
                            json={"question": "How does login work?"}).get_json()
    assert body["truncated"] is True
    assert "token budget" in body["uncertainty"]


def test_stale_citation_from_another_project_is_rejected(auth_client, configured_key, monkeypatch):
    """A citation valid in project A must not verify against project B."""
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    pid_a = _upload_batch(auth_client, {"auth/login.py": "def login():\n    pass\n"}).get_json()["project_id"]
    body_a = auth_client.post(f"/api/projects/{pid_a}/ask",
                              json={"question": "login"}).get_json()
    good_path = body_a["citations"][0]["path"]

    pid_b = _upload_batch(auth_client, {"other/thing.py": "def thing():\n    pass\n"}).get_json()["project_id"]

    class CrossProject(StubSarvam):
        def answer(self, question, language, retrieval, history=None):
            payload = {
                "answer": "x", "steps": [], "key_files": [],
                "citations": [{"path": good_path, "start_line": 1, "end_line": 2,
                               "quote": "def login():", "note": ""}],
                "uncertainty": "", "followups": [],
            }
            return {"model": "sarvam-105b", "finish_reason": "stop",
                    "raw_text": json.dumps(payload), "structured": payload,
                    "usage": None, "truncated": False}

    monkeypatch.setattr("app.routes.SarvamClient", CrossProject)
    body_b = auth_client.post(f"/api/projects/{pid_b}/ask",
                              json={"question": "thing"}).get_json()
    assert body_b["citations"] == []
    assert body_b["rejected_citations"]


def test_ask_unknown_project_is_404(auth_client):
    response = auth_client.post("/api/projects/123e4567-e89b-12d3-a456-426614174000/ask",
                                json={"question": "hi"})
    assert response.status_code == 404


def test_unknown_endpoint_returns_json_404(client):
    response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"
