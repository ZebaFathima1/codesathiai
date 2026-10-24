"""Tests for the request rate limiters."""
import pytest

from app import routes as routes_module
from tests.conftest import TEST_USER, file_entries


@pytest.fixture()
def limited(monkeypatch):
    """Enable a very small general limit for this test only."""
    monkeypatch.setattr(routes_module._limiter, "per_minute", 3)
    monkeypatch.setattr(routes_module._limiter, "_hits", {})


@pytest.fixture()
def auth_limited(monkeypatch):
    """Enable a very small limit on sign-in attempts."""
    monkeypatch.setattr(routes_module._auth_limiter, "per_minute", 2)
    monkeypatch.setattr(routes_module._auth_limiter, "_hits", {})


def _post_upload(client):
    """Each call needs a fresh stream: the test client closes it."""
    return client.post(
        "/api/projects",
        json={"name": "x", "files": file_entries({"a.py": "print(1)\n"})},
    )


def test_rate_limit_blocks_after_threshold(auth_client, limited):
    statuses = [_post_upload(auth_client).status_code for _ in range(4)]
    assert statuses[:3] == [201, 201, 201]
    assert statuses[3] == 429


def test_rate_limit_response_shape(auth_client, limited):
    for _ in range(3):
        _post_upload(auth_client)
    body = _post_upload(auth_client).get_json()
    assert body["code"] == "rate_limited"
    assert "Too many requests" in body["error"]


def test_login_attempts_are_rate_limited(client, account, auth_limited):
    """Brute-forcing credentials must be throttled far below request speed."""
    statuses = [
        client.post("/api/auth/login",
                    json={"email": TEST_USER["email"], "password": "guess"}).status_code
        for _ in range(4)
    ]
    assert statuses[:2] == [401, 401]
    assert statuses[2:] == [429, 429]


def test_signup_is_rate_limited(client, auth_limited):
    statuses = [
        client.post("/api/auth/signup",
                    json={"email": f"user{i}@example.com",
                          "password": "long-enough-password"}).status_code
        for i in range(4)
    ]
    assert statuses[:2] == [201, 201]
    assert statuses[2:] == [429, 429]


def test_the_general_limit_does_not_block_reads_by_default(client, sample_project):
    """The default budget is generous enough for ordinary browsing."""
    pid = sample_project["project_id"]
    assert all(client.get(f"/api/projects/{pid}/files").status_code == 200
               for _ in range(5))
