"""Password hashing helpers.

Wraps bcrypt so the rest of the codebase never touches the hashing library
directly. ``hash_password`` is used at registration and ``check_password`` at
login time.
"""
import bcrypt


def hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt.

    Returns the hash as a UTF-8 string ready to be stored in the database.
    """
    if not plain:
        raise ValueError("password must not be empty")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def check_password(plain: str, hashed: str) -> bool:
    """Return True when ``plain`` matches the stored bcrypt ``hashed`` value."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the database: treat as a failed login.
        return False
