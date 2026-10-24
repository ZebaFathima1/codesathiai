"""Environment-specific settings for ShopEasy.

Configuration is layered: base values live in ``BaseConfig`` and each
environment overrides what it needs. Secrets are always read from the
environment so they never end up in source control.
"""
import os


class BaseConfig:
    """Settings shared by every environment."""

    # SECRET_KEY signs session cookies and JWTs. Never hard-code this.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    JWT_EXPIRY_MINUTES = int(os.environ.get("JWT_EXPIRY_MINUTES", "60"))

    # Database connection string, e.g.
    # postgresql://user:pass@localhost:5432/shopeasy
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///shopeasy.db")
    DB_POOL_PRE_PING = True

    # Password hashing parameters.
    BCRYPT_ROUNDS = int(os.environ.get("BCRYPT_ROUNDS", "12"))


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    DB_POOL_PRE_PING = True


class TestConfig(BaseConfig):
    TESTING = True
    DATABASE_URL = "sqlite:///:memory:"
