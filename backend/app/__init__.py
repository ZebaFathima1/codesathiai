"""CodeSathi AI backend — Flask application factory."""
from __future__ import annotations

import logging
import os

from flask import Flask, jsonify
from flask_cors import CORS

from . import config
from .db import init_db
from .routes import api, register_error_handlers


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def create_app(config_overrides: dict | None = None) -> Flask:
    """Build and configure the Flask application."""
    _configure_logging()

    app = Flask(__name__)
    # Bounds a single JSON batch. Vercel caps a serverless body at ~4.5 MB, so
    # this is deliberately close to that rather than the old 25 MB archive size.
    app.config["MAX_CONTENT_LENGTH"] = config.UPLOAD_BATCH_BYTES + 2 * 1024 * 1024
    app.config["JSON_SORT_KEYS"] = False
    if config_overrides:
        app.config.update(config_overrides)

    # Tables are created on first use, which is idempotent and safe to repeat
    # on every cold start.
    init_db()

    # CORS is restricted to the configured frontend origins, and credentials
    # are allowed so the session cookie can be sent. In production the frontend
    # and API share an origin, so this is only exercised in local development.
    CORS(
        app,
        resources={r"/api/*": {"origins": config.FRONTEND_ORIGINS}},
        methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
        supports_credentials=True,
        max_age=600,
    )

    app.register_blueprint(api, url_prefix="/api")
    register_error_handlers(app)

    @app.get("/")
    def index():
        return jsonify({
            "service": "CodeSathi AI API",
            "docs": "/api/health",
            "message": "Understand code, in your language.",
        }), 200

    return app


__all__ = ["create_app"]
