"""Sarvam AI chat-completion integration.

Verified against the official documentation and the installed ``sarvamai``
SDK (v0.1.x):

* ``SarvamAI(api_subscription_key=...)``
* ``client.chat.completions(model=..., messages=..., temperature=...,
  max_tokens=..., reasoning_effort=..., response_format=...)``
* the model is ``sarvam-105b`` (128K context, flagship reasoning/coding model)
* ``response_format={"type": "json_schema", "json_schema": {...}}`` returns a
  JSON string in ``choices[0].message.content``

The client is injectable so the test-suite can exercise every error path with
a stub. In production the real SDK client is used and the API key is read
from the environment — it is never logged, echoed or returned to the client.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from . import config
from .errors import (
    SarvamAuthError,
    SarvamBadResponse,
    SarvamError,
    SarvamNotConfigured,
    SarvamQuotaExhausted,
    SarvamRateLimited,
    SarvamTimeout,
)
from .prompts import ANSWER_SCHEMA, build_messages
from .retrieval import RetrievalResult

log = logging.getLogger(__name__)

# Appended to the user turn when the first reply could not be parsed. Measured
# live: the failure mode is the model writing a raw double quote inside a JSON
# string (e.g. app.config["DATABASE_URL"]), which invalidates the reply and
# leaves the model emitting whitespace until it hits the token cap.
_CORRECTION = (
    "IMPORTANT: your previous reply was not valid JSON and could not be read. "
    "Reply again with ONLY a valid JSON object, and follow these rules exactly: "
    "never write a double-quote character inside a string value — use backticks "
    "for code and single quotes for anything that must be quoted, so write "
    "app.config['DATABASE_URL'] and never app.config[\"DATABASE_URL\"]; "
    "do not include code text in citations, only path and line numbers; "
    "keep every field short."
)


def _default_client_factory(api_key: str, timeout: float):
    """Build a real SarvamAI SDK client."""
    from sarvamai import SarvamAI

    return SarvamAI(api_subscription_key=api_key, timeout=timeout)


def _classify_error(exc: Exception) -> SarvamError:
    """Map an SDK/transport exception onto a typed application error."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)

    if name in {"UnauthorizedError", "ForbiddenError"} or status in (401, 403):
        return SarvamAuthError(
            "Sarvam rejected the API key. Check that SARVAM_API_KEY is valid "
            "and has access to this model."
        )
    if name == "PaymentRequiredError" or status == 402:
        return SarvamQuotaExhausted(
            "The Sarvam account has no remaining quota or credits."
        )
    if name == "TooManyRequestsError" or status == 429:
        return SarvamRateLimited(
            "Sarvam is rate-limiting requests right now. Please retry shortly."
        )
    if name in {"GatewayTimeoutError"} or status == 504:
        return SarvamTimeout("The Sarvam request timed out. Please try again.")
    if name in {"ServiceUnavailableError", "InternalServerError"} or (status and status >= 500):
        return SarvamError("Sarvam returned a server error. Please retry.", status_code=502)
    if name in {"BadRequestError", "UnprocessableEntityError"} or status == 400:
        return SarvamBadResponse(
            "Sarvam rejected the request as invalid. This usually means the "
            "retrieved context was too large; try a more specific question."
        )
    if isinstance(exc, (TimeoutError,)) or "timeout" in name.lower():
        return SarvamTimeout("The Sarvam request timed out. Please try again.")

    return SarvamError(f"Sarvam request failed ({name}). Please retry.")


