"""Central configuration for the CodeSathi AI backend.

Everything tunable lives here and is read from the environment so that no
secret or environment-specific value is ever hard-coded in application logic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------
# Upload / archive safety limits
# --------------------------------------------------------------------------
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", 25 * 1024 * 1024)          # 25 MB
MAX_EXTRACTED_BYTES = _env_int("MAX_EXTRACTED_BYTES", 80 * 1024 * 1024)    # 80 MB
MAX_ARCHIVE_FILES = _env_int("MAX_ARCHIVE_FILES", 4000)
MAX_FILE_BYTES = _env_int("MAX_FILE_BYTES", 1_500_000)                     # 1.5 MB / file
MAX_COMPRESSION_RATIO = _env_int("MAX_COMPRESSION_RATIO", 200)             # zip-bomb guard
MIN_RATIO_CHECK_BYTES = 64 * 1024

# --------------------------------------------------------------------------
# Indexing / retrieval
# --------------------------------------------------------------------------
MAX_INDEXED_FILES = _env_int("MAX_INDEXED_FILES", 1500)
MAX_INDEXED_FILE_BYTES = _env_int("MAX_INDEXED_FILE_BYTES", 512_000)
SNIPPET_MAX_LINES = _env_int("SNIPPET_MAX_LINES", 60)
CONTEXT_CHAR_BUDGET = _env_int("CONTEXT_CHAR_BUDGET", 24_000)
MAX_SNIPPETS = _env_int("MAX_SNIPPETS", 8)

# --------------------------------------------------------------------------
# Sarvam
# --------------------------------------------------------------------------
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "").strip()
SARVAM_MODEL = os.environ.get("SARVAM_MODEL", "sarvam-105b")
# Response format. Measured against the live API, `json_schema` (strict or
# not) intermittently made the model pad the reply with thousands of newlines
# and never emit a stop token — 46-59s per answer and the later fields lost.
# `json_object` always terminated cleanly in 2-4s with the same field names,
# so it is the default. The JSON shape is still specified in the system
# prompt, and the parser tolerates the field-name variants models produce.
SARVAM_RESPONSE_FORMAT = os.environ.get("SARVAM_RESPONSE_FORMAT", "json_object").strip().lower()
SARVAM_TIMEOUT_SECONDS = _env_int("SARVAM_TIMEOUT_SECONDS", 90)
SARVAM_MAX_TOKENS = _env_int("SARVAM_MAX_TOKENS", 4096)
SARVAM_TEMPERATURE = float(os.environ.get("SARVAM_TEMPERATURE", "0.2"))

# Reasoning is ON by default in the Sarvam API and its tokens are billed as
# completion tokens. Measured against the live API, `reasoning_effort="low"`
# consumed the entire 3000-token budget on a real code question and returned
# empty content (finish_reason="length"), while disabling it produced a
# complete structured answer in ~240 tokens. For a latency-sensitive
# explanation tool, reasoning is therefore OFF unless explicitly enabled.
#
# To turn it on, set SARVAM_REASONING_EFFORT to low/high/max AND raise
# SARVAM_MAX_TOKENS well above the reasoning budget (e.g. 8000+), otherwise
# the visible answer will be squeezed out.
_reasoning = os.environ.get("SARVAM_REASONING_EFFORT", "").strip().lower()
SARVAM_REASONING_EFFORT = _reasoning if _reasoning in {"low", "high", "max"} else None

# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
# Sessions are server-side: the cookie carries a random token and the database
# stores only its SHA-256 hash.
SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "codesathi_session")
SESSION_TTL_DAYS = _env_int("SESSION_TTL_DAYS", 30)
OAUTH_STATE_COOKIE = "codesathi_oauth_state"
OAUTH_STATE_TTL_SECONDS = 600

# A cookie marked Secure is not sent over plain HTTP, so it must be off for
# local development and on for any real deployment. Vercel sets VERCEL=1.
COOKIE_SECURE = _env_bool("COOKIE_SECURE", bool(os.environ.get("VERCEL")) or
                          os.environ.get("FLASK_DEBUG", "1") != "1")

# Google sign-in. Optional: the app runs fine without it, and the endpoint
# reports that it is unavailable rather than failing obscurely.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()

# Minimum password length enforced at signup.
MIN_PASSWORD_LENGTH = _env_int("MIN_PASSWORD_LENGTH", 8)

# --------------------------------------------------------------------------
# Storage limits for the serverless profile
# --------------------------------------------------------------------------
# Vercel caps a serverless request body at ~4.5 MB, so archives are extracted
# in the browser and uploaded in batches. These bound what a project may hold.
MAX_STORED_BYTES = _env_int("MAX_STORED_BYTES", 12 * 1024 * 1024)   # total text stored
UPLOAD_BATCH_FILES = _env_int("UPLOAD_BATCH_FILES", 150)
UPLOAD_BATCH_BYTES = _env_int("UPLOAD_BATCH_BYTES", 3 * 1024 * 1024)

# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------
FRONTEND_ORIGINS = _env_list(
    "FRONTEND_ORIGINS",
    ["http://localhost:5173", "http://127.0.0.1:5173"],
)
RATE_LIMIT_PER_MINUTE = _env_int("RATE_LIMIT_PER_MINUTE", 30)
# Sign-in and sign-up get a much tighter budget than ordinary reads,
# so credentials cannot be brute-forced at request speed.
AUTH_RATE_LIMIT_PER_MINUTE = _env_int("AUTH_RATE_LIMIT_PER_MINUTE", 10)
PROJECT_TTL_SECONDS = _env_int("PROJECT_TTL_SECONDS", 60 * 60 * 6)
MAX_PROJECTS = _env_int("MAX_PROJECTS", 40)
TEMP_ROOT = os.environ.get("CODESATHI_TEMP_ROOT", "").strip() or None

SUPPORTED_LANGUAGES = {
    "te-IN": "Telugu",
    "en-IN": "English",
    "hi-IN": "Hindi",
    "ta-IN": "Tamil",
}


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the effective configuration."""

    max_upload_bytes: int = MAX_UPLOAD_BYTES
    max_extracted_bytes: int = MAX_EXTRACTED_BYTES
    max_archive_files: int = MAX_ARCHIVE_FILES
    max_file_bytes: int = MAX_FILE_BYTES
    max_compression_ratio: int = MAX_COMPRESSION_RATIO
    context_char_budget: int = CONTEXT_CHAR_BUDGET
    max_snippets: int = MAX_SNIPPETS
    frontend_origins: list[str] = field(default_factory=lambda: list(FRONTEND_ORIGINS))

    @property
    def sarvam_configured(self) -> bool:
        return bool(SARVAM_API_KEY)


settings = Settings()
