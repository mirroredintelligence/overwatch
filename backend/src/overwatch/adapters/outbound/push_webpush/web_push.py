"""Web Push sender (I14): one push to one installed app, through pywebpush.

The VAPID private key is platform-wide (DEC-340): one key pair for the platform, read from the
secret store at start-up, so a change of key forces every app to subscribe again. Its subject is
the operations `mailto:` from settings. The key and the subscription are secrets: neither is logged,
and no error text repeats them, the endpoint, the keys or the provider's body (WebPushException's
own text includes the response body, so it is never copied into a message).

pywebpush is synchronous, so each send runs in a worker thread (asyncio.to_thread).
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any, Final

from pywebpush import WebPushException, webpush

from diucs.application.ports.outbound.messaging import (
    PUSH_GONE,
    SendFailedError,
    SendReceipt,
    TransientSendError,
)
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.domain.errors import NotFound

VAPID_PRIVATE_KEY_SECRET: Final = "webpush-vapid-private-key"
"""The secret reference of the platform's VAPID private key (platform-wide, not per tenant)."""
PUSH_TTL_SECONDS: Final = 600
"""A push the device has not taken within ten minutes is dropped by the push service."""
PUSH_TIMEOUT_SECONDS: Final = 10.0
GONE: Final = PUSH_GONE
_GONE_STATUSES: Final = frozenset({404, 410})
_TRANSIENT_STATUSES: Final = frozenset({429})
_URGENCIES: Final = frozenset({"high", "normal"})

Transport = Callable[..., object]


def vapid_private_key(secrets: SecretStore) -> str:
    """The VAPID private key from the secret store. A missing key is NotFound and names no value."""
    try:
        return secrets.get(VAPID_PRIVATE_KEY_SECRET).decode("utf-8")
    except NotFound:
        raise NotFound("the web push key is not configured") from None


def configured_push_sender(secrets: SecretStore, subject: str) -> WebPushSender | None:
    """The platform's Web Push sender, or None when no VAPID key is configured. None is not an
    error: the push runner is then not started, and push messages wait on their subscription until
    a key is configured (fail closed; nothing is sent without a key)."""
    try:
        key = vapid_private_key(secrets)
    except NotFound:
        return None
    return WebPushSender(key, subject)


def _status(error: WebPushException) -> int | None:
    status: int | None = error.status_code
    return status


class WebPushSender:
    """Implements PushSender. `transport` is pywebpush's webpush by default; tests pass a fake."""

    def __init__(
        self,
        vapid_private_key: str,
        vapid_subject: str,
        *,
        transport: Transport = webpush,
    ) -> None:
        if not vapid_private_key or not vapid_subject.startswith("mailto:"):
            raise ValueError("web push needs a VAPID key and a mailto subject")
        self._key = vapid_private_key
        self._claims: dict[str, str | int] = {"sub": vapid_subject}
        self._transport = transport

    async def send(
        self,
        subscription: dict[str, Any],
        title: str,
        body: str,
        url: str,
        *,
        urgency: str = "normal",
    ) -> SendReceipt:
        if urgency not in _URGENCIES:
            raise ValueError("urgency is high or normal")
        data = _payload(title, body, url)
        try:
            await asyncio.to_thread(
                self._transport,
                subscription_info=subscription,
                data=data,
                vapid_private_key=self._key,
                vapid_claims=dict(self._claims),
                ttl=PUSH_TTL_SECONDS,
                headers={"Urgency": urgency},
                timeout=PUSH_TIMEOUT_SECONDS,
            )
        except WebPushException as error:
            status = _status(error)
            if status in _GONE_STATUSES:
                return SendReceipt(provider_message_id="", accepted=False, reason=GONE)
            if status is None or status in _TRANSIENT_STATUSES or status >= 500:
                raise TransientSendError() from None
            raise SendFailedError(f"web push refused with status {status}") from None
        except OSError:
            # A connection, a DNS or a timeout failure: the push service may answer on retry.
            raise TransientSendError() from None
        return SendReceipt(provider_message_id="", accepted=True)


def _payload(title: str, body: str, url: str) -> str:
    return json.dumps(
        {"title": title, "body": body, "url": url},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