def _repair_truncated_json(text: str) -> dict | None:
    """Salvage a JSON object whose tail was cut off by the token limit.

    Verified against the live API: a thorough answer can exceed the token
    budget and arrive as valid JSON that simply stops mid-object. Discarding
    it would throw away a perfectly good explanation, so instead we cut back
    to the last complete token, close any open brackets, and keep the result
    only if it still carries a usable ``answer``.
    """
    stack: list[str] = []
    in_str = False
    esc = False
    last_complete = 0

    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                last_complete = i + 1
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
            last_complete = i + 1
        elif ch in "}]":
            if stack:
                stack.pop()
            last_complete = i + 1
        elif ch.isalnum() or ch in ".-+":
            last_complete = i + 1

    head = text[:last_complete].rstrip()
    while head and head[-1] in ",:":
        head = head[:-1].rstrip()
    if not head:
        return None

    candidate = head + "".join(reversed(stack))
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    # Only trust a repair that still produced a real answer.
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    return parsed


def _clean_step_title(title: str) -> str:
    """Drop a title that is only a number or a bullet.

    Observed live: the model sometimes returns `{"title": "1", "detail": ...}`,
    which the UI renders as "1. 1". The list is already numbered, so a numeric
    title is redundant rather than informative.
    """
    stripped = title.strip().strip(".)-•*")
    if not stripped or stripped.isdigit() or len(stripped) == 1:
        return ""
    return title.strip()[:120]


def _first_key(data: dict, names: tuple[str, ...], default: Any = None) -> Any:
    """Return the first present, non-empty value among ``names``."""
    for name in names:
        if name in data:
            value = data[name]
            if value not in (None, "", [], {}):
                return value
    return default


_ANSWER_KEYS = ("answer", "direct_answer", "summary", "short_answer", "explanation")
_STEP_KEYS = ("steps", "step_by_step", "explanation_steps", "walkthrough", "flow")
_KEY_FILE_KEYS = ("key_files", "files", "relevant_files", "important_files", "file_references")
_CITATION_KEYS = ("citations", "evidence", "references", "sources", "code_references")
_UNCERTAINTY_KEYS = ("uncertainty", "caveats", "limitations", "missing_evidence", "notes")
_FOLLOWUP_KEYS = ("followups", "follow_ups", "suggested_questions", "next_questions", "follow_up_questions")


def normalize_structured(parsed: dict | None) -> dict | None:
    """Map the model's JSON onto our canonical field names.

    Verified against the live API: without constrained decoding the model
    usually returns our exact keys, but it can also emit `short_answer`,
    `walkthrough`, `evidence`, or `follow_ups`. Rather than reject a good
    answer over a key name, we normalise the shapes we have actually seen.
    """
    if not isinstance(parsed, dict):
        return None

    answer = _first_key(parsed, _ANSWER_KEYS)
    if not isinstance(answer, str) or not answer.strip():
        return None

    raw_steps = _first_key(parsed, _STEP_KEYS, [])
    steps: list[dict] = []
    if isinstance(raw_steps, list):
        for item in raw_steps:
            if isinstance(item, dict):
                title = _first_key(item, ("title", "step", "name", "heading"), "")
                detail = _first_key(item, ("detail", "description", "text", "body", "explanation"), "")
                title = _clean_step_title(str(title))
                if title or detail:
                    steps.append({"title": title, "detail": str(detail)})
            elif isinstance(item, str) and item.strip():
                steps.append({"title": _clean_step_title(item), "detail": ""})

    raw_files = _first_key(parsed, _KEY_FILE_KEYS, [])
    key_files: list[dict] = []
    if isinstance(raw_files, list):
        for item in raw_files:
            if isinstance(item, dict):
                path = _first_key(item, ("path", "file", "filename"), "")
                if path:
                    key_files.append({
                        "path": str(path),
                        "symbol": str(_first_key(item, ("symbol", "function", "name"), "")),
                        "role": str(_first_key(item, ("role", "purpose", "why", "description"), "")),
                    })
            elif isinstance(item, str) and item.strip():
                key_files.append({"path": item.strip(), "symbol": "", "role": ""})

    raw_citations = _first_key(parsed, _CITATION_KEYS, [])
    if isinstance(raw_citations, dict):
        raw_citations = [raw_citations]
    if not isinstance(raw_citations, list):
        raw_citations = []

    uncertainty = _first_key(parsed, _UNCERTAINTY_KEYS, "")
    if isinstance(uncertainty, list):
        uncertainty = " ".join(str(u) for u in uncertainty)

    raw_followups = _first_key(parsed, _FOLLOWUP_KEYS, [])
    followups = [str(f) for f in raw_followups if isinstance(f, str)] if isinstance(raw_followups, list) else []

    return {
        "answer": answer.strip(),
        "steps": steps,
        "key_files": key_files,
        "citations": raw_citations,
        "uncertainty": str(uncertainty or "").strip(),
        "followups": followups,
    }


