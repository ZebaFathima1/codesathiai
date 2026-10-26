"""HTTP API for CodeSathi AI.

Every route opens its own database session via ``session_scope()``, which
commits on success and rolls back on failure. Nothing is kept in process
memory, so any serverless instance can serve any request.

Access model
------------
* The bundled **sample project is public** — anyone can browse its files.
* An **uploaded project is private** to the account that uploaded it.
* **Uploading and asking require a signed-in account.** Browsing does not.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import time

from flask import Blueprint, jsonify, make_response, redirect, request
from sqlalchemy import select

from . import auth, config, repository
from .citations import parse_citations, validate_citations
from .db import session_scope
from .indexer import CodeIndex
from .security import inspect_upload, safe_extract_zip
from .errors import (
    AuthError,
    ConflictError,
    NotFoundError,
    RateLimited,
    UploadError,
    ValidationError,
)
from .models import User
from .retrieval import Retriever, looks_like_overview
from .sarvam_client import SarvamClient

log = logging.getLogger(__name__)

api = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
class RateLimiter:
    """Small fixed-window limiter keyed by client IP."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        now = time.time()
        with self._lock:
            window = [t for t in self._hits.get(key, []) if now - t < 60]
            if len(window) >= self.per_minute:
                raise RateLimited(
                    "Too many requests. Please wait a moment and try again."
                )
            window.append(now)
            self._hits[key] = window

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


_limiter = RateLimiter(config.RATE_LIMIT_PER_MINUTE)
# Sign-in attempts get a much tighter budget than ordinary reads.
_auth_limiter = RateLimiter(config.AUTH_RATE_LIMIT_PER_MINUTE)


def _client_key() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.", code="bad_body")
    return data


def _frontend_base() -> str:
    if config.FRONTEND_ORIGINS:
        return config.FRONTEND_ORIGINS[0].rstrip("/")
    return request.url_root.rstrip("/")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@api.get("/health")
def health():
    """Liveness plus configuration status. Never reveals a secret."""
    from .db import get_engine, storage_is_ephemeral
    return jsonify({
        "status": "ok",
        "service": "codesathi-ai",
        "version": "2.0.0",
        "sarvam": {
            "configured": bool(config.SARVAM_API_KEY),
            "model": config.SARVAM_MODEL,
            "note": ("Live Sarvam integration is active."
                     if config.SARVAM_API_KEY else
                     "SARVAM_API_KEY is not set: browsing and evidence "
                     "retrieval work, but AI explanations are unavailable."),
        },
        "auth": {
            "password_signup": True,
            "google": auth.google_configured(),
        },
        "storage": {
            "backend": get_engine().url.drivername,
            "ephemeral": storage_is_ephemeral(),
            "max_stored_bytes": config.MAX_STORED_BYTES,
            "upload_batch_bytes": config.UPLOAD_BATCH_BYTES,
        },
        "limits": {
            "max_archive_files": config.MAX_ARCHIVE_FILES,
            "max_file_bytes": config.MAX_FILE_BYTES,
        },
        "languages": config.SUPPORTED_LANGUAGES,
    }), 200


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
def _user_payload(user: User) -> dict:
    return {"user": user.to_dict()}


@api.post("/auth/signup")
def signup():
    """Create a password account and sign the caller in."""
    _auth_limiter.check(_client_key())
    body = _json_body()

    email = auth.normalise_email(body.get("email", ""))
    password = body.get("password") or ""
    full_name = (body.get("full_name") or "").strip()[:120]
    auth.validate_password_strength(password)

    with session_scope() as db:
        existing = db.execute(
            select(User).where(User.email == email)
        ).scalars().first()
        if existing is not None:
            raise ConflictError(
                "An account with that email already exists. Try signing in.",
                code="email_taken",
            )
        user = User(
            email=email,
            full_name=full_name or email.split("@")[0],
            password_hash=auth.hash_password(password),
            provider="password",
        )
        db.add(user)
        db.flush()
        token = auth.create_session(db, user, request.headers.get("User-Agent"))
        payload = user.to_dict()

    response = make_response(jsonify(payload), 201)
    return auth.set_session_cookie(response, token)


