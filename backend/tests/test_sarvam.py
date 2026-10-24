"""Tests for the Sarvam integration layer.

The SDK is never contacted here: a stub client is injected so every error
path and the structured-output parser can be exercised deterministically.
"""
import pytest

from app import config
from app.errors import (
    SarvamAuthError,
    SarvamBadResponse,
    SarvamNotConfigured,
    SarvamQuotaExhausted,
    SarvamRateLimited,
    SarvamTimeout,
)
from app.retrieval import RetrievalResult, Snippet
from app.sarvam_client import (
    SarvamClient,
    _classify_error,
    _escape_inner_quotes,
    _extract_json,
    _repair_truncated_json,
    normalize_structured,
)


class FakeError(Exception):
    def __init__(self, name, status_code=None):
        super().__init__(name)
        self.status_code = status_code


# Build exception classes whose *class names* match the SDK's error classes.
UnauthorizedError = type("UnauthorizedError", (Exception,), {})
TooManyRequestsError = type("TooManyRequestsError", (Exception,), {})
PaymentRequiredError = type("PaymentRequiredError", (Exception,), {})
GatewayTimeoutError = type("GatewayTimeoutError", (Exception,), {})
InternalServerError = type("InternalServerError", (Exception,), {})


class _Message:
    def __init__(self, content):
        self.content = content
        self.role = "assistant"


class _Choice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _Message(content)
        self.finish_reason = finish_reason
        self.index = 0


class _Usage:
    prompt_tokens = 10
    completion_tokens = 20
    total_tokens = 30


class _Response:
    def __init__(self, content, finish_reason="stop", model="sarvam-105b"):
        self.choices = [_Choice(content, finish_reason)]
        self.model = model
        self.usage = _Usage()


class _Completions:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    def __call__(self, **kwargs):
        return self.behaviour(kwargs)


class _FakeSarvam:
    def __init__(self, behaviour):
        self.chat = type("Chat", (), {"completions": _Completions(behaviour)})()


def _retrieval():
    return RetrievalResult(snippets=[
        Snippet("auth/login.py", 1, 5, "def login():\n    pass\n", 10.0, "test", "Python"),
    ], terms=["login"], used_chars=20)


def _client(behaviour):
    return SarvamClient(api_key="sk_test", client_factory=lambda k, t: _FakeSarvam(behaviour))


def test_not_configured_raises():
    client = SarvamClient(api_key="")
    with pytest.raises(SarvamNotConfigured):
        client.answer("hi", "en-IN", _retrieval())


def test_successful_structured_answer():
    payload = '{"answer": "Login checks the password.", "steps": [], "key_files": [], "citations": [], "uncertainty": "", "followups": []}'
    client = _client(lambda kwargs: _Response(payload))
    result = client.answer("How does login work?", "en-IN", _retrieval())
    assert result["structured"]["answer"].startswith("Login checks")
    assert result["model"] == "sarvam-105b"
    assert result["usage"]["total_tokens"] == 30


def test_request_uses_configured_model_and_format(monkeypatch):
    captured = {}

    def behaviour(kwargs):
        captured.update(kwargs)
        return _Response('{"answer":"x"}')

    monkeypatch.setattr(config, "SARVAM_RESPONSE_FORMAT", "json_object", raising=False)
    client = _client(behaviour)
    client.answer("q", "te-IN", _retrieval())
    assert captured["model"] == config.SARVAM_MODEL
    # JSON mode is the default: json_schema was measured to make the model pad
    # its reply and run to the token cap without ever stopping.
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["messages"][0]["role"] == "system"
    assert "Telugu" in captured["messages"][-1]["content"]


def test_json_schema_mode_is_still_available(monkeypatch):
    monkeypatch.setattr(config, "SARVAM_RESPONSE_FORMAT", "json_schema", raising=False)
    fmt = SarvamClient(api_key="sk_test")._response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"]["required"][0] == "answer"


