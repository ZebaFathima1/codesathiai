"""User API blueprint: registration and profile lookup."""
from flask import Blueprint, jsonify, request

from models.user import User
from utils.security import hash_password

users_bp = Blueprint("users", __name__)


@users_bp.route("/register", methods=["POST"])
def register():
    """Create a new account.

    Validates the payload, hashes the password and persists the user.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()

    if not email or not password or not full_name:
        return jsonify({"error": "email, password and full_name are required"}), 400

    if User.query.filter_by(email=email).first() is not None:
        return jsonify({"error": "email already registered"}), 409

    user = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        role="customer",
    )
    from config.database import get_session

    session = get_session()
    session.add(user)
    session.commit()
    return jsonify(user.to_dict()), 201


@users_bp.route("/<int:user_id>", methods=["GET"])
def get_user(user_id: int):
    """Return a single user profile by id."""
    user = User.query.get(user_id)
    if user is None:
        return jsonify({"error": "user not found"}), 404
    return jsonify(user.to_dict()), 200
