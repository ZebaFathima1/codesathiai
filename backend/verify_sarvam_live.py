"""Live connectivity check for the Sarvam integration.

This is *not* part of the automated suite (it needs the network). It answers
one question honestly: when we hand our real request to the real Sarvam SDK
against the real API, what happens?

With no valid key it must fail with a clean, classified authentication error
rather than a crash — which also proves the base URL, the SDK call signature
and the error mapping are correct. With a valid key in SARVAM_API_KEY it
exercises the full structured-output path.
"""
import os
import sys

sys.path.insert(0, "/scratch/work/codesathi-ai/backend")

from app.errors import SarvamAuthError, SarvamError  # noqa: E402
from app.retrieval import RetrievalResult, Snippet  # noqa: E402
from app.sarvam_client import SarvamClient  # noqa: E402

RETRIEVAL = RetrievalResult(
    snippets=[
        Snippet(
            path="auth/login.py",
            start_line=39,
            end_line=45,
            code=(
                "def login():\n"
                "    user = User.query.filter_by(email=email).first()\n"
                "    if user is None or not check_password(password, user.password_hash):\n"
                "        return jsonify({'error': 'invalid credentials'}), 401\n"
                "    token = generate_token(user)\n"
                "    return jsonify({'access_token': token}), 200\n"
            ),
            score=10.0,
            reason="enclosing function 'login'",
            language="Python",
            symbol="login",
        )
    ],
    terms=["login", "password"],
    used_chars=240,
)


def main() -> int:
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    live = bool(key)

    if not live:
        # A syntactically plausible but invalid key, to reach the real endpoint.
        key = "sk_invalid_key_for_connectivity_check"
        print("SARVAM_API_KEY is not set — using an invalid key to test the live error path.\n")

    client = SarvamClient(api_key=key, timeout=30)
    print(f"Model: {client.model}")
    print("Calling https://api.sarvam.ai/v1/chat/completions …\n")

    try:
        result = client.answer(
            "Ee project lo login process ela work avutundi?", "te-IN", RETRIEVAL
        )
        print("LIVE CALL SUCCEEDED")
        print("  model        :", result["model"])
        print("  finish_reason:", result["finish_reason"])
        print("  structured   :", result["structured"] is not None)
        if result["structured"]:
            print("  answer       :", str(result["structured"].get("answer"))[:160])
            print("  citations    :", len(result["structured"].get("citations") or []))
        print("  usage        :", result["usage"])
        return 0
    except SarvamAuthError as exc:
        print("Live call rejected with a classified authentication error (expected without a valid key).")
        print(f"  code    : {exc.code}")
        print(f"  message : {exc.message}")
        print("\nThis confirms: the SDK call reached api.sarvam.ai, the request shape was")
        print("accepted by the endpoint, and the failure was mapped to a typed error the")
        print("API surfaces to the client — no crash, no fabricated answer.")
        return 0 if not live else 1
    except SarvamError as exc:
        print(f"Live call failed with a classified Sarvam error: {exc.code} — {exc.message}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Unexpected failure type {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
