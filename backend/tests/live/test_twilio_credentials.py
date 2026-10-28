"""Live check of the Twilio credentials stored as a network secret. Read-only; sends nothing.

The credentials are network secrets on the cloud environment. The agent proxy attaches them to
requests for the listed host, so this test sends NO credentials itself and the session never
sees a secret value. A 200 response proves the stored credentials work.

Runs only when DIUCS_LIVE_TWILIO=1 is set, so normal test runs never reach the network.
"""

import json
import os
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("DIUCS_LIVE_TWILIO") != "1",
    reason="live Twilio check: set DIUCS_LIVE_TWILIO=1 to run it",
)

TWILIO_ACCOUNTS = "https://api.twilio.com/2010-04-01/Accounts.json"


def _get_without_credentials(url: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, {}


def test_stored_twilio_credentials_authenticate() -> None:
    status, body = _get_without_credentials(TWILIO_ACCOUNTS)
    assert status == 200, (
        f"Twilio answered HTTP {status}. The network secret for api.twilio.com is missing, "
        "shows 'Not sent' in the environment's list, or its credentials are wrong."
    )


def test_the_account_is_active() -> None:
    status, body = _get_without_credentials(TWILIO_ACCOUNTS)
    assert status == 200, f"Twilio answered HTTP {status}"
    accounts = body.get("accounts")
    assert isinstance(accounts, list) and accounts, "Twilio returned no account"
    assert accounts[0].get("status") == "active", "the Twilio account is not active"
