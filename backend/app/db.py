"""Database engine and session management.

The storage layer is deliberately the *same code* in every environment:

* **Production (Vercel)** — a hosted Postgres (Neon / Vercel Postgres) given by
  ``DATABASE_URL``. Serverless functions have no persistent disk and no memory
  shared between invocations, so nothing may be kept in the process.
* **Local development** — a SQLite file, created automatically.
* **Tests** — an in-memory SQLite database.

Using one path everywhere means the tests exercise the storage code that
production actually runs, rather than a stand-in.

The Postgres driver is **pg8000**, which is pure Python. That matters on
serverless: it installs with no compiler and no platform-specific wheel, so a
Vercel build cannot fail on a native dependency.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None
_initialised = False


def database_url() -> str:
    """Resolve the database URL for this environment."""
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        # Local development: a file next to the backend.
        path = os.environ.get("SQLITE_PATH", os.path.join(os.getcwd(), "codesathi.db"))
        return f"sqlite:///{path}"
    # Hosted providers hand out `postgres://`, which SQLAlchemy no longer maps.
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql+pg8000://", 1)
    elif raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+pg8000://", 1)
    return raw


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # StaticPool keeps a single connection so an in-memory database is
        # shared across threads (the Flask test client uses another thread).
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url.endswith("sqlite://"):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, future=True, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    connect_args: dict = {}
    if url.startswith("postgresql+pg8000"):
        # Neon and friends require TLS. pg8000 takes an SSL context rather than
        # a `sslmode` query parameter.
        if "localhost" not in url and "127.0.0.1" not in url:
            connect_args["ssl_context"] = True
        connect_args["timeout"] = 15

    return create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        pool_recycle=280,      # shorter than a typical serverless idle window
        pool_size=2,
        max_overflow=2,
        connect_args=connect_args,
    )


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine(database_url())
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def init_db() -> None:
    """Create tables if they do not exist. Safe to call on every cold start."""
    global _initialised
    if _initialised:
        return
    Base.metadata.create_all(bind=get_engine())
    _initialised = True
    log.info("Database ready (%s)", get_engine().url.drivername)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on failure."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_for_tests(url: str = "sqlite://") -> None:
    """Point the layer at a fresh database. Used by the test suite."""
    global _engine, _SessionLocal, _initialised
    if _engine is not None:
        _engine.dispose()
    _engine = _build_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    Base.metadata.create_all(bind=_engine)
    _initialised = True


def dispose() -> None:
    global _engine, _SessionLocal, _initialised
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _initialised = False