@api.post("/auth/login")
def login():
    """Verify credentials and start a session."""
    _auth_limiter.check(_client_key())
    body = _json_body()

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        raise ValidationError("Email and password are required.",
                              code="missing_credentials")

    with session_scope() as db:
        user = db.execute(select(User).where(User.email == email)).scalars().first()
        # One message for both failure modes, so accounts cannot be enumerated.
        if user is None or not auth.verify_password(password, user.password_hash):
            raise AuthError("Incorrect email or password.",
                            code="invalid_credentials", status_code=401)
        if not user.is_active:
            raise AuthError("That account is disabled.",
                            code="account_disabled", status_code=403)
        token = auth.create_session(db, user, request.headers.get("User-Agent"))
        payload = user.to_dict()

    response = make_response(jsonify(payload), 200)
    return auth.set_session_cookie(response, token)


@api.post("/auth/logout")
def logout():
    with session_scope() as db:
        auth.destroy_session(db, request.cookies.get(config.SESSION_COOKIE_NAME))
    return auth.clear_session_cookie(make_response(jsonify({"ok": True}), 200))


@api.get("/auth/me")
def me():
    """The signed-in user, or ``null``. Returns 200 either way so the client
    can probe on load without treating "signed out" as an error."""
    with session_scope() as db:
        user = auth.current_user(db)
        return jsonify({"user": user.to_dict() if user else None,
                        "google_available": auth.google_configured()}), 200


@api.get("/auth/google/start")
def google_start():
    """Begin the Google authorization-code flow."""
    if not auth.google_configured():
        raise AuthError(
            "Google sign-in is not configured on this deployment. Set "
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
            code="google_not_configured", status_code=503,
        )
    state = auth.new_oauth_state()
    response = redirect(auth.build_google_auth_url(auth.google_redirect_uri(), state))
    response.set_cookie(
        config.OAUTH_STATE_COOKIE, state,
        max_age=config.OAUTH_STATE_TTL_SECONDS,
        httponly=True, secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE, path="/",
    )
    return response


@api.get("/auth/google/callback")
def google_callback():
    """Complete the Google flow and redirect back to the app."""
    if not auth.google_configured():
        raise AuthError("Google sign-in is not configured on this deployment.",
                        code="google_not_configured", status_code=503)

    error = request.args.get("error")
    if error:
        return redirect(f"{_frontend_base()}/#/login?error={error}")

    code = request.args.get("code") or ""
    state = request.args.get("state") or ""
    expected = request.cookies.get(config.OAUTH_STATE_COOKIE) or ""
    if not code:
        raise ValidationError("Google did not return an authorization code.",
                              code="google_missing_code")
    if not expected or state != expected:
        # CSRF: the state must match the cookie we set when the flow started.
        raise AuthError("The Google sign-in request could not be verified. "
                        "Please try again.", code="google_state_mismatch",
                        status_code=400)

    access_token = auth.exchange_google_code(code, auth.google_redirect_uri())
    profile = auth.fetch_google_profile(access_token)

    with session_scope() as db:
        user = auth.upsert_google_user(db, profile)
        token = auth.create_session(db, user, request.headers.get("User-Agent"))

    response = redirect(f"{_frontend_base()}/#/app")
    auth.set_session_cookie(response, token)
    response.delete_cookie(config.OAUTH_STATE_COOKIE, path="/")
    return response


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@api.post("/projects")
def create_project():
    """Create a project and store the first batch of files.

    Archives are unpacked in the browser (Vercel caps a serverless request body
    at ~4.5 MB), so files arrive as JSON in batches. Send the first batch here,
    more via ``POST /projects/<id>/files``, then ``POST /projects/<id>/finalize``.
    """
    _limiter.check(_client_key())
    body = _json_body()

    with session_scope() as db:
        user = auth.require_user(db)
        repository.cleanup_expired(db)

        name = (body.get("name") or "untitled-project").strip()[:120]
        files = body.get("files")
        project = repository.create_project(
            db, name=name, user_id=user.id, source="upload"
        )
        stored = 0
        if files:
            stored = repository.add_files(db, project, files)
            repository.finalize_project(db, project)
        summary = repository.project_summary(project)

    summary["stored_files"] = stored
    return jsonify(summary), 201


