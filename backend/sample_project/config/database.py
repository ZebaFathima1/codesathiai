"""Database configuration and session management.

This module is the single place where the database connection is created.
``DATABASE_URL`` is read from the application config, which in turn reads it
from the environment (see config/settings.py). Nothing else in the project
opens a connection directly.
"""
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from models.user import Base

# Module level handles, populated by init_db().
engine = None
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False))


def init_db(app: Flask) -> None:
    """Create the engine, bind the session and create tables.

    Args:
        app: the Flask application whose config holds ``DATABASE_URL``.
    """
    global engine

    database_url = app.config["DATABASE_URL"]
    pool_pre_ping = app.config.get("DB_POOL_PRE_PING", True)

    # ``pool_pre_ping`` protects against connections dropped by the database
    # server between requests.
    engine = create_engine(database_url, pool_pre_ping=pool_pre_ping)
    SessionLocal.configure(bind=engine)

    # For this sample project we create tables on boot. A production service
    # would run migrations (Alembic) instead.
    Base.metadata.create_all(bind=engine)


def get_session():
    """Return the thread-local SQLAlchemy session."""
    return SessionLocal()
