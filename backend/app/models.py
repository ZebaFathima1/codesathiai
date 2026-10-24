"""SQLAlchemy models for users, sessions, projects and indexed files.

Everything the application needs to survive a restart lives here. Nothing is
kept in process memory, because a serverless function may be frozen or replaced
between any two requests.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """A registered account."""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(120), nullable=False, default="")
    # NULL for accounts created through an identity provider.
    password_hash = Column(String(255), nullable=True)
    provider = Column(String(20), nullable=False, default="password")
    google_sub = Column(String(64), nullable=True, unique=True, index=True)
    avatar_url = Column(String(512), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    projects = relationship("Project", back_populates="owner")

    def to_dict(self) -> dict:
        """Public representation. Never includes the password hash."""
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "provider": self.provider,
            "avatar_url": self.avatar_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuthSession(Base):
    """A server-side session.

    Only the SHA-256 hash of the cookie value is stored, so a database leak
    does not hand an attacker usable session tokens.
    """

    __tablename__ = "auth_sessions"

    id = Column(String(64), primary_key=True)          # sha256 hex of the token
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    expires_at = Column(DateTime, nullable=False)
    user_agent = Column(String(255), nullable=True)

    user = relationship("User")


class Project(Base):
    """An indexed repository.

    ``user_id`` is NULL for the bundled sample project, which is public. Every
    other project belongs to exactly one account.
    """

    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=True, index=True)
    name = Column(String(120), nullable=False, default="untitled-project")
    source = Column(String(16), nullable=False, default="upload")   # upload | sample
    status = Column(String(16), nullable=False, default="ready")    # uploading | ready
    stats_json = Column(Text, nullable=False, default="{}")
    file_count = Column(Integer, nullable=False, default=0)
    total_bytes = Column(Integer, nullable=False, default=0)
    skipped_entries = Column(Integer, nullable=False, default=0)
    skip_reasons_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=_now)
    last_used_at = Column(DateTime, nullable=False, default=_now)

    owner = relationship("User", back_populates="projects")
    files = relationship("ProjectFile", back_populates="project",
                         cascade="all, delete-orphan")

    def is_public(self) -> bool:
        return self.user_id is None

    def owned_by(self, user_id: str | None) -> bool:
        return self.user_id is not None and self.user_id == user_id


class ProjectFile(Base):
    """One source file, with its exact original text.

    Storing the content is what lets the index be rebuilt on demand in a
    stateless function, and what lets the code viewer show real lines.
    """

    __tablename__ = "project_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    path = Column(String(512), nullable=False)
    language = Column(String(40), nullable=False, default="Text")
    line_count = Column(Integer, nullable=False, default=0)
    size = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False, default="")

    project = relationship("Project", back_populates="files")


# Lookups are always "the files of this project", often ordered by path.
Index("ix_project_files_project_path", ProjectFile.project_id, ProjectFile.path)
