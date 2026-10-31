"""Twilio SMS adapter (I06): sends a text and maps Twilio's status callbacks. DEC-002, DEC-107.

Nothing Twilio-specific leaves this module. Callers see the port's types: SendReceipt,
TransientSendError, SendFailedError and DeliveryUpdate. The message id and the Twilio sid are
logged; the number, the body and the token are never logged or put in an error.
"""

import logging
import re
from collections.abc import Mapping
from typing import Final

import httpx

from diucs.application.ports.outbound.identity import normalise_uk_mobile
from diucs.application.ports.outbound.messaging import (
    DeliveryUpdate,
    SendFailedError,
    SendReceipt,
    TransientSendError,
)
from diucs.domain.errors import ValidationFailed

_log = logging.getLogger(__name__)

# httpx logs every request URL at INFO, and the Twilio URL carries the account SID (DEC-107 item 8).
# This is process-wide; the O01 logging configuration must hold the same levels (follow-up).
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

_MESSAGES_URL: Final = "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
_ACCEPTED: Final = 201

# Twilio error codes that refuse one message for good: an invalid, blocked or unsubscribed number.
_PERMANENT_REFUSALS: Final = frozenset({21211, 21614, 21610})

_SEPARATORS: Final = re.compile(r"[ \-().]")
# A bare international form (447700900123): a 44 and ten digits. No UK national number starts 44.
_BARE_INTERNATIONAL: Final = re.compile(r"44[0-9]{10}")

# Twilio's message statuses, mapped to the statuses of DELIVERY_STATUSES. sending is not yet with
# the carrier, so it is still queued; undelivered is a failure to deliver.
_STATUS_MAP: Final[Mapping[str, str]] = {
    "queued": "queued",
    "sending": "queued",
    "sent": "sent",
    "delivered": "delivered",
    "undelivered": "failed",
    "failed": "failed",
}


def to_e164_uk(number: str) -> str:
    """Return a UK mobile number in E.164 form ("+447700900123").

    The rule is the identity port's (normalise_uk_mobile); this adds only the bare 44 form.
    Landlines and any other shape raise ValueError. The message never includes the number.
    """
    compact = _SEPARATORS.sub("", number)
    if _BARE_INTERNATIONAL.fullmatch(compact):
        compact = "0" + compact[2:]
    try:
        national = normalise_uk_mobile(compact)
    except ValidationFailed:
        raise ValueError("not a UK mobile number") from None
    return "+44" + national[1:]


def parse_status_callback(form: Mapping[str, str]) -> DeliveryUpdate:
    """Map one Twilio status callback (form fields MessageSid, MessageStatus, ErrorCode)."""
    sid = form.get("MessageSid")
    raw_status = form.get("MessageStatus")
    if not sid or raw_status is None:
        raise ValueError("status callback has no MessageSid or MessageStatus")
    status = _STATUS_MAP.get(raw_status)
    if status is None:
        raise ValueError("status callback has an unknown MessageStatus")
    return DeliveryUpdate(sid, status, form.get("ErrorCode") or None)


def _provider_code(response: httpx.Response) -> int | None:
    """The Twilio error code of a refusal, or None. The body is parsed, never logged."""
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, int) else None


class TwilioSms:
    """SmsSender over the Twilio Messages API (DEC-002). The client is injected; no SDK."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        account_sid: str,
        auth_token: str,
        from_number: str,
        status_callback_url: str,
    ) -> None:
        self._client = client
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._status_callback_url = status_callback_url

    async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
        if not text.strip():
            raise ValueError("text is empty")
        recipient = to_e164_uk(to)
        form = {
            "To": recipient,
            "From": self._from_number,
            "Body": text,
            "StatusCallback": self._status_callback_url,
        }
        url = _MESSAGES_URL.format(account_sid=self._account_sid)
        try:
            response = await self._client.post(
                url, data=form, auth=(self._account_sid, self._auth_token)
            )
        except httpx.TransportError:
            _log.warning("sms not sent, retry: message_id=%s", message_id)
            raise TransientSendError("the provider could not be reached") from None

        status = response.status_code
        if status == _ACCEPTED:
            sid = _accepted_sid(response)
            _log.info("sms accepted: message_id=%s sid=%s", message_id, sid)
            return SendReceipt(sid, True)
        if status == 429 or status >= 500:
            _log.warning("sms not sent, retry: message_id=%s status=%s", message_id, status)
            raise TransientSendError(f"the provider answered {status}")
        code = _provider_code(response)
        if 400 <= status < 500 and code in _PERMANENT_REFUSALS:
            _log.warning("sms refused: message_id=%s code=%s", message_id, code)
            return SendReceipt("", False)
        _log.error("sms send failed: message_id=%s status=%s code=%s", message_id, status, code)
        raise SendFailedError(f"the provider answered {status} with code {code}")


def _accepted_sid(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    sid = body.get("sid") if isinstance(body, dict) else None
    if not isinstance(sid, str) or not sid:
        raise SendFailedError("the provider accepted a message but gave no sid")
    return sid
