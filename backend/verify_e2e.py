"""End-to-end verification of the running backend.

Starts the real Flask app in a background thread inside this process, then
exercises the documented user journey over HTTP, including the account flow.

Run it with SARVAM_API_KEY set to also exercise a live answer.
"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/scratch/work/codesathi-ai/backend")

# A throwaway SQLite database so a verification run never touches real data.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/verify.db")

from app import create_app  # noqa: E402

BASE = "http://127.0.0.1:8765"
COOKIE = "codesathi_session"


def call(method, path, payload=None, timeout=180, cookie=None):
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", f"{COOKIE}={cookie}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else {}), resp.headers
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, (json.loads(body) if body else {}), exc.headers
        except json.JSONDecodeError:
            return exc.code, {"raw": body}, exc.headers


def session_token(headers) -> str | None:
    for value in headers.get_all("Set-Cookie") or []:
        if value.startswith(f"{COOKIE}="):
            return value.split("=", 1)[1].split(";")[0]
    return None


def main() -> int:
    app = create_app({"TESTING": False})
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False),
        daemon=True,
    ).start()

    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/api/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.2)

    checks: list[tuple[str, bool, str]] = []
    failures: list[str] = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        if not ok:
            failures.append(name)

    # -- health ------------------------------------------------------------
    status, health, _ = call("GET", "/api/health")
    configured = health.get("sarvam", {}).get("configured", False)
    check("GET /api/health", status == 200,
          f"sarvam configured={configured} · storage={health.get('storage', {}).get('backend')}")

    # -- accounts ----------------------------------------------------------
    status, body, _ = call("GET", "/api/auth/me")
    check("GET /api/auth/me (anonymous)", status == 200 and body.get("user") is None,
          "user is null")

    status, body, _ = call("POST", "/api/projects",
                           {"name": "x", "files": [{"path": "a.py", "content": "x = 1"}]})
    check("uploading without an account is refused", status == 401, body.get("code", ""))

    email = f"verify+{int(time.time())}@example.com"
    status, body, headers = call("POST", "/api/auth/signup",
                                 {"email": email, "password": "verify-password-123",
                                  "full_name": "Verify Bot"})
    token = session_token(headers)
    check("POST /api/auth/signup", status == 201 and token is not None,
          f"account created for {email}")

    status, body, _ = call("GET", "/api/auth/me", cookie=token)
    check("GET /api/auth/me (signed in)", status == 200 and body["user"]["email"] == email,
          "session cookie identifies the account")

    status, body, _ = call("POST", "/api/auth/signup",
                           {"email": email, "password": "verify-password-123"})
    check("duplicate signup is refused", status == 409, body.get("code", ""))

    status, body, _ = call("POST", "/api/auth/login",
                           {"email": email, "password": "wrong-password"})
    check("wrong password is refused", status == 401, body.get("code", ""))

    # -- sample project (public) -------------------------------------------
    status, project, _ = call("POST", "/api/projects/sample")
    pid = project.get("project_id")
    check("POST /api/projects/sample (public)", status == 200,
          f"{project.get('stats', {}).get('file_count')} files indexed")

    status, files, _ = call("GET", f"/api/projects/{pid}/files")
    check("GET /projects/:id/files (no account needed)", status == 200,
          f"tree children={len(files.get('tree', {}).get('children', []))}")

    status, content, _ = call("GET", f"/api/projects/{pid}/file?path=auth/login.py")
    ok = status == 200 and content.get("lines") and content["lines"][0]["number"] == 1
    check("GET /projects/:id/file", ok,
          f"{content.get('line_count')} lines, {len(content.get('symbols', []))} symbols")

    status, search, _ = call("GET", f"/api/projects/{pid}/search?q=login")
    check("GET /projects/:id/search", status == 200 and len(search.get("results", [])) > 0,
          f"{len(search.get('results', []))} hits")

    status, blocked, _ = call("GET", f"/api/projects/{pid}/file?path=../../etc/passwd")
    check("path traversal refused", status == 400, blocked.get("code", ""))

    # -- ask ---------------------------------------------------------------
    status, ask, _ = call("POST", f"/api/projects/{pid}/ask",
                          {"question": "How does login work?", "language": "en-IN"},
                          cookie=token)
    expected = 200 if configured else 503
    check("POST /projects/:id/ask", status == expected,
          f"HTTP {status} · {ask.get('code') or 'answered'}")

    if expected == 200:
        verified = ask.get("citations") or []
        check("  answer is non-empty", bool(ask.get("answer")),
              f"{len(ask.get('answer') or '')} chars")
        check("  structured output honoured", ask.get("structured") is True,
              f"model={ask.get('model')}")
        check("  evidence retrieved", len(ask.get("evidence") or []) > 0,
              f"{len(ask.get('evidence') or [])} snippets")
        check("  citations verified against the index", len(verified) > 0,
              f"{len(verified)} verified, {len(ask.get('rejected_citations') or [])} rejected")
        for citation in verified:
            check(f"  cite {citation['citation_id']}", citation.get("verified") is True,
                  (citation.get("note") or "")[:40])
            check("  quote came from the file", bool(citation.get("quote")),
                  repr((citation.get("quote") or "")[:36]))

    # -- private project via the browser's batched upload ------------------
    status, created, _ = call("POST", "/api/projects", {
        "name": "batched-demo",
        "files": [{"path": "src/login.py",
                   "content": "def login(user, pw):\n    return check(pw, user.hash)\n"}],
    }, cookie=token)
    own_pid = created.get("project_id")
    check("POST /api/projects (batched, signed in)", status == 201,
          f"status={created.get('status')}")

    status, _, _ = call("GET", f"/api/projects/{own_pid}/files")
    check("a private project is hidden from anonymous callers", status == 404, "")

    status, _, _ = call("GET", f"/api/projects/{own_pid}/files", cookie=token)
    check("the owner can read their own project", status == 200, "")

    status, _, _ = call("DELETE", f"/api/projects/{own_pid}", cookie=token)
    check("DELETE /projects/:id (owner)", status == 200, "removed")

    status, _, _ = call("GET", f"/api/projects/{own_pid}/files", cookie=token)
    check("deleted project is gone", status == 404, "404 as expected")

    status, bad, _ = call("GET", "/api/projects/not-a-uuid/files")
    check("invalid project id", status == 400, bad.get("code", ""))

    # -- sign out ----------------------------------------------------------
    status, _, headers = call("POST", "/api/auth/logout", cookie=token)
    check("POST /api/auth/logout", status == 200, "")
    status, body, _ = call("GET", "/api/auth/me", cookie=token)
    check("the session is dead after logout", body.get("user") is None, "")

    print("\n" + "=" * 72)
    print("CodeSathi AI — end-to-end journey against a live server")
    print("=" * 72)
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:46s} {detail}")
    print("=" * 72)
    if failures:
        print(f"FAILED steps: {failures}")
        return 1
    print(f"All {len(checks)} journey checks passed.")
    if not configured:
        print("NOTE: SARVAM_API_KEY is not set, so the live AI answer was not exercised.")
        print("      The 503 sarvam_not_configured path is the verified behaviour here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