@api.post("/projects/upload")
def upload_archive():
    """Upload a ZIP directly (server-side extraction).

    Kept for self-hosted and local use, where the archive can be unpacked to a
    temporary directory. On Vercel a serverless request body is capped at
    ~4.5 MB, so the browser unpacks the archive and uses the batch endpoints
    instead; this route still works there for small archives because ``/tmp``
    is writable.
    """
    _limiter.check(_client_key())

    if "file" not in request.files:
        raise UploadError("Attach a .zip archive in the 'file' field.",
                          code="missing_file")
    upload = request.files["file"]
    filename = upload.filename or ""
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    inspect_upload(filename, size)

    with session_scope() as db:
        user = auth.require_user(db)
        name = (request.form.get("name") or "").strip()
        if not name:
            name = os.path.splitext(os.path.basename(filename))[0] or "untitled-project"

        workdir = tempfile.mkdtemp(prefix="codesathi-")
        zip_path = os.path.join(workdir, "__upload__.zip")
        try:
            upload.save(zip_path)
            result = safe_extract_zip(zip_path, workdir)
            index = CodeIndex.build(workdir)
            if not index.files:
                raise UploadError(
                    "The archive contained no files this tool can index.",
                    code="no_indexable_files",
                )
            project = repository.create_project(
                db, name=name, user_id=user.id, source="upload"
            )
            repository.add_files(db, project, [
                {"path": f.path, "content": "\n".join(f.lines)}
                for f in sorted(index.files.values(), key=lambda x: x.path)
            ])
            repository.finalize_project(db, project)
            project.skipped_entries = result.skipped_entries
            project.skip_reasons_json = json.dumps(result.skip_reasons)
            db.flush()
            summary = repository.project_summary(project)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        return jsonify(summary), 201


@api.post("/projects/<project_id>/files")
def append_files(project_id: str):
    """Append another batch of files to an in-progress upload."""
    _limiter.check(_client_key())
    body = _json_body()

    with session_scope() as db:
        user = auth.require_user(db)
        project = repository.get_owned_project(db, project_id, user)
        if project.status != "uploading":
            raise ValidationError(
                "This project is already complete.", code="project_already_finalized"
            )
        stored = repository.add_files(db, project, body.get("files"))
        return jsonify({
            "project_id": project.id,
            "stored_files": stored,
            "file_count": project.file_count,
            "total_bytes": project.total_bytes,
        }), 200


@api.post("/projects/<project_id>/finalize")
def finalize_project(project_id: str):
    """Finish an upload and build the index."""
    _limiter.check(_client_key())

    with session_scope() as db:
        user = auth.require_user(db)
        project = repository.get_owned_project(db, project_id, user)
        if project.status == "uploading":
            repository.finalize_project(db, project)
        if not project.file_count:
            raise UploadError(
                "No indexable source files were found in that archive.",
                code="no_source_files",
            )
        return jsonify(repository.project_summary(project)), 200


@api.post("/projects/sample")
def load_sample():
    """Load (or return) the bundled sample repository. Public."""
    _limiter.check(_client_key())
    with session_scope() as db:
        project = repository.get_or_create_sample_project(db)
        return jsonify(repository.project_summary(project)), 200


@api.get("/projects")
def list_projects():
    """The signed-in user's own projects."""
    with session_scope() as db:
        user = auth.require_user(db)
        return jsonify({"projects": repository.list_projects(db, user)}), 200


@api.get("/projects/<project_id>/files")
def project_files(project_id: str):
    with session_scope() as db:
        user = auth.current_user(db)
        project = repository.get_project(db, project_id, user=user)
        repository.touch(project)
        index = repository.build_index(db, project)
        return jsonify({
            "project_id": project.id,
            "name": project.name,
            "source": project.source,
            "tree": index.file_tree(),
            "stats": index.stats(),
            "files": [
                {"path": f.path, "language": f.language, "line_count": f.line_count,
                 "parser": f.parser, "symbols": [s.to_dict() for s in f.symbols]}
                for f in sorted(index.files.values(), key=lambda x: x.path)
            ],
        }), 200


@api.get("/projects/<project_id>/file")
def project_file(project_id: str):
    """One file's contents. ``path`` must exist in the project's index."""
    path = (request.args.get("path") or "").strip()
    if not path:
        raise ValidationError("A 'path' query parameter is required.",
                              code="missing_path")

    with session_scope() as db:
        user = auth.current_user(db)
        project = repository.get_project(db, project_id, user=user)
        index = repository.build_index(db, project)
        indexed = index.get(path)
        if indexed is None:
            raise ValidationError("That path is not part of this project.",
                                  code="path_not_in_project")

        start = request.args.get("start", type=int)
        end = request.args.get("end", type=int)
        if start is not None or end is not None:
            start = max(1, start or 1)
            end = min(indexed.line_count, end or indexed.line_count)
            pairs = index.read_lines(path, start, end)
        else:
            start, end = 1, indexed.line_count
            pairs = list(enumerate(indexed.lines, start=1))

        return jsonify({
            "path": indexed.path,
            "language": indexed.language,
            "parser": indexed.parser,
            "line_count": indexed.line_count,
            "start_line": start,
            "end_line": end,
            "symbols": [s.to_dict() for s in indexed.symbols],
            "lines": [{"number": n, "text": t} for n, t in pairs],
        }), 200


