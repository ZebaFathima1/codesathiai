"""Authentication: password accounts, server-side sessions, Google sign-in.

Design notes
------------
* **Password hashing uses PBKDF2-HMAC-SHA256 from the standard library**, with a
  per-account salt and 600,000 iterations (the OWASP recommendation for this
  algorithm). This is deliberate: serverless builds fail on native
  dependencies, and a pure-stdlib hash cannot break a Vercel deploy. The stored
  format is ``pbkdf2_sha256$iterations$salt$hash``, so the cost can be raised
  later without invalidating existing passwords.
* **Sessions are server-side.** The cookie holds a 256-bit random token; the
  database stores only its SHA-256 hash. Deleting a row logs the user out, and
  a database leak does not yield usable tokens.
* **Google sign-in uses the authorization-code flow** and reads the profile
  from Google's TLS-protected userinfo endpoint, so no JWT verification library
  is needed. The ``state`` parameter is checked against a short-lived cookie to
  block CSRF.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Response, current_app, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .errors import AuthError, ValidationError
from .models import AuthSession, User

log = logging.getLogger(__name__)

PBKDF2_ITERATIONS = 600_000
PBKDF2_ALGORITHM = "pbkdf2_sha256"

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256."""
    if not password:
        raise ValidationError("Password must not be empty.", code="empty_password")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return "{}${}${}${}".format(
        PBKDF2_ALGORITHM,
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time password check. Returns False for unusable hashes."""
    if not password or not stored:
        return False
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored.split("$")
        if algorithm != PBKDF2_ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


def validate_password_strength(password: str) -> None:
    if len(password) < config.MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters.",
            code="weak_password",
        )
    if len(password) > 200:
        raise ValidationError("Password is too long.", code="weak_password")


def normalise_email(email: str) -> str:
    """Lower-case and validate an email address.

    Deliberately strict about shape but not about exotic-but-legal addresses:
    exactly one ``@``, a non-empty local part, and a dotted domain. Real
    deliverability is proven by the account actually working.
    """
    value = (email or "").strip().lower()
    if len(value) > 255:
        raise ValidationError("That email address is too long.", code="invalid_email")
    if value.count("@") != 1:
        raise ValidationError("Enter a valid email address.", code="invalid_email")
    local, _, domain = value.partition("@")
    if (not local or not domain or "." not in domain
            or domain.startswith(".") or domain.endswith(".")):
        raise ValidationError("Enter a valid email address.", code="invalid_email")
    return value


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, user_agent: str | None = None) -> str:
    """Create a session row and return the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        id=_token_hash(token),
        user_id=user.id,
        expires_at=_now() + timedelta(days=config.SESSION_TTL_DAYS),
        user_agent=(user_agent or "")[:255] or None,
    ))
    db.flush()
    return token


def resolve_session(db: Session, token: str | None) -> User | None:
    """Return the user for a session token, or None if it is missing/expired."""
    if not token:
        return None
    row = db.get(AuthSession, _token_hash(token))
    if row is None:
        return None
    if row.expires_at <= _now():
        db.delete(row)
        db.flush()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def destroy_session(db: Session, token: str | None) -> bool:
    if not token:
        return False
    row = db.get(AuthSession, _token_hash(token))
    if row is None:
        return False
    db.delete(row)
    return True


def purge_expired_sessions(db: Session) -> int:
    rows = db.execute(
        select(AuthSession).where(AuthSession.expires_at <= _now())
    ).scalars().all()
    for row in rows:
        db.delete(row)
    return len(rows)


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------
def set_session_cookie(response: Response, token: str) -> Response:
    response.set_cookie(
        config.SESSION_COOKIE_NAME,
        token,
        max_age=config.SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="Lax",
        path="/",
    )
    return response


def clear_session_cookie(response: Response) -> Response:
    response.delete_cookie(
        config.SESSION_COOKIE_NAME,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="Lax",
        path="/",
    )
    return response


def current_user(db: Session) -> User | None:
    """The signed-in user for this request, if any."""
    return resolve_session(db, request.cookies.get(config.SESSION_COOKIE_NAME))


def require_user(db: Session):
    """Load the current user or raise 401. Returns the user."""
    user = current_user(db)
    if user is None:
        raise AuthError(
            "Sign in to continue.", code="not_authenticated", status_code=401
        )
    return user


# ---------------------------------------------------------------------------
# Google sign-in
# ---------------------------------------------------------------------------
def google_configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def google_redirect_uri() -> str:
    """Explicit override, else derived from the incoming request."""
    if config.GOOGLE_REDIRECT_URI:
        return config.GOOGLE_REDIRECT_URI
    return request.url_root.rstrip("/") + "/api/auth/google/callback"


def build_google_auth_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _http_json(url: str, data: dict | None = None, headers: dict | None = None,
               method: str = "GET") -> dict:
    """Small JSON HTTP helper. Isolated so tests can replace it."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def exchange_google_code(code: str, redirect_uri: str) -> str:
    """Trade an authorization code for an access token."""
    payload = {
        "code": code,
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        result = _http_json(GOOGLE_TOKEN_ENDPOINT, data=payload, method="POST")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        log.warning("Google token exchange failed: %s %s", exc.code, detail)
        raise AuthError(
            "Google sign-in failed. Please try again.",
            code="google_exchange_failed", status_code=502,
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AuthError(
            "Could not reach Google to complete sign-in.",
            code="google_unreachable", status_code=502,
        ) from exc

    token = result.get("access_token")
    if not token:
        raise AuthError("Google did not return an access token.",
                        code="google_exchange_failed", status_code=502)
    return token


def fetch_google_profile(access_token: str) -> dict:
    """Read the signed-in Google profile from the userinfo endpoint."""
    try:
        profile = _http_json(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise AuthError("Could not read your Google profile.",
                        code="google_profile_failed", status_code=502) from exc

    if not profile.get("sub") or not profile.get("email"):
        raise AuthError("Google did not return an email address.",
                        code="google_profile_failed", status_code=502)
    return profile


def upsert_google_user(db: Session, profile: dict) -> User:
    """Find or create the account behind a Google profile.

    An existing password account with the same verified email is linked rather
    than duplicated, so a user who signed up with a password can later use
    Google and land on the same account.
    """
    sub = str(profile["sub"])
    email = normalise_email(profile.get("email", ""))
    if not profile.get("email_verified", True):
        raise AuthError("That Google email address is not verified.",
                        code="google_email_unverified", status_code=403)

    user = db.execute(select(User).where(User.google_sub == sub)).scalars().first()
    if user is None:
        user = db.execute(select(User).where(User.email == email)).scalars().first()

    if user is None:
        user = User(
            email=email,
            full_name=(profile.get("name") or email.split("@")[0])[:120],
            provider="google",
            google_sub=sub,
            avatar_url=(profile.get("picture") or None),
        )
        db.add(user)
    else:
        user.google_sub = sub
        user.avatar_url = profile.get("picture") or user.avatar_url
        if not user.full_name and profile.get("name"):
            user.full_name = profile["name"][:120]
    db.flush()
    return user


def new_oauth_state() -> str:
    return secrets.token_urlsafe(24)
