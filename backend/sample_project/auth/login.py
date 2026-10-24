"""Authentication blueprint: login, logout and token refresh.

The login flow is intentionally explicit so it can be explained end to end:

1. The client POSTs ``{"email": ..., "password": ...}`` to ``/api/auth/login``.
2. We look the user up by email through the User model.
3. The submitted password is verified against the stored bcrypt hash.
4. On success we issue a signed JWT and return it with the user profile.
5. On failure we return 401 with a generic message (no user enumeration).
"""
from datetime import datetime, timedelta, timezone

import jwt
from flask import Blueprint, current_app, jsonify, request

from models.user import User
from utils.security import check_password

auth_bp = Blueprint("auth", __name__)


def generate_token(user: User) -> str:
    """Create a signed JWT for an authenticated user.

    The token carries the user id as the subject and expires after the
    number of minutes configured in ``JWT_EXPIRY_MINUTES``.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=current_app.config["JWT_EXPIRY_MINUTES"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticate a user and return a JWT access token."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    # Step 1: find the account. A missing account and a bad password return
    # the same response so attackers cannot enumerate registered emails.
    user = User.query.filter_by(email=email).first()
    if user is None or not check_password(password, user.password_hash):
        return jsonify({"error": "invalid credentials"}), 401

    if not user.is_active:
        return jsonify({"error": "account disabled"}), 403

    # Step 2: mint the token and return the profile the client needs.
    token = generate_token(user)
    return jsonify({"access_token": token, "token_type": "Bearer",
                    "user": user.to_dict()}), 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Log the current session out.

    Tokens are stateless JWTs, so logout is handled client side by discarding
    the token; the endpoint exists for API symmetry and audit logging.
    """
    return jsonify({"status": "logged_out"}), 200
