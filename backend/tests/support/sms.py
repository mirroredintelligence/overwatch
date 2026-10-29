"""Support for the Twilio webhook tests (I07).

Two tenants, each with its own Twilio subaccount, number and auth token (DEC-131), one secret store
that holds the phone-hash key and both tokens, and an independent signer: the tests compute the
signature with hmac and hashlib themselves and never call the code under test to build a request.
Every value is synthetic. 07700 900123 is the sample number of the specs, and the tokens are made
up for the tests.
"""

import base64
import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass

from httpx import AsyncClient, Response

from diucs.adapters.testing.fixed_inbound_lines import FixedInboundLines
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET
from diucs.application.ports.outbound.tenant_lines import InboundLine

PUBLIC_BASE_URL = "https://diucs.example/"
REPLY_URL = "https://diucs.example/webhooks/sms/twilio"
STATUS_URL = "https://diucs.example/webhooks/sms/twilio/status"
# The proxy in front of the app rewrites the host: the app sees this, Twilio signed the public URL.
INTERNAL_REPLY_URL = "http://internal:8000/webhooks/sms/twilio"
INTERNAL_STATUS_URL = "http://internal:8000/webhooks/sms/twilio/status"

SENDER = "07700 900123"
SENDER_E164 = "+447700900123"
UNKNOWN_SENDER_E164 = "+447700900456"
LANDLINE_E164 = "+441234567890"
REPLY_TEXT = "4"
PHONE_HASH_KEY = b"i07-test-phone-hash-key"
FORM = {"content-type": "application/x-www-form-urlencoded"}


@dataclass(frozen=True, slots=True)
class Subaccount:
    tenant_id: str
    number: str
    account_sid: str
    token_secret: str
    token: bytes


TENANT_A = Subaccount("tenant-a", "+447700900001", "AC" + "a" * 32, "twilio/tenant-a", b"token-a")
TENANT_B = Subaccount("tenant-b", "+447700900002", "AC" + "b" * 32, "twilio/tenant-b", b"token-b")


def secret_store() -> FixedSecretStore:
    return FixedSecretStore(
        {
            PHONE_HASH_SECRET: PHONE_HASH_KEY,
            TENANT_A.token_secret: TENANT_A.token,
            TENANT_B.token_secret: TENANT_B.token,
        }
    )


def inbound_lines() -> FixedInboundLines:
    return FixedInboundLines(
        [
            (
                account.number,
                account.account_sid,
                InboundLine(account.tenant_id, account.token_secret),
            )
            for account in (TENANT_A, TENANT_B)
        ]
    )


def phone_hash(number: str) -> str:
    """The keyed hash of a UK mobile number, computed here with hmac, not by HmacPhoneHasher."""
    national = number.replace(" ", "")
    national = "0" + national[3:] if national.startswith("+44") else national
    return hmac.new(PHONE_HASH_KEY, national.encode("ascii"), hashlib.sha256).hexdigest()


def sign(url: str, params: Mapping[str, str], token: bytes) -> str:
    """Twilio's signature: base64(HMAC-SHA1(token, url + each name and value, sorted by name))."""
    data = url + "".join(name + params[name] for name in sorted(params))
    return base64.b64encode(hmac.new(token, data.encode("utf-8"), hashlib.sha1).digest()).decode()


def reply_params(
    account: Subaccount = TENANT_A,
    *,
    sid: str = "SM" + "1" * 32,
    sender: str = SENDER_E164,
    text: str = REPLY_TEXT,
) -> dict[str, str]:
    return {
        "AccountSid": account.account_sid,
        "MessageSid": sid,
        "From": sender,
        "To": account.number,
        "Body": text,
        "NumMedia": "0",
    }


def status_params(
    account: Subaccount = TENANT_A,
    *,
    sid: str = "SM1",
    status: str = "delivered",
    recipient: str = SENDER_E164,
) -> dict[str, str]:
    return {
        "AccountSid": account.account_sid,
        "MessageSid": sid,
        "MessageStatus": status,
        "From": account.number,
        "To": recipient,
    }


async def post_signed(
    client: AsyncClient,
    params: Mapping[str, str],
    *,
    token: bytes = TENANT_A.token,
    signed_url: str = REPLY_URL,
    send_to: str = INTERNAL_REPLY_URL,
    headers: Mapping[str, str] | None = None,
) -> Response:
    """POST a form signed over `signed_url` (what Twilio saw) to `send_to` (what the app sees)."""
    all_headers = {"X-Twilio-Signature": sign(signed_url, params, token), **(headers or {})}
    return await client.post(send_to, data=dict(params), headers=all_headers)
