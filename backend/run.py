"""Development entry point for the CodeSathi AI backend.

Usage:
    python run.py
"""
import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402  (import after env is loaded)

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=port, debug=debug)
