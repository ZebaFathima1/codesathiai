"""Tests for authentication: passwords, sessions, and Google sign-in."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import auth, config
from app.db import session_scope
from app.models import AuthSession, User
from tests.conftest import TEST_USER, file_entries


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def test_password_hash_is_salted_and_verifiable():
    first = auth.hash_password("correct-horse-battery")
    second = auth.hash_password("correct-horse-battery")
    assert first != second, "the same password must not hash identically"
    assert first.startswith("pbkdf2_sha256$600000$")
    assert auth.verify_password("correct-horse-battery", first)
    assert auth.verify_password("correct-horse-battery", second)
    assert not auth.verify_password("wrong-password", first)


def test_password_hash_never_contains_the_password():
    stored = auth.hash_password("my-secret-password")
    assert "my-secret-password" not in stored


@pytest.mark.parametrize("bad", ["", None, "not-a-hash", "pbkdf2_sha256$1$bad"])
def test_verify_password_rejects_unusable_input(bad):
    assert auth.verify_password("anything", bad) is False


def test_verify_password_rejects_empty_password():
    assert auth.verify_password("", auth.hash_password("real-password")) is False


def test_email_normalisation():
    assert auth.normalise_email("  Zeba@Example.COM ") == "zeba@example.com"
    for bad in ["", "no-at-sign", "trailing@dot.", "@nodomain.com"]:
        with pytest.raises(Exception):
            auth.normalise_email(bad)


# ---------------------------------------------------------------------------
# Sign up
# ---------------------------------------------------------------------------
def test_signup_creates_an_account_and_signs_in(client):
    response = client.post("/api/auth/signup", json=TEST_USER)
    assert response.status_code == 201
    body = response.get_json()
    assert body["email"] == TEST_USER["email"]
    assert body["full_name"] == "Zeba Fathima"
    assert body["provider"] == "password"
    assert "password" not in body and "password_hash" not in body
    assert config.SESSION_COOKIE_NAME in response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in response.headers.get("Set-Cookie", "")

    # The session cookie now identifies us.
    assert client.get("/api/auth/me").get_json()["user"]["email"] == TEST_USER["email"]


def test_signup_stores_a_hash_not_the_password(client):
    client.post("/api/auth/signup", json=TEST_USER)
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == TEST_USER["email"])).scalars().first()
        assert user.password_hash and user.password_hash != TEST_USER["password"]
        assert auth.verify_password(TEST_USER["password"], user.password_hash)


def test_signup_rejects_a_duplicate_email(client):
    client.post("/api/auth/signup", json=TEST_USER)
    response = client.post("/api/auth/signup", json=TEST_USER)
    assert response.status_code == 409
    assert response.get_json()["code"] == "email_taken"


def test_signup_rejects_a_weak_password(client):
    response = client.post("/api/auth/signup",
                           json={"email": "new@example.com", "password": "short"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "weak_password"


def test_signup_rejects_an_invalid_email(client):
    response = client.post("/api/auth/signup",
                           json={"email": "nope", "password": "long-enough-password"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_email"


def test_signup_defaults_the_name_from_the_email(client):
    response = client.post("/api/auth/signup",
                           json={"email": "noname@example.com",
                                 "password": "long-enough-password"})
    assert response.get_json()["full_name"] == "noname"


# ---------------------------------------------------------------------------
# Sign in
# ---------------------------------------------------------------------------
def test_login_succeeds_with_correct_credentials(client, account):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login",
                           json={"email": TEST_USER["email"],
                                 "password": TEST_USER["password"]})
    assert response.status_code == 200
    assert client.get("/api/auth/me").get_json()["user"] is not None


def test_login_is_case_insensitive_on_email(client, account):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login",
                           json={"email": "ZEBA@EXAMPLE.COM",
                                 "password": TEST_USER["password"]})
    assert response.status_code == 200


def test_login_rejects_a_wrong_password(client, account):
    response = client.post("/api/auth/login",
                           json={"email": TEST_USER["email"], "password": "wrong-password"})
    assert response.status_code == 401
    assert response.get_json()["code"] == "invalid_credentials"


def test_login_does_not_reveal_whether_an_account_exists(client, account):
    missing = client.post("/api/auth/login",
                          json={"email": "ghost@example.com", "password": "whatever123"})
    wrong = client.post("/api/auth/login",
                        json={"email": TEST_USER["email"], "password": "whatever123"})
    assert missing.status_code == wrong.status_code == 401
    assert missing.get_json()["error"] == wrong.get_json()["error"]


def test_login_requires_both_fields(client):
    assert client.post("/api/auth/login", json={"email": "a@b.com"}).status_code == 400


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def test_me_returns_null_when_signed_out(client):
    body = client.get("/api/auth/me").get_json()
    assert body["user"] is None
    assert "google_available" in body


def test_logout_invalidates_the_session(client, account):
    assert client.get("/api/auth/me").get_json()["user"] is not None
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").get_json()["user"] is None
    # The session row is gone, not merely unset in the browser.
    with session_scope() as db:
        assert db.execute(select(AuthSession)).scalars().all() == []


def test_only_the_token_hash_is_stored(client, account):
    with session_scope() as db:
        row = db.execute(select(AuthSession)).scalars().first()
        assert row is not None
        assert re.fullmatch(r"[0-9a-f]{64}", row.id), "session id must be a sha256 hex digest"


def test_an_expired_session_is_rejected(client, account):
    with session_scope() as db:
        row = db.execute(select(AuthSession)).scalars().first()
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    assert client.get("/api/auth/me").get_json()["user"] is None


def test_a_forged_session_cookie_is_rejected(client, account):
    client.set_cookie(config.SESSION_COOKIE_NAME, "not-a-real-token")
    assert client.get("/api/auth/me").get_json()["user"] is None


def test_deactivated_accounts_lose_access(client, account):
    with session_scope() as db:
        user = db.execute(select(User).where(User.email == TEST_USER["email"])).scalars().first()
        user.is_active = False
    assert client.get("/api/auth/me").get_json()["user"] is None


def test_purge_expired_sessions_removes_only_old_rows(client, account):
    with session_scope() as db:
        row = db.execute(select(AuthSession)).scalars().first()
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        assert auth.purge_expired_sessions(db) == 1


# ---------------------------------------------------------------------------
# Google sign-in
# ---------------------------------------------------------------------------
def test_google_start_is_unavailable_when_not_configured(client):
    response = client.get("/api/auth/google/start")
    assert response.status_code == 503
    assert response.get_json()["code"] == "google_not_configured"


def test_google_start_redirects_and_sets_a_state_cookie(client, google_configured):
    response = client.get("/api/auth/google/start")
    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.startswith(auth.GOOGLE_AUTH_ENDPOINT)
    assert "client_id=test-client-id" in location
    assert "state=" in location
    assert config.OAUTH_STATE_COOKIE in response.headers.get("Set-Cookie", "")


def test_google_callback_rejects_a_mismatched_state(client, google_configured):
    client.get("/api/auth/google/start")
    response = client.get("/api/auth/google/callback?code=abc&state=wrong")
    assert response.status_code == 400
    assert response.get_json()["code"] == "google_state_mismatch"


def test_google_callback_rejects_a_missing_state_cookie(client, google_configured):
    response = client.get("/api/auth/google/callback?code=abc&state=whatever")
    assert response.status_code == 400


def test_google_callback_signs_in_and_creates_the_account(client, google_configured, monkeypatch):
    monkeypatch.setattr(auth, "exchange_google_code", lambda code, uri: "access-token")
    monkeypatch.setattr(auth, "fetch_google_profile", lambda token: {
        "sub": "google-12345",
        "email": "newperson@example.com",
        "email_verified": True,
        "name": "New Person",
        "picture": "https://example.com/a.png",
    })

    start = client.get("/api/auth/google/start")
    state = re.search(r"state=([^&]+)", start.headers["Location"]).group(1)

    response = client.get(f"/api/auth/google/callback?code=abc&state={state}")
    assert response.status_code == 302, response.get_json()
    assert "/#/app" in response.headers["Location"]

    me = client.get("/api/auth/me").get_json()["user"]
    assert me["email"] == "newperson@example.com"
    assert me["provider"] == "google"
    assert me["avatar_url"] == "https://example.com/a.png"
    assert me["full_name"] == "New Person"


def test_google_sign_in_links_an_existing_password_account(client, account, google_configured, monkeypatch):
    """Signing up with a password then using Google must not create a duplicate."""
    monkeypatch.setattr(auth, "exchange_google_code", lambda code, uri: "access-token")
    monkeypatch.setattr(auth, "fetch_google_profile", lambda token: {
        "sub": "google-999",
        "email": TEST_USER["email"],
        "email_verified": True,
        "name": "Zeba Fathima",
    })

    start = client.get("/api/auth/google/start")
    state = re.search(r"state=([^&]+)", start.headers["Location"]).group(1)
    client.get(f"/api/auth/google/callback?code=abc&state={state}")

    with session_scope() as db:
        users = db.execute(select(User)).scalars().all()
        assert len(users) == 1, "the accounts should have been linked, not duplicated"
        assert users[0].google_sub == "google-999"
        # The original password still works.
        assert auth.verify_password(TEST_USER["password"], users[0].password_hash)


def test_google_callback_reports_an_unverified_email(client, google_configured, monkeypatch):
    monkeypatch.setattr(auth, "exchange_google_code", lambda code, uri: "access-token")
    monkeypatch.setattr(auth, "fetch_google_profile", lambda token: {
        "sub": "google-1", "email": "unverified@example.com", "email_verified": False,
    })
    start = client.get("/api/auth/google/start")
    state = re.search(r"state=([^&]+)", start.headers["Location"]).group(1)
    response = client.get(f"/api/auth/google/callback?code=abc&state={state}")
    assert response.status_code == 403
    assert response.get_json()["code"] == "google_email_unverified"


def test_google_callback_surfaces_an_upstream_failure(client, google_configured, monkeypatch):
    def boom(code, uri):
        from app.errors import AuthError
        raise AuthError("Google sign-in failed. Please try again.",
                        code="google_exchange_failed", status_code=502)

    monkeypatch.setattr(auth, "exchange_google_code", boom)
    start = client.get("/api/auth/google/start")
    state = re.search(r"state=([^&]+)", start.headers["Location"]).group(1)
    response = client.get(f"/api/auth/google/callback?code=abc&state={state}")
    assert response.status_code == 502
    assert response.get_json()["code"] == "google_exchange_failed"


def test_google_callback_handles_a_user_cancelling(client, google_configured):
    response = client.get("/api/auth/google/callback?error=access_denied")
    assert response.status_code == 302
    assert "error=access_denied" in response.headers["Location"]


def test_health_reports_whether_google_is_available(client, google_configured):
    assert client.get("/api/health").get_json()["auth"]["google"] is True


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------
def test_uploading_requires_an_account(client):
    response = client.post("/api/projects", json={"name": "x",
                                                  "files": file_entries({"a.py": "x = 1"})})
    assert response.status_code == 401
    assert response.get_json()["code"] == "not_authenticated"


def test_asking_requires_an_account(client, sample_project):
    response = client.post(f"/api/projects/{sample_project['project_id']}/ask",
                           json={"question": "How does login work?"})
    assert response.status_code == 401


def test_listing_projects_requires_an_account(client):
    assert client.get("/api/projects").status_code == 401


def test_browsing_the_sample_project_needs_no_account(client, sample_project):
    """Browsing stays open; only upload and ask are gated."""
    pid = sample_project["project_id"]
    assert client.get(f"/api/projects/{pid}/files").status_code == 200
    assert client.get(f"/api/projects/{pid}/file?path=auth/login.py").status_code == 200
    assert client.get(f"/api/projects/{pid}/search?q=login").status_code == 200


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------
def test_a_project_is_private_to_its_owner(auth_client, second_client):
    created = auth_client.post("/api/projects", json={
        "name": "mine", "files": file_entries({"secret.py": "api_key = 'x'\n"}),
    }).get_json()
    pid = created["project_id"]

    # The owner can read it.
    assert auth_client.get(f"/api/projects/{pid}/files").status_code == 200
    # Another signed-in account cannot even tell that it exists.
    assert second_client.get(f"/api/projects/{pid}/files").status_code == 404
    assert second_client.get(f"/api/projects/{pid}/file?path=secret.py").status_code == 404


def test_only_the_owner_can_ask_about_a_private_project(auth_client, second_client, configured_key):
    created = auth_client.post("/api/projects", json={
        "name": "mine", "files": file_entries({"login.py": "def login():\n    pass\n"}),
    }).get_json()
    response = second_client.post(f"/api/projects/{created['project_id']}/ask",
                                  json={"question": "How does login work?"})
    assert response.status_code == 404


def test_only_the_owner_can_delete(auth_client, second_client):
    created = auth_client.post("/api/projects", json={
        "name": "mine", "files": file_entries({"a.py": "x = 1\n"}),
    }).get_json()
    pid = created["project_id"]
    assert second_client.delete(f"/api/projects/{pid}").status_code == 404
    assert auth_client.delete(f"/api/projects/{pid}").status_code == 200


def test_the_sample_project_cannot_be_deleted(auth_client):
    sample = auth_client.post("/api/projects/sample").get_json()
    response = auth_client.delete(f"/api/projects/{sample['project_id']}")
    assert response.status_code == 403
    assert response.get_json()["code"] == "sample_is_protected"


def test_a_signed_in_user_can_ask_about_the_sample_project(auth_client, sample_project, configured_key):
    """The sample is shared, so any signed-in account may ask about it."""
    response = auth_client.post(f"/api/projects/{sample_project['project_id']}/ask",
                                json={"question": "zzzznomatch"})
    assert response.status_code == 200
    assert response.get_json()["sarvam_called"] is False


def test_list_projects_returns_only_my_projects(auth_client, second_client):
    auth_client.post("/api/projects", json={"name": "first", "files": file_entries({"a.py": "x=1"})})
    second_client.post("/api/projects", json={"name": "theirs", "files": file_entries({"b.py": "y=1"})})
    names = [p["name"] for p in auth_client.get("/api/projects").get_json()["projects"]]
    assert names == ["first"]