def test_text_mode_disables_json(monkeypatch):
    monkeypatch.setattr(config, "SARVAM_RESPONSE_FORMAT", "text", raising=False)
    assert SarvamClient(api_key="sk_test")._response_format() == {"type": "text"}


def test_truncated_reply_is_flagged(monkeypatch):
    payload = '{"answer": "partial"}'

    def behaviour(_kwargs):
        return _Response(payload, finish_reason="length")

    result = _client(behaviour).answer("q", "en-IN", _retrieval())
    assert result["truncated"] is True


def test_complete_reply_is_not_flagged():
    def behaviour(_kwargs):
        return _Response('{"answer": "complete"}')

    assert _client(behaviour).answer("q", "en-IN", _retrieval())["truncated"] is False


# --------------------------------------------------------------------------
# Response normalisation and truncation repair
# --------------------------------------------------------------------------
def test_normalize_structured_accepts_alternate_key_names():
    normalized = normalize_structured({
        "short_answer": "It authenticates the user.",
        "walkthrough": ["First look up the user", {"step": "Then hash", "body": "bcrypt"}],
        "relevant_files": ["auth/login.py", {"file": "models/user.py", "function": "User"}],
        "evidence": [{"path": "auth/login.py", "lines": "39-61", "quote": "def login():"}],
        "caveats": "Only the snippets shown were available.",
        "suggested_questions": ["Where is the token verified?"],
    })
    assert normalized is not None
    assert normalized["answer"] == "It authenticates the user."
    assert normalized["steps"][0] == {"title": "First look up the user", "detail": ""}
    assert normalized["steps"][1]["title"] == "Then hash"
    assert normalized["key_files"][0]["path"] == "auth/login.py"
    assert normalized["key_files"][1]["symbol"] == "User"
    assert normalized["citations"][0]["path"] == "auth/login.py"
    assert normalized["uncertainty"].startswith("Only the snippets")
    assert normalized["followups"] == ["Where is the token verified?"]


def test_normalize_structured_requires_an_answer():
    assert normalize_structured(None) is None
    assert normalize_structured({}) is None
    assert normalize_structured({"steps": ["a"]}) is None
    assert normalize_structured({"answer": "   "}) is None


def test_normalize_structured_wraps_a_single_citation_object():
    normalized = normalize_structured({
        "answer": "ok",
        "citations": {"path": "a.py", "lines": "1-2"},
    })
    assert isinstance(normalized["citations"], list)
    assert len(normalized["citations"]) == 1


def test_repair_recovers_a_truncated_object():
    truncated = '{"answer": "Login checks the hash", "citations": [{"path": "a.py", "lines": "1-2"}'
    repaired = _repair_truncated_json(truncated)
    assert repaired is not None
    assert repaired["answer"] == "Login checks the hash"
    assert repaired["citations"][0]["path"] == "a.py"


def test_repair_rejects_a_fragment_without_an_answer():
    assert _repair_truncated_json('{"steps": [{"title": "x"') is None
    assert _repair_truncated_json("") is None


def test_extract_json_uses_repair_as_a_last_resort():
    truncated = '{"answer": "Recovered", "steps": [{"title": "one"}'
    parsed = _extract_json(truncated)
    assert parsed is not None
    assert parsed["answer"] == "Recovered"


def test_auth_error_is_classified():
    def behaviour(_kwargs):
        raise UnauthorizedError("bad key")

    with pytest.raises(SarvamAuthError):
        _client(behaviour).answer("q", "en-IN", _retrieval())


def test_rate_limit_is_classified():
    def behaviour(_kwargs):
        raise TooManyRequestsError("slow down")

    with pytest.raises(SarvamRateLimited):
        _client(behaviour).answer("q", "en-IN", _retrieval())


def test_quota_error_is_classified():
    def behaviour(_kwargs):
        raise PaymentRequiredError("no credits")

    with pytest.raises(SarvamQuotaExhausted):
        _client(behaviour).answer("q", "en-IN", _retrieval())


