"""The User model.

A minimal SQLAlchemy declarative model representing a registered customer or
admin account. Passwords are never stored in plain text: ``password_hash``
holds a bcrypt hash produced by utils.security.hash_password.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    """A registered account."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(120), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="customer")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        """Serialise the public fields of a user (never the password hash)."""
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "is_active": self.is_active,
        }

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"
