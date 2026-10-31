"""Twilio Email adapter: sends an email through Twilio's own Email API (DEC-131 correction,
DEC-1130).

`POST https://comms.twilio.com/v1/Emails` with the tenant subaccount's Account SID and Auth Token,
the same credentials as its texts. The API is asynchronous: it answers 202 with an operation id,
which is the provider message id kept on the Communication; the delivery is read from the Operation
(`GET /v1/Emails/Operations/{id}`) and mapped to the statuses of a text by `map_operation`.

The sender address must be one the tenant verified in Twilio (a domain identity matching the
address domain): that is a tenant onboarding step, not something this adapter can check. An
unverified sender is refused by Twilio with a 4xx, which is a fault of the set-up and not retried.

[ASSUMED] The request body shape (`from`, `to`, `content.subject/text/html`) and the Operation
counts (`counts.delivered/sent/failed/undelivered/canceled`) follow the shape of Twilio's published
documentation as far as it could be read when this was built; twilio.com was not reachable from the
build session, so both are kept in `build_body` and `map_operation` alone, and the live check
(`backend/tests/live`) must confirm them before a real tenant sends. The status words, the 202 and
the Operation path are from the documentation.

Nothing Twilio-specific leaves this module. No address, subject, body or token is logged or put in
an error: the provider id and fixed words only.
"""

import json
import logging
import re
from collections.abc import Mapping
from typing import Any, Final

import httpx

from diucs.application.ports.outbound.messaging import (
    DeliveryUpdate,
    SendFailedError,
    SendReceipt,
    TransientSendError,
)

_log = logging.getLogger(__name__)

# httpx logs every request URL at INFO, and the Operation URL carries the operation id.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

EMAILS_URL: Final = "https://comms.twilio.com/v1/Emails"
OPERATION_URL: Final = "https://comms.twilio.com/v1/Emails/Operations/"
_ACCEPTED: Final = 202
_TIMEOUT_S: Final = 30.0

_LABEL: Final = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
# One address, no display name, no comment, no quoting: the shape a role inbox has.
_ADDRESS: Final = re.compile(rf"[A-Za-z0-9._%+-]{{1,64}}@{_LABEL}(?:\.{_LABEL})+")
_ADDRESS_MAX: Final = 254
_DISPLAY_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .'&()_-]{0,79}")
_OPERATION_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SUBJECT_MAX: Final = 200

_PENDING: Final = frozenset({"SCHEDULED", "PROCESSING"})
_KNOWN_STATUSES: Final = _PENDING | {"COMPLETED", "CANCELED"}
_COUNTS: Final = ("sent", "delivered", "undelivered", "failed", "canceled")


def _is_address(value: object) -> bool:
    return (
        type(value) is str and len(value) <= _ADDRESS_MAX and _ADDRESS.fullmatch(value) is not None
    )


def build_body(
    to: str, from_address: str, from_name: str | None, subject: str, text: str, html: str | None
) -> dict[str, Any]:
    """The JSON of one send: the sender, the one recipient and the content. [ASSUMED] shape."""
    sender: dict[str, str] = {"address": from_address}
    if from_name is not None:
        sender["name"] = from_name
    content: dict[str, str] = {"subject": subject, "text": text}
    if html is not None:
        content["html"] = html
    return {"from": sender, "to": [{"address": to}], "content": content}


def _count(counts: Mapping[str, object], name: str) -> int:
    value = counts.get(name, 0)
    if type(value) is not int or value < 0:
        raise ValueError("an operation count is not a whole number")
    return value


def map_operation(body: object) -> DeliveryUpdate:
    """Map one Operation to the delivery statuses of a text (queued, sent, delivered, failed).

    SCHEDULED and PROCESSING are queued. CANCELED is failed. A COMPLETED operation is failed when
    any email failed or was undelivered (so a lost email is never reported delivered), else
    delivered when one was, else sent when the server accepted one, else still queued. The error
    code is a fixed word. A body that cannot be read, or a status the API does not document, is a
    ValueError."""
    if not isinstance(body, Mapping):
        raise ValueError("an operation is not an object")
    operation_id = body.get("operationId")
    status = body.get("status")
    if type(operation_id) is not str or not _OPERATION_ID.fullmatch(operation_id):
        raise ValueError("an operation has no id")
    if type(status) is not str or status not in _KNOWN_STATUSES:
        raise ValueError("an operation has an unknown status")
    if status in _PENDING:
        return DeliveryUpdate(operation_id, "queued", None)
    if status == "CANCELED":
        return DeliveryUpdate(operation_id, "failed", "canceled")
    raw = body.get("counts", {})
    counts: Mapping[str, object] = raw if isinstance(raw, Mapping) else {}
    numbers = {name: _count(counts, name) for name in _COUNTS}
    if numbers["undelivered"]:
        return DeliveryUpdate(operation_id, "failed", "undelivered")
    if numbers["failed"] or numbers["canceled"]:
        return DeliveryUpdate(operation_id, "failed", "failed")
    if numbers["delivered"]:
        return DeliveryUpdate(operation_id, "delivered", None)
    if numbers["sent"]:
        return DeliveryUpdate(operation_id, "sent", None)
    return DeliveryUpdate(operation_id, "queued", None)