def test_timeout_is_classified():
    def behaviour(_kwargs):
        raise GatewayTimeoutError("too slow")

    with pytest.raises(SarvamTimeout):
        _client(behaviour).answer("q", "en-IN", _retrieval())


def test_server_error_is_classified():
    def behaviour(_kwargs):
        raise InternalServerError("boom")

    with pytest.raises(Exception) as exc:
        _client(behaviour).answer("q", "en-IN", _retrieval())
    assert exc.value.code == "sarvam_error"


def test_empty_content_is_rejected():
    def behaviour(_kwargs):
        return _Response("")

    with pytest.raises(SarvamBadResponse):
        _client(behaviour).answer("q", "en-IN", _retrieval())


def test_length_finish_with_no_content_explains_token_budget():
    def behaviour(_kwargs):
        return _Response("", finish_reason="length")

    with pytest.raises(SarvamBadResponse) as exc:
        _client(behaviour).answer("q", "en-IN", _retrieval())
    assert "token budget" in str(exc.value)


def test_bad_response_shape_is_rejected():
    class Weird:
        choices = []

    def behaviour(_kwargs):
        return Weird()

    with pytest.raises(SarvamBadResponse):
        _client(behaviour).answer("q", "en-IN", _retrieval())


def test_extract_json_handles_plain_and_fenced():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert _extract_json("prefix {\"a\": 3} suffix") == {"a": 3}
    assert _extract_json("not json at all") is None
    assert _extract_json("") is None


def test_classify_error_falls_back_to_generic():
    err = _classify_error(ValueError("something odd"))
    assert err.code == "sarvam_error"


def test_classify_error_uses_status_code():
    err = _classify_error(FakeError("Mystery", status_code=401))
    assert err.code == "sarvam_auth_failed"


# --------------------------------------------------------------------------
# Regression: the model sometimes emits JSON with unescaped quotes inside a
# string value (it is writing code, e.g. app.config["DATABASE_URL"]). That
# made the whole reply unparseable and the answer was lost. Observed live.
# --------------------------------------------------------------------------
def test_unescaped_quotes_inside_a_string_are_repaired():
    broken = (
        '{"answer": "It reads app.config["DATABASE_URL"] to build the engine.", '
        '"citations": [{"path": "config/database.py", "lines": "20-20", '
        '"quote": "engine = create_engine("}]}'
    )
    parsed = _extract_json(broken)
    assert parsed is not None
    assert 'app.config["DATABASE_URL"]' in parsed["answer"]
    assert parsed["citations"][0]["path"] == "config/database.py"


def test_quote_escaping_never_alters_valid_json():
    samples = [
        '{"answer": "a \\"quoted\\" word", "steps": []}',
        '{"a": ["x", "y"]}',
        '{"answer": "x", "steps": [{"title": "t", "detail": "d"}]}',
        '{"answer": "ends with a bracket }", "steps": []}',
    ]
    for sample in samples:
        assert _escape_inner_quotes(sample) == sample, sample
        assert isinstance(_extract_json(sample), dict)


def test_aggressive_quote_repair_is_only_a_fallback():
    # Safe mode must not touch a string that legitimately ends before a bracket.
    safe = '{"a": ["x"]}'
    assert _escape_inner_quotes(safe, aggressive=False) == safe
    # Aggressive mode is allowed to differ; it only runs when safe mode failed.
    assert _extract_json(safe) == {"a": ["x"]}


