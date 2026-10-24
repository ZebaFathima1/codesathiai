"""Typed application errors and their HTTP representations.

Every failure the API can produce has a stable ``code`` so the frontend can
branch on it without string matching.
"""
from __future__ import annotations


class CodeSathiError(Exception):
    """Base class for all handled application errors."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None,
                 status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict:
        payload = {"error": self.message, "code": self.code}
        if self.details:
            payload["details"] = self.details
        return payload


class UploadError(CodeSathiError):
    """The uploaded archive was rejected."""

    status_code = 400
    code = "upload_rejected"


class NotFoundError(CodeSathiError):
    status_code = 404
    code = "not_found"


class ValidationError(CodeSathiError):
    status_code = 400
    code = "invalid_request"


class SarvamError(CodeSathiError):
    """Base for upstream Sarvam failures."""

    status_code = 502
    code = "sarvam_error"


class SarvamNotConfigured(SarvamError):
    status_code = 503
    code = "sarvam_not_configured"


class SarvamAuthError(SarvamError):
    status_code = 502
    code = "sarvam_auth_failed"


class SarvamRateLimited(SarvamError):
    status_code = 429
    code = "sarvam_rate_limited"


class SarvamTimeout(SarvamError):
    status_code = 504
    code = "sarvam_timeout"


class SarvamQuotaExhausted(SarvamError):
    status_code = 402
    code = "sarvam_quota_exhausted"


class SarvamBadResponse(SarvamError):
    status_code = 502
    code = "sarvam_bad_response"


class RateLimited(CodeSathiError):
    status_code = 429
    code = "rate_limited"


class AuthError(CodeSathiError):
    """Authentication or authorization failure."""

    status_code = 401
    code = "not_authenticated"


class ForbiddenError(CodeSathiError):
    """Authenticated, but not allowed to touch this resource."""

    status_code = 403
    code = "forbidden"


class ConflictError(CodeSathiError):
    """The request conflicts with existing state, e.g. a duplicate email."""

    status_code = 409
    code = "conflict"
