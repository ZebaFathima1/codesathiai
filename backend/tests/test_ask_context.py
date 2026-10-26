"""Ask fallbacks and the cookie policy behind a split deployment.

These cover the failure users actually hit: a question like "explain this"
contains only stopwords, so it used to reach the model with zero evidence and
come back as "no direct answer was produced". The fix resolves such a question
against the open file, then the previous turn, then the project as a whole —
and when none of those apply, it returns clickable suggestions instead of a
dead end.
"""
import json

import pytest

from app import config
from tests.conftest import TEST_USER, file_entries

PROJECT_FILES = {
    "auth/login.py": (
        "from .db import find_user\n\n\n"
        "def login(email, password):\n"
        "    user = find_user(email)\n"
        "    if user is None:\n"
        "        return None\n"
        "    return issue_token(user)\n"
    ),
    "config/settings.py": (
        "import os\n\n\n"
        "class Settings:\n"
        "    database_url = os.environ.get('DATABASE_URL')\n"
    ),
    "README.md": "# ShopEasy API\n\nA small Flask service with login and a database.\n",
}


class StubSarvam:
    """Records what it was handed and returns a well-formed answer."""

    last = None

    def __init__(self, *args, **kwargs):
        pass

    def answer(self, question, language, retrieval, history=None):
        StubSarvam.last = {
            "question": question,
            "note": retrieval.note,
            "paths": [s.path for s in retrieval.snippets],
        }
        snippet = retrieval.snippets[0]
        payload = {
            "answer": "This explains the code that was supplied.",
            "steps": [],
            "key_files": [{"path": snippet.path, "symbol": "", "role": "relevant"}],
            "citations": [{
                "path": snippet.path,
                "start_line": snippet.start_line,
                "end_line": snippet.end_line,
                "note": "the code in question",
            }],
            "uncertainty": "",
            "followups": [],
        }
        return {
            "model": "sarvam-105b",
            "finish_reason": "stop",
            "raw_text": json.dumps(payload),
            "structured": payload,
            "usage": None,
            "truncated": False,
        }


@pytest.fixture()
def project(auth_client):
    """A small uploaded project with a login flow, config and a README."""
    response = auth_client.post("/api/projects", json={
        "name": "shop", "files": file_entries(PROJECT_FILES),
    })
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _ask(client, project, question, **extra):
    payload = {"question": question, "language": "en-IN"}
    payload.update(extra)
    return client.post(f"/api/projects/{project['project_id']}/ask", json=payload)


# ---------------------------------------------------------------------------
# Focus: the file the user is looking at
# ---------------------------------------------------------------------------
def test_explain_this_uses_the_selected_range(auth_client, configured_key,
                                              monkeypatch, project):
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    body = _ask(auth_client, project, "explain this", focus={
        "path": "auth/login.py", "start_line": 4, "end_line": 8,
    }).get_json()

    assert body["sarvam_called"] is True
    assert body["context"]["mode"] == "focus"
    assert body["context"]["path"] == "auth/login.py"
    assert body["context"]["start_line"] == 4
    assert StubSarvam.last["paths"][0] == "auth/login.py"
    assert "open in the code viewer" in StubSarvam.last["note"]
    assert body["citations"], "the focused snippet should verify as a citation"
    assert body["suggestions"]


def test_explain_this_uses_the_open_file_when_nothing_is_selected(
        auth_client, configured_key, monkeypatch, project):
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    body = _ask(auth_client, project, "what is this?",
                focus={"path": "config/settings.py"}).get_json()

    assert body["sarvam_called"] is True
    assert body["context"]["mode"] == "focus"
    assert StubSarvam.last["paths"][0] == "config/settings.py"


def test_a_named_term_that_matches_nothing_is_not_answered_from_the_open_file(
        auth_client, configured_key, monkeypatch, project):
    """Focus is for anaphora ("explain this"), not for any unmatched word."""
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    body = _ask(auth_client, project, "zzzqqqxyw",
                focus={"path": "auth/login.py"}).get_json()

    assert body["sarvam_called"] is False
    assert body["context"]["mode"] == "none"
    assert body["suggestions"]


def test_a_stale_focus_path_is_ignored_rather_than_rejected(
        auth_client, configured_key, monkeypatch, project):
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    response = _ask(auth_client, project, "explain this",
                    focus={"path": "gone/ファイル.py"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["context"]["mode"] == "none"
    assert body["sarvam_called"] is False


# ---------------------------------------------------------------------------
# Previous turn: a follow-up inherits the earlier question
# ---------------------------------------------------------------------------
def test_follow_up_inherits_the_previous_question(auth_client, configured_key,
                                                  monkeypatch, project):
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    body = _ask(
        auth_client, project, "explain that again",
        history=[
            {"role": "user", "content": "How does login work?"},
            {"role": "assistant", "content": "Login looks up the user."},
        ],
    ).get_json()

    assert body["sarvam_called"] is True
    assert body["context"]["mode"] == "previous"
    assert body["context"]["question"] == "How does login work?"
    assert "follow-up" in StubSarvam.last["note"]
    assert StubSarvam.last["question"] == "explain that again"


# ---------------------------------------------------------------------------
# Overview: a project-level question that names no symbol
# ---------------------------------------------------------------------------
def test_project_question_falls_back_to_an_overview(auth_client, configured_key,
                                                    monkeypatch, project):
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    body = _ask(auth_client, project, "what does this project do?").get_json()

    assert body["sarvam_called"] is True
    assert body["context"]["mode"] == "overview"
    assert "README.md" in StubSarvam.last["paths"]
    assert "overview" in StubSarvam.last["note"].lower()


def test_specific_questions_still_win_over_the_overview(auth_client,
                                                        configured_key,
                                                        monkeypatch, project):
    monkeypatch.setattr("app.routes.SarvamClient", StubSarvam)

    body = _ask(auth_client, project, "How does login work?").get_json()

    assert body["context"]["mode"] == "question"
    assert body["evidence"]


# ---------------------------------------------------------------------------
# Dead end: honest, but with somewhere to go
# ---------------------------------------------------------------------------
def test_unmatched_question_returns_suggestions_instead_of_nothing(
        auth_client, project):
    body = _ask(auth_client, project, "zzzqqqxyw").get_json()

    assert body["sarvam_called"] is False
    assert body["answer"] is None
    assert body["context"]["mode"] == "none"
    assert body["suggestions"], "a dead end must offer clickable next steps"
    assert any("login" in item["question"].lower() for item in body["suggestions"])


# ---------------------------------------------------------------------------
# Cookie policy for a split deployment
# ---------------------------------------------------------------------------
def test_origin_classification():
    assert config._is_external_origin("https://codesathiai.vercel.app")
    assert config._is_external_origin("https://api.example.com:8443")
    assert not config._is_external_origin("http://localhost:5173")
    assert not config._is_external_origin("http://127.0.0.1:5173")


def test_session_cookie_uses_the_configured_policy(client, account):
    response = client.post("/api/auth/login", json={
        "email": TEST_USER["email"], "password": TEST_USER["password"],
    })
    assert response.status_code == 200

    cookie = response.headers.get("Set-Cookie", "")
    expected = config.COOKIE_SAMESITE.capitalize()
    assert f"SameSite={expected}" in cookie
    assert "HttpOnly" in cookie
    if config.COOKIE_SAMESITE == "none":
        assert "Secure" in cookie