# --------------------------------------------------------------------------
# Retry: a reply that fails to parse, or that ran to the token cap, is retried
# once with a corrective instruction. Observed live: ~1 in 4 code-heavy
# replies contained an unescaped double quote and stalled to the cap.
# --------------------------------------------------------------------------
class _SequencedSarvam:
    """Returns a different response on each successive call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

        class _Completions:
            def __init__(self, outer):
                self._outer = outer

            def __call__(self, **kwargs):
                self._outer.calls.append(kwargs)
                index = min(len(self._outer.calls) - 1, len(self._outer._responses) - 1)
                return self._outer._responses[index]

        self.chat = type("Chat", (), {"completions": _Completions(self)})()


def _sequenced_client(responses):
    holder = {}

    def factory(_key, _timeout):
        holder["client"] = _SequencedSarvam(responses)
        return holder["client"]

    return SarvamClient(api_key="sk_test", client_factory=factory), holder


def test_a_truncated_reply_is_retried_once_and_recovers():
    good = '{"answer": "The login function checks the password.", "citations": []}'
    client, holder = _sequenced_client([
        _Response('{"answer": "cut off here', finish_reason="length"),
        _Response(good, finish_reason="stop"),
    ])
    result = client.answer("q", "en-IN", _retrieval())
    assert len(holder["client"].calls) == 2, "must retry exactly once"
    assert result["truncated"] is False
    assert result["structured"]["answer"].startswith("The login function")


def test_a_malformed_reply_is_repaired_without_costing_a_second_call():
    # The unescaped-quote case is recoverable locally, so it must not spend a
    # second API call on a retry.
    broken = '{"answer": "It reads app.config["DATABASE_URL"]", "citations": []}'
    client, holder = _sequenced_client([_Response(broken, finish_reason="stop")])
    result = client.answer("q", "en-IN", _retrieval())
    assert len(holder["client"].calls) == 1
    assert result["structured"] is not None
    assert 'app.config["DATABASE_URL"]' in result["structured"]["answer"]


def test_unparseable_prose_is_retried_once():
    good = '{"answer": "Recovered on the retry.", "citations": []}'
    client, holder = _sequenced_client([
        _Response("This is prose, not JSON at all.", finish_reason="stop"),
        _Response(good, finish_reason="stop"),
    ])
    result = client.answer("q", "en-IN", _retrieval())
    assert len(holder["client"].calls) == 2
    assert result["structured"]["answer"] == "Recovered on the retry."


def test_the_retry_prompt_forbids_raw_double_quotes():
    good = '{"answer": "ok", "citations": []}'
    client, holder = _sequenced_client([
        _Response("not json at all", finish_reason="stop"),
        _Response(good, finish_reason="stop"),
    ])
    client.answer("q", "en-IN", _retrieval())
    retry_prompt = holder["client"].calls[1]["messages"][-1]["content"]
    assert "double-quote" in retry_prompt
    assert "not valid JSON" in retry_prompt


def test_a_good_reply_is_not_retried():
    good = '{"answer": "fine", "citations": []}'
    client, holder = _sequenced_client([_Response(good, finish_reason="stop")])
    client.answer("q", "en-IN", _retrieval())
    assert len(holder["client"].calls) == 1, "a clean reply must not cost a second call"


def test_retry_keeps_the_first_answer_if_the_retry_is_worse():
    # First reply is truncated but repairable; the retry returns nothing usable.
    first = '{"answer": "partial answer", "steps": []'
    client, holder = _sequenced_client([
        _Response(first, finish_reason="length"),
        _Response("still not json", finish_reason="stop"),
    ])
    result = client.answer("q", "en-IN", _retrieval())
    assert len(holder["client"].calls) == 2
    assert result["structured"]["answer"] == "partial answer"
    assert result["truncated"] is True


def test_when_both_attempts_fail_the_raw_text_is_returned():
    client, _ = _sequenced_client([
        _Response("garbage one", finish_reason="stop"),
        _Response("garbage two", finish_reason="stop"),
    ])
    result = client.answer("q", "en-IN", _retrieval())
    assert result["structured"] is None
    # Neither attempt parsed, so the first reply is kept rather than swapped
    # for an equally unusable one.
    assert result["raw_text"] == "garbage one"
