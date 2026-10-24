"""Shared pytest fixtures for the CodeSathi AI backend test-suite.

Each test gets a fresh in-memory SQLite database. That matters: the storage
layer is the same code production runs against Postgres, so these tests
exercise the real persistence path rather than a stand-in.
"""
from __future__ import annotations

import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as app_config  # noqa: E402
from app import create_app, db, repository  # noqa: E402
from app import routes as routes_module  # noqa: E402

TEST_USER = {"email": "zeba@example.com", "password": "correct-horse-battery",
             "full_name": "Zeba Fathima"}


# ---------------------------------------------------------------------------
# Archive helpers
# ---------------------------------------------------------------------------
def make_zip_bytes(files: dict[str, str]) -> bytes:
    """Build an in-memory ZIP from a mapping of path -> text."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def zip_upload(files: dict[str, str], name: str = "demo.zip") -> tuple:
    """A (BytesIO, filename) pair ready for the Flask test client."""
    return io.BytesIO(make_zip_bytes(files)), name


def make_zip_with_raw_entries(entries: list[tuple[str, bytes]]) -> bytes:
    """Build a ZIP where entries can have hostile names or raw bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def file_entries(files: dict[str, str]) -> list[dict]:
    """The JSON batch shape the browser sends after unpacking a ZIP."""
    return [{"path": path, "content": content} for path, content in files.items()]


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def fresh_database():
    """A brand-new in-memory database for every test."""
    db.reset_for_tests("sqlite://")
    repository._CACHE.clear()
    yield
    db.dispose()
    repository._CACHE.clear()


@pytest.fixture()
def app(monkeypatch):
    """A test app with no Sarvam key and no Google client configured."""
    monkeypatch.setattr(app_config, "SARVAM_API_KEY", "", raising=False)
    monkeypatch.setattr(app_config, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(app_config, "GOOGLE_CLIENT_SECRET", "", raising=False)
    # Rate limiting is off by default so a suite can make many requests;
    # test_rate_limit.py turns it back on.
    monkeypatch.setattr(routes_module._limiter, "per_minute", 0)
    monkeypatch.setattr(routes_module._auth_limiter, "per_minute", 0)
    application = create_app({"TESTING": True})
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def configured_key(monkeypatch):
    """Pretend a valid Sarvam API key is present."""
    monkeypatch.setattr(app_config, "SARVAM_API_KEY", "sk_test_key", raising=False)
    return "sk_test_key"


@pytest.fixture()
def google_configured(monkeypatch):
    """Pretend Google sign-in is configured."""
    monkeypatch.setattr(app_config, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(app_config, "GOOGLE_CLIENT_SECRET", "test-secret", raising=False)
    return "test-client-id"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@pytest.fixture()
def account(client):
    """Sign up a user and leave the client signed in. Returns the user dict."""
    response = client.post("/api/auth/signup", json=TEST_USER)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


@pytest.fixture()
def auth_client(account, client):
    """A client that is signed in as :func:`account`."""
    return client


@pytest.fixture()
def second_client(app):
    """A separate signed-in client, for ownership tests."""
    other = app.test_client()
    response = other.post("/api/auth/signup", json={
        "email": "someone.else@example.com",
        "password": "another-long-password",
        "full_name": "Someone Else",
    })
    assert response.status_code == 201
    return other


@pytest.fixture()
def sample_project(client):
    """The public bundled sample project."""
    response = client.post("/api/projects/sample")
    assert response.status_code == 200, response.get_json()
    return response.get_json()
