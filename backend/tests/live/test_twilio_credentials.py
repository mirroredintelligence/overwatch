"""Live check of the Twilio credentials in the environment. Read-only; sends nothing.

Runs only when DIUCS_LIVE_TWILIO=1 is set, so normal test runs never reach the network.
It never prints a secret value: failures name the variable and report HTTP status only.
Variable names are read as the environment settings name them, in lower case or upper case.
"""

import base64
import json
import os
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("DIUCS_LIVE_TWILIO") != "1",
    reason="live Twilio check: set DIUCS_LIVE_TWILIO=1 to run it",
)

NAMES = (
    "twilio_api_key_sid",
    "twilio_api_key_secret",
    "twilio_account_sid",
    "twilio_auth_token",
    "twilio_api_endpoint",
)


def _value(name: str) -> str:
    """Return the variable's value, trying the name as given and in upper case. Never printed."""
    for candidate in (name, name.upper()):
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    pytest.fail(f"missing environment variable: {name} (or {name.upper()})")


def _get(endpoint: str, path: str, user: str, password: str) -> tuple[int, dict[str, object]]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}{path}", headers={"Authorization": f"Basic {token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        return error.code, {}


def test_all_five_variables_are_set() -> None:
    for name in NAMES:
        _value(name)


def test_endpoint_is_https() -> None:
    assert _value("twilio_api_endpoint").startswith("https://"), (
        "twilio_api_endpoint must be an https:// URL"
    )


def test_account_sid_and_auth_token_authenticate_and_the_account_is_active() -> None:
    endpoint = _value("twilio_api_endpoint")
    account_sid = _value("twilio_account_sid")
    status, body = _get(
        endpoint,
        f"/2010-04-01/Accounts/{account_sid}.json",
        account_sid,
        _value("twilio_auth_token"),
    )
    assert status == 200, f"account SID and auth token: Twilio answered HTTP {status}"
    assert body.get("status") == "active", "the Twilio account is not active"


def test_api_key_sid_and_secret_authenticate_against_the_account() -> None:
    endpoint = _value("twilio_api_endpoint")
    account_sid = _value("twilio_account_sid")
    status, _ = _get(
        endpoint,
        f"/2010-04-01/Accounts/{account_sid}.json",
        _value("twilio_api_key_sid"),
        _value("twilio_api_key_secret"),
    )
    assert status == 200, f"API key SID and secret: Twilio answered HTTP {status}"
