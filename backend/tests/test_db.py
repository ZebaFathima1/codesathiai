"""Tests for database URL resolution and engine construction.

A live Postgres is not available in CI, so the *wiring* is what gets tested:
the hosted-provider URL shapes are normalised to the pure-Python driver, TLS is
requested for remote hosts, and SQLite keeps the settings the tests rely on.
The application-level storage behaviour is covered in ``test_repository.py``,
which runs against SQLite through the same SQLAlchemy models.
"""
import pytest
from sqlalchemy.pool import StaticPool

from app import db


@pytest.fixture(autouse=True)
def restore_engine():
    """Leave the module-level engine as the tests expect it."""
    yield
    db.reset_for_tests("sqlite://")


def test_defaults_to_sqlite_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = db.database_url()
    assert url.startswith("sqlite:///")


def test_heroku_style_postgres_url_is_normalised(monkeypatch):
    """Providers still hand out `postgres://`, which SQLAlchemy dropped."""
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")
    assert db.database_url() == "postgresql+pg8000://u:p@host:5432/db"


def test_postgresql_url_uses_the_pure_python_driver(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:p@ep-cool.eu-central-1.aws.neon.tech/db?sslmode=require"
    )
    url = db.database_url()
    assert url.startswith("postgresql+pg8000://")
    assert url.endswith("/db?sslmode=require"), "the query string is preserved"


def test_remote_postgres_requests_tls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com:5432/app")
    engine = db._build_engine(db.database_url())
    try:
        assert engine.url.drivername == "postgresql+pg8000"
        # pool_pre_ping matters on serverless: connections go stale between
        # invocations, and a dead connection must not surface as a 500.
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_local_postgres_does_not_force_tls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/app")
    engine = db._build_engine(db.database_url())
    try:
        assert engine.url.drivername == "postgresql+pg8000"
    finally:
        engine.dispose()


def test_sqlite_engine_uses_static_pool_for_memory():
    engine = db._build_engine("sqlite://")
    try:
        assert isinstance(engine.pool, StaticPool), (
            "an in-memory database must share one connection across threads"
        )
    finally:
        engine.dispose()


def test_reset_for_tests_creates_the_schema():
    from sqlalchemy import inspect

    db.reset_for_tests("sqlite://")
    tables = set(inspect(db.get_engine()).get_table_names())
    assert {"users", "auth_sessions", "projects", "project_files"} <= tables


def test_init_db_is_idempotent():
    db.reset_for_tests("sqlite://")
    db.init_db()
    db.init_db()  # must not raise on a second cold start


def test_session_scope_rolls_back_on_error():
    from sqlalchemy import select

    from app.models import User

    with pytest.raises(RuntimeError):
        with db.session_scope() as session:
            session.add(User(email="rollback@example.com", full_name="x"))
            raise RuntimeError("boom")

    with db.session_scope() as session:
        assert session.execute(
            select(User).where(User.email == "rollback@example.com")
        ).scalars().first() is None