def _escape_inner_quotes(text: str, aggressive: bool = False) -> str:
    """Escape quote characters the model left unescaped inside strings.

    Observed live: explaining a line of code, the model wrote
    `"answer": "... app.config["DATABASE_URL"] ..."` — the quotes around the
    key were not escaped, so the JSON was invalid and the whole answer was
    lost.

    A quote inside a string is normally a closing quote when the next
    significant character is a JSON separator (`:`, `,`, `}` or `]`). That
    rule handles valid JSON exactly, so this never alters a well-formed reply.

    The ambiguous case is a quote followed by `]` or `}` *inside* a string of
    code — `app.config["DATABASE_URL"]`. In ``aggressive`` mode those are
    treated as inner quotes too. Aggressive mode breaks genuinely valid JSON
    such as ``{"a": "b"}``, so it is only ever tried after the safe pass has
    already failed to parse.
    """
    closers = ",:}" if aggressive else ",:}]"

    out: list[str] = []
    in_str = False
    escaped = False
    index = 0
    length = len(text)

    while index < length:
        ch = text[index]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            index += 1
            continue

        if escaped:
            out.append(ch)
            escaped = False
            index += 1
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            index += 1
            continue
        if ch == '"':
            look = index + 1
            while look < length and text[look] in " \t\r\n":
                look += 1
            if look >= length or text[look] in closers:
                out.append(ch)
                in_str = False
            else:
                out.append('\\"')
            index += 1
            continue
        out.append(ch)
        index += 1

    return "".join(out)


def _extract_json(content: str) -> dict | None:
    """Parse a JSON object out of the model's content, tolerating fences."""
    if not content:
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.strip("`")
        text = text.lstrip("json").strip()

    start, end = text.find("{"), text.rfind("}")
    candidates = [text]
    if 0 <= start < end:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        # Retry after repairing unescaped inner quotes — safe pass first,
        # then the aggressive pass that also escapes quotes before brackets.
        for aggressive in (False, True):
            try:
                parsed = json.loads(_escape_inner_quotes(candidate, aggressive=aggressive))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    # Last resort: the reply was cut off mid-object by the token budget.
    if start >= 0:
        fragment = text[start:]
        for aggressive in (False, True):
            repaired = _repair_truncated_json(
                _escape_inner_quotes(fragment, aggressive=aggressive)
            )
            if repaired is not None:
                return repaired
    return None