@api.get("/projects/<project_id>/search")
def project_search(project_id: str):
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        raise ValidationError("Search needs at least two characters.",
                              code="query_too_short")
    with session_scope() as db:
        user = auth.current_user(db)
        project = repository.get_project(db, project_id, user=user)
        index = repository.build_index(db, project)
        return jsonify({"query": q, "results": index.search(q)}), 200


@api.delete("/projects/<project_id>")
def delete_project(project_id: str):
    with session_scope() as db:
        user = auth.require_user(db)
        project = repository.get_owned_project(db, project_id, user)
        repository.delete_project(db, project)
        return jsonify({"deleted": True, "project_id": project_id}), 200


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------
def _parse_focus(body: dict, index: CodeIndex) -> dict | None:
    """The file (and optional selection) the user is looking at.

    The client sends this so an anaphoric question — "explain this" — has a
    subject. A stale path is ignored rather than rejected: the user may have
    switched project between opening the file and asking.
    """
    raw = body.get("focus")
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path") or "").replace("\\", "/").strip()
    if not path or index.get(path) is None:
        return None

    def _int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return {
        "path": path,
        "start_line": _int(raw.get("start_line")),
        "end_line": _int(raw.get("end_line")),
    }


def _last_user_question(history, current: str) -> str | None:
    """The most recent earlier question, so a follow-up inherits its terms."""
    for turn in reversed(history or []):
        if not isinstance(turn, dict) or turn.get("role") != "user":
            continue
        content = (turn.get("content") or "").strip()
        if content and content != current:
            return content
    return None


def _context_note(mode: str, retrieval, previous_question: str | None) -> str | None:
    """Tell the model what the question is actually pointing at."""
    if mode == "focus":
        first = retrieval.snippets[0]
        return (
            f"Context: the user is asking about `{first.path}` lines "
            f"{first.start_line}-{first.end_line}, which they have open in the "
            f"code viewer. Treat that code as the subject of the question."
        )
    if mode == "previous":
        return (
            f"Context: this is a follow-up to the earlier question "
            f"{previous_question!r}. The snippets were retrieved for that "
            f"earlier question, so answer the follow-up about them."
        )
    if mode == "overview":
        return (
            "Context: the question is about the project as a whole and the "
            "snippets are an overview (README, entry points, configuration). "
            "Describe what the project does, its main entry points and how it "
            "is organised. The instruction to ignore unrelated snippets does "
            "not apply to this overview question."
        )
    return None


