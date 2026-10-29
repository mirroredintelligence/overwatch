"""Web Push adapter (I14): the payload, the headers, and how each provider answer is mapped.

No real send is made here. The transport is a recording fake that stands in for pywebpush's
`webpush` call; the default transport is never reached by a test. The subscription, the key and the
subject are sample values, not secrets or patient data.
"""

import json
from typing import Any

import pytest
from pywebpush import WebPushException

from diucs.adapters.outbound.push_webpush.web_push import (
    GONE,
    PUSH_TTL_SECONDS,
    VAPID_PRIVATE_KEY_SECRET,
    WebPushSender,
    vapid_private_key,
)
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.messaging import SendFailedError, TransientSendError
from diucs.domain.errors import NotFound

ENDPOINT = "https://push.example/sample-endpoint"
SUBSCRIPTION = {"endpoint": ENDPOINT, "keys": {"auth": "sample-auth", "p256dh": "sample-p256dh"}}
KEY = "sample-vapid-private-key"
SUBJECT = "mailto:operations@diucs.example"
RESPONSE_BODY = "provider says: SENSITIVE-PROVIDER-BODY"


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = RESPONSE_BODY


class RecordingTransport:
    """Stands in for pywebpush.webpush: records each call and answers with a fixed error or none."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    def __call__(self, subscription_info: Any, **kwargs: Any) -> _Response:
        self.calls.append({"subscription_info": subscription_info, **kwargs})
        if self._error is not None:
            raise self._error
        return _Response(201)


def _sender(transport: RecordingTransport) -> WebPushSender:
    return WebPushSender(KEY, SUBJECT, transport=transport)


async def test_the_payload_carries_title_body_and_url_as_json() -> None:
    transport = RecordingTransport()
    await _sender(transport).send(SUBSCRIPTION, "UCR West", "Confirm or update", "https://d/x")
    payload = json.loads(transport.calls[0]["data"])
    assert payload == {"title": "UCR West", "body": "Confirm or update", "url": "https://d/x"}


async def test_the_send_has_a_ten_minute_ttl_and_the_subject_in_its_claims() -> None:
    transport = RecordingTransport()
    await _sender(transport).send(SUBSCRIPTION, "t", "b", "https://d/x")
    call = transport.calls[0]
    assert PUSH_TTL_SECONDS == 600
    assert call["ttl"] == 600
    assert call["vapid_claims"]["sub"] == SUBJECT
    assert call["vapid_private_key"] == KEY
    assert call["subscription_info"] == SUBSCRIPTION


async def test_urgency_is_high_only_when_asked_and_normal_otherwise() -> None:
    transport = RecordingTransport()
    sender = _sender(transport)
    await sender.send(SUBSCRIPTION, "t", "b", "https://d/x")
    await sender.send(SUBSCRIPTION, "t", "b", "https://d/x", urgency="high")
    assert transport.calls[0]["headers"]["Urgency"] == "normal"
    assert transport.calls[1]["headers"]["Urgency"] == "high"


async def test_an_accepted_send_returns_an_accepted_receipt() -> None:
    receipt = await _sender(RecordingTransport()).send(SUBSCRIPTION, "t", "b", "https://d/x")
    assert receipt.accepted is True
    assert receipt.reason is None


@pytest.mark.parametrize("status", [404, 410])
async def test_a_gone_subscription_is_refused_with_reason_gone(status: int) -> None:
    transport = RecordingTransport(WebPushException("gone", response=_Response(status)))
    receipt = await _sender(transport).send(SUBSCRIPTION, "t", "b", "https://d/x")
    assert receipt.accepted is False
    assert receipt.reason == GONE


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_busy_or_failing_provider_is_transient(status: int) -> None:
    transport = RecordingTransport(WebPushException("busy", response=_Response(status)))
    with pytest.raises(TransientSendError):
        await _sender(transport).send(SUBSCRIPTION, "t", "b", "https://d/x")


async def test_a_network_failure_is_transient() -> None:
    transport = RecordingTransport(ConnectionError("no route"))
    with pytest.raises(TransientSendError):
        await _sender(transport).send(SUBSCRIPTION, "t", "b", "https://d/x")


@pytest.mark.parametrize("status", [400, 401, 413])
async def test_a_refused_request_is_a_send_failure_and_is_not_retried(status: int) -> None:
    transport = RecordingTransport(WebPushException("bad", response=_Response(status)))
    with pytest.raises(SendFailedError):
        await _sender(transport).send(SUBSCRIPTION, "t", "b", "https://d/x")


async def test_no_error_text_names_the_endpoint_the_keys_or_the_provider_body() -> None:
    for error in (
        WebPushException("bad", response=_Response(400)),
        WebPushException("busy", response=_Response(503)),
    ):
        transport = RecordingTransport(error)
        with pytest.raises((SendFailedError, TransientSendError)) as raised:
            await _sender(transport).send(SUBSCRIPTION, "t", "b", "https://d/x")
        text = f"{raised.value!s} {raised.value.__class__.__name__}"
        for secret in (ENDPOINT, "sample-auth", "sample-p256dh", RESPONSE_BODY, KEY):
            assert secret not in text


def test_the_vapid_key_is_read_from_the_platform_secret_store() -> None:
    secrets = FixedSecretStore({VAPID_PRIVATE_KEY_SECRET: KEY.encode()})
    assert vapid_private_key(secrets) == KEY


def test_a_missing_vapid_key_fails_closed_without_naming_a_value() -> None:
    with pytest.raises(NotFound):
        vapid_private_key(FixedSecretStore({}))