def _json_object(response: httpx.Response) -> Mapping[str, Any] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _error_code(response: httpx.Response) -> object:
    body = _json_object(response)
    code = None if body is None else body.get("code")
    return code if type(code) is int else None


class TwilioEmail:
    """EmailSender over Twilio's Email API. The client is injected; there is no SDK. A 429, a 5xx
    answer or a lost connection is transient (the consumer retries). Any other answer that is not
    202 is a fault of the set-up (credentials, an unverified sender) or of the request, and is not
    retried."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        account_sid: str,
        auth_token: str,
        from_address: str,
        from_display_name: str | None = None,
    ) -> None:
        if not _is_address(from_address):
            raise ValueError("the sender address is not an address")
        if from_display_name is not None and (
            type(from_display_name) is not str or _DISPLAY_NAME.fullmatch(from_display_name) is None
        ):
            raise ValueError("the sender display name is not plain text")
        self._client = client
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_address = from_address
        self._from_name = from_display_name

    def __repr__(self) -> str:
        return f"TwilioEmail(domain={self._from_address.rsplit('@', 1)[1]})"

    __str__ = __repr__

    async def send(self, to: str, subject: str, text: str, html: str | None) -> SendReceipt:
        if not _is_address(to):
            raise SendFailedError("the recipient is not an address")
        if (
            not subject.strip()
            or len(subject) > _SUBJECT_MAX
            or not subject.isprintable()
            or not text.strip()
        ):
            raise SendFailedError("the subject or the text is not usable")
        body = build_body(to, self._from_address, self._from_name, subject, text, html)
        try:
            response = await self._client.post(
                EMAILS_URL,
                content=json.dumps(body),
                headers={"Content-Type": "application/json"},
                auth=(self._account_sid, self._auth_token),
                timeout=_TIMEOUT_S,
            )
        except httpx.TransportError:
            _log.warning("email not sent, retry")
            raise TransientSendError("the provider could not be reached") from None
        status = response.status_code
        if status == _ACCEPTED:
            operation_id = _accepted_operation(response)
            _log.info("email accepted: operation=%s", operation_id)
            return SendReceipt(operation_id, True)
        if status == 429 or status >= 500:
            _log.warning("email not sent, retry: status=%s", status)
            raise TransientSendError(f"the provider answered {status}")
        code = _error_code(response)
        _log.error("email send failed: status=%s code=%s", status, code)
        raise SendFailedError(f"the provider answered {status} with code {code}")

    async def operation_update(self, operation_id: str) -> DeliveryUpdate:
        """Read one Operation and map it to the delivery statuses of a text. The update carries the
        id asked for, whatever the body says."""
        if not _OPERATION_ID.fullmatch(operation_id):
            raise ValueError("not an operation id")
        try:
            response = await self._client.get(
                OPERATION_URL + operation_id,
                auth=(self._account_sid, self._auth_token),
                timeout=_TIMEOUT_S,
            )
        except httpx.TransportError:
            raise TransientSendError("the provider could not be reached") from None
        status = response.status_code
        if status == 429 or status >= 500:
            raise TransientSendError(f"the provider answered {status}")
        if status != 200:
            raise SendFailedError(f"the provider answered {status}")
        try:
            mapped = map_operation(_json_object(response))
        except ValueError:
            raise SendFailedError("the provider's operation could not be read") from None
        return DeliveryUpdate(operation_id, mapped.status, mapped.error_code)


def _accepted_operation(response: httpx.Response) -> str:
    body = _json_object(response)
    operation_id = None if body is None else body.get("operationId")
    if type(operation_id) is not str or not _OPERATION_ID.fullmatch(operation_id):
        raise SendFailedError("the provider accepted an email but gave no operation id")
    return operation_id