@api.post("/projects/<project_id>/ask")
def ask(project_id: str):
    """Retrieve evidence for a question and ask Sarvam to explain it."""
    _limiter.check(_client_key())
    body = _json_body()

    question = (body.get("question") or "").strip()
    if not question:
        raise ValidationError("Ask a question first.", code="missing_question")
    if len(question) > 2000:
        raise ValidationError("That question is too long (2000 character limit).",
                              code="question_too_long")

    language = (body.get("language") or "en-IN").strip()
    if language not in config.SUPPORTED_LANGUAGES:
        raise ValidationError(
            f"Unsupported language '{language}'. Supported: "
            f"{', '.join(config.SUPPORTED_LANGUAGES)}.",
            code="unsupported_language",
        )

    history = body.get("history")
    if history is not None and not isinstance(history, list):
        raise ValidationError("'history' must be a list.", code="bad_history")

    with session_scope() as db:
        user = auth.require_user(db)
        project = repository.get_project(db, project_id, user=user)
        repository.touch(project)
        index = repository.build_index(db, project)

        focus = _parse_focus(body, index)

        retriever = Retriever(index)
        retrieval = retriever.retrieve(question)
        mode = "question" if retrieval.snippets else "none"
        context: dict = {"mode": mode}
        suggestions = retriever.suggestions()

        # A question such as "explain this" carries no searchable term. Rather
        # than give up before the model is even called, resolve it against the
        # code the user is looking at, then the previous turn, and only then
        # against the project as a whole.
        # Only a question that names *nothing* is anaphoric enough to answer
        # from the open file. A question that names a symbol the repository
        # does not contain ("zzzqqqxyw") is a genuine miss: it must stay a
        # dead end with suggestions rather than be answered about some file.
        if mode == "none" and focus and not retrieval.terms:
            retrieval = retriever.retrieve_focus(
                focus["path"], focus["start_line"], focus["end_line"]
            )
            if retrieval.snippets:
                mode = "focus"
                first = retrieval.snippets[0]
                context = {"mode": mode, "path": first.path,
                           "start_line": first.start_line,
                           "end_line": first.end_line}

        if mode == "none":
            previous = _last_user_question(history, question)
            if previous:
                retrieval = retriever.retrieve(previous)
                if retrieval.snippets:
                    mode = "previous"
                    context = {"mode": mode, "question": previous}

        if mode == "none" and looks_like_overview(question):
            retrieval = retriever.retrieve_overview()
            if retrieval.snippets:
                mode = "overview"
                context = {"mode": mode}

        if not retrieval.snippets:
            return jsonify({
                "project_id": project.id,
                "question": question,
                "language": language,
                "answer": None,
                "steps": [],
                "key_files": [],
                "citations": [],
                "rejected_citations": [],
                "uncertainty": ("No relevant source code was found for that "
                                "question in this project. Try naming a file, "
                                "function, or feature such as 'login' or "
                                "'database', or open a file and ask "
                                "'explain this'."),
                "followups": [],
                "evidence": [],
                "retrieval_terms": retrieval.terms,
                "model": None,
                "usage": None,
                "structured": False,
                "truncated": False,
                "sarvam_called": False,
                "context": context,
                "suggestions": suggestions,
            }), 200

        # The note travels with the retrieval, so the client interface stays
        # the same as it was before the fallbacks existed.
        retrieval.note = _context_note(mode, retrieval, context.get("question")) or ""
        result = SarvamClient().answer(question, language, retrieval,
                                       history=history or [])

        structured = result.get("structured") or {}
        raw_text = result.get("raw_text") or ""

        if structured:
            answer = str(structured.get("answer") or "").strip()
            steps = structured.get("steps") or []
            key_files = structured.get("key_files") or []
            uncertainty = str(structured.get("uncertainty") or "").strip()
            followups = structured.get("followups") or []
            raw_citations = structured.get("citations") or []
        else:
            answer = raw_text.strip()
            steps, key_files, followups, raw_citations = [], [], [], []
            uncertainty = ("The model did not return a structured, "
                           "machine-checkable answer, so no citations could be "
                           "verified for this reply.")

        if result.get("truncated"):
            note = ("Sarvam hit the token budget, so this answer may stop "
                    "short. Raise SARVAM_MAX_TOKENS for a longer reply.")
            uncertainty = f"{uncertainty} {note}".strip() if uncertainty else note

        context_ids = {s.citation_id for s in retrieval.snippets}
        verified, rejected = validate_citations(
            parse_citations(raw_citations), index, context_ids
        )

        return jsonify({
            "project_id": project.id,
            "question": question,
            "language": language,
            "answer": answer,
            "steps": steps if isinstance(steps, list) else [],
            "key_files": key_files if isinstance(key_files, list) else [],
            "citations": verified,
            "rejected_citations": rejected,
            "uncertainty": uncertainty,
            "followups": [f for f in followups if isinstance(f, str)][:3]
                         if isinstance(followups, list) else [],
            "evidence": [s.to_dict() for s in retrieval.snippets],
            "retrieval_terms": retrieval.terms,
            "model": result.get("model"),
            "usage": result.get("usage"),
            "structured": bool(structured),
            "truncated": bool(result.get("truncated")),
            "sarvam_called": True,
            "context": context,
            "suggestions": suggestions,
        }), 200


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
def register_error_handlers(app) -> None:
    from .errors import CodeSathiError

    @app.errorhandler(CodeSathiError)
    def _handle_app_error(err: CodeSathiError):
        return jsonify(err.to_dict()), err.status_code

    @app.errorhandler(413)
    def _handle_too_large(_err):
        return jsonify({
            "error": "That request body is larger than the server allows.",
            "code": "payload_too_large",
        }), 413

    @app.errorhandler(404)
    def _handle_404(_err):
        return jsonify({"error": "No such endpoint.", "code": "not_found"}), 404

    @app.errorhandler(405)
    def _handle_405(_err):
        return jsonify({"error": "Method not allowed.",
                        "code": "method_not_allowed"}), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):  # pragma: no cover - safety net
        log.exception("Unhandled error: %s", err)
        return jsonify({"error": "Something went wrong on the server.",
                        "code": "internal_error"}), 500
