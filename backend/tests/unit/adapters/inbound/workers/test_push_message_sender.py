"""The push message sender (I14): the urgency rule and the refusals that need no database.

The sends and the store effects (gone subscriptions deleted, the Communication settled) are in
tests/integration/adapters/inbound/workers/test_push_message_sender.py. No real push is sent: the
sender is a recording fake. Sample values only.
"""

import json
from typing import Any

import pytest

from diucs.adapters.inbound.workers.consumer import PermanentError
from diucs.adapters.inbound.workers.message_senders import (
    BAD_CHANNEL,
    BAD_CONTENT,
    MESSAGES_TOPIC,
    PUSH_SUBSCRIPTION,
    SEND_MESSAGE_EVENT,
    PushMessageSender,
    push_urgency,
)
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import RecordingPushSender
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.event_bus import BusMessage
from datetime import UTC, datetime

SECRET = b"link-token-test-secret-0123456789abcdef"
SEALER = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))
TENANT = "tenant-a"
ROLE = "role-1"
OUTBOX_ID = "outbox-1"


class _Untouched:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work must not be used: {name}")


def _payload(channel: str = "push", subject: str | None = "UCR West", text: str = "Body") -> dict:
    content = json.dumps(
        {"text": text, "subject": subject, "html": None}, sort_keys=True, separators=(",", ":")
    )
    sealed = SEALER.seal(content, message_id=OUTBOX_ID, tenant_id=TENANT, recipient_role_id=ROLE)
    return {
        "communication_id": "comm-1",
        "message_id": "C1",
        "channel": channel,
        "recipient_role_id": ROLE,
        "sealed_content": sealed,
    }


def _message(payload: dict[str, Any]) -> BusMessage:
    return BusMessage(
        id=OUTBOX_ID,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload=payload,
        tenant_id=TENANT,
    )


def _sender() -> PushMessageSender:
    return PushMessageSender(
        RecordingPushSender(),
        SEALER,
        "https://diucs.example/reporter",
        FixedClock(datetime(2026, 10, 25, 13, 12, tzinfo=UTC)),
    )


def test_the_push_subscription_is_the_one_the_config_names() -> None:
    assert PUSH_SUBSCRIPTION == "push-sender"


@pytest.mark.parametrize("message_id", ["B3", "K3"])
def test_booking_requests_and_alerts_are_high_urgency(message_id: str) -> None:
    assert push_urgency(message_id) == "high"


@pytest.mark.parametrize("message_id", ["C1", "C8", "K2", "B1", "B2"])
def test_every_other_push_is_normal_urgency(message_id: str) -> None:
    assert push_urgency(message_id) == "normal"


async def test_a_text_payload_is_refused_by_the_push_sender_before_the_unit_of_work() -> None:
    with pytest.raises(PermanentError) as refused:
        await _sender()(_message(_payload("text", subject=None)), _Untouched())  # type: ignore[arg-type]
    assert str(refused.value) == BAD_CHANNEL


async def test_a_push_without_a_title_is_refused_as_bad_content() -> None:
    with pytest.raises(PermanentError) as refused:
        await _sender()(_message(_payload("push", subject=None)), _Untouched())  # type: ignore[arg-type]
    assert str(refused.value) == BAD_CONTENT


async def test_a_push_message_without_a_tenant_is_refused_before_the_unit_of_work() -> None:
    message = BusMessage(
        id=OUTBOX_ID,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload=_payload(),
        tenant_id=None,
    )
    with pytest.raises(PermanentError):
        await _sender()(message, _Untouched())  # type: ignore[arg-type]
