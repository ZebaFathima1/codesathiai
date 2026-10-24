"""Vercel serverless entry point.

Vercel's Python runtime looks for a WSGI callable named ``app`` in a file under
``api/``. This module puts the backend package on the import path and builds the
same application the local ``run.py`` does, so there is one code path for both.

Nothing here holds state between requests: the database is external (Postgres)
and the code index is rebuilt from stored rows, because a serverless instance
may be frozen or replaced between any two requests.
"""
import os
import sys

# The Flask package lives in backend/app; the function runs from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "backend"))

from app import create_app  # noqa: E402  (import after sys.path is set)

app = create_app()
