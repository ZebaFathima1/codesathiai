"""ShopEasy API - application entry point.

A small Flask service used as the bundled sample repository for CodeSathi AI.
It wires together configuration, the database, authentication and the API
blueprints. Real source, not a mock.
"""
from flask import Flask, jsonify

from api.orders import orders_bp
from api.users import users_bp
from auth.login import auth_bp
from config.database import init_db
from utils.logger import get_logger

log = get_logger(__name__)


def create_app(config_name: str = "development") -> Flask:
    """Application factory.

    Creates the Flask app, loads configuration, initialises the database and
    registers every blueprint that makes up the public API surface.
    """
    app = Flask(__name__)
    app.config.from_object(f"config.settings.{config_name.capitalize()}Config")

    # Initialise the SQLAlchemy-backed store. In this sample project the
    # connection string comes from config/settings.py.
    init_db(app)

    # Every HTTP route in the service is registered from a blueprint below.
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    app.register_blueprint(orders_bp, url_prefix="/api/orders")

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "service": "shopeasy"})

    log.info("ShopEasy app created with config=%s", config_name)
    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=True)