class SarvamClient:
    """Thin, testable wrapper around the Sarvam chat-completion API."""

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: float | None = None,
                 client_factory: Callable[[str, float], Any] | None = None):
        self.api_key = api_key if api_key is not None else config.SARVAM_API_KEY
        self.model = model or config.SARVAM_MODEL
        self.timeout = timeout if timeout is not None else config.SARVAM_TIMEOUT_SECONDS
        self._factory = client_factory or _default_client_factory
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            if not self.configured:
                raise SarvamNotConfigured(
                    "Sarvam is not configured. Set SARVAM_API_KEY in the backend "
                    "environment and restart the server."
                )
            self._client = self._factory(self.api_key, self.timeout)
        return self._client

    @staticmethod
    def _response_format() -> dict:
        """Build the response_format parameter from configuration.

        Defaults to JSON mode. `json_schema` is available via
        SARVAM_RESPONSE_FORMAT but is not the default because it was measured
        to make the model pad the reply and run to the token cap.
        """
        mode = config.SARVAM_RESPONSE_FORMAT
        if mode == "json_schema":
            return {"type": "json_schema", "json_schema": ANSWER_SCHEMA}
        if mode == "text":
            return {"type": "text"}
        return {"type": "json_object"}

    def _request(self, messages: list[dict]):
        """Issue one chat completion, classifying any transport failure."""
        try:
            return self._get_client().chat.completions(
                model=self.model,
                messages=messages,
                temperature=config.SARVAM_TEMPERATURE,
                max_tokens=config.SARVAM_MAX_TOKENS,
                reasoning_effort=config.SARVAM_REASONING_EFFORT,
                response_format=self._response_format(),
            )
        except SarvamError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            log.warning("Sarvam call failed: %s", type(exc).__name__)
            raise _classify_error(exc) from exc

    @staticmethod
    def _read(response) -> tuple[str, str | None]:
        """Pull the content and finish reason out of a completion."""
        try:
            choice = response.choices[0]
            return choice.message.content or "", getattr(choice, "finish_reason", None)
        except (AttributeError, IndexError, TypeError) as exc:
            raise SarvamBadResponse("Sarvam returned an unexpected response shape.") from exc

    def answer(self, question: str, language: str, retrieval: RetrievalResult,
               history: list[dict] | None = None) -> dict:
        """Ask Sarvam to explain the retrieved code and return a parsed answer.

        Returns a dict with the raw text, the parsed structured answer (if the
        model honoured the schema), and the model name used.
        """
        if not self.configured:
            raise SarvamNotConfigured(
                "Sarvam is not configured. Set SARVAM_API_KEY in the backend "
                "environment and restart the server."
            )

        messages = build_messages(question, language, retrieval, history)

        # Two attempts at most. Measured against the live API, roughly one in
        # four replies to a code-heavy question contained a raw double quote
        # inside a JSON string; the model then stalled and ran to the token
        # cap. A single corrective retry recovers those, and costs nothing on
        # the (majority) of replies that are already well formed.
        response = self._request(messages)
        content, finish_reason = self._read(response)
        structured = normalize_structured(_extract_json(content))
        truncated = finish_reason == "length"

        if structured is None or truncated:
            log.info(
                "Retrying once: structured=%s truncated=%s",
                structured is not None, truncated,
            )
            retry_messages = messages[:-1] + [{
                "role": "user",
                "content": messages[-1]["content"] + "\n\n" + _CORRECTION,
            }]
            retry = self._request(retry_messages)
            retry_content, retry_finish = self._read(retry)
            retry_structured = normalize_structured(_extract_json(retry_content))
            # Keep the retry only if it is actually better.
            if retry_structured is not None and not (retry_finish == "length" and structured is None):
                response, content, finish_reason = retry, retry_content, retry_finish
                structured, truncated = retry_structured, retry_finish == "length"

        if structured is None and not content.strip():
            if finish_reason == "length":
                raise SarvamBadResponse(
                    "Sarvam's reply was cut off before any answer was produced "
                    "(token budget exhausted). Try a shorter question or raise "
                    "SARVAM_MAX_TOKENS."
                )
            raise SarvamBadResponse("Sarvam returned an empty answer.")

        usage = None
        try:
            u = getattr(response, "usage", None)
            if u is not None:
                usage = {
                    "prompt_tokens": getattr(u, "prompt_tokens", None),
                    "completion_tokens": getattr(u, "completion_tokens", None),
                    "total_tokens": getattr(u, "total_tokens", None),
                }
        except Exception:  # pragma: no cover - usage is optional metadata
            usage = None

        return {
            "model": getattr(response, "model", self.model),
            "finish_reason": finish_reason,
            "raw_text": content,
            "structured": structured,
            "usage": usage,
            # True when the model ran out of token budget. The answer may be
            # cut short, so the caller reports that to the user.
            "truncated": finish_reason == "length",
        }
