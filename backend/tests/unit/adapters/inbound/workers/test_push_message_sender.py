"""The push message sender (I14): the urgency rule and the refusals that need no database.

The sends and the store effects (gone subscriptions deleted, the Communication settled) are in
tests/integration/adapters/inbound/workers/test_push_message_sender.py. No real push is sent: the
sender is a recording fake. Sample values only.
"""

import json
from datetime import UTC, datetime
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
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import RecordingPushSender
from diucs.application.ports.outbound.event_bus import BusMessage
from tests.support.bus import message_with_tenant

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
    # Set without the constructor's check: a message built by a path that bypasses validation
    # must still not be handled (defence in depth; a validated BusMessage always has a tenant).
    message = message_with_tenant(
        None,
        id=OUTBOX_ID,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload=_payload(),
    )
    with pytest.raises(PermanentError):
        await _sender()(message, _Untouched())  # type: ignore[arg-type]


# ----------------------------------------------------------------- a push to a person (W9H, DEC-1044)
#
# An alert (K3) and an executive's test notification name the PERSON, not a post: an executive holds
# no post, so there is no role, no Communication and no sealed content. The title and body are the
# plain K3 text (a service's name and the kind of alert, or the test words), which name no patient and
# carry no link.

PERSON = "stf-0123456789abcdef0123456789abcdef"
SUBSCRIPTION_JSON = {"endpoint": "https://push.example/sample-endpoint"}


def _person_payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message_id": "K3",
        "channel": "push",
        "recipient_practitioner_id": PERSON,
        "title": "UCR West is over capacity",
        "body": "Tap to acknowledge.",
        "alert_id": "alert-1",
    }
    payload.update(changes)
    return payload


class _People:
    async def get_role(self, role_id: str) -> None:
        raise AssertionError("a person push has no role")


class _Subscriptions:
    def __init__(self, held: list[Any]) -> None:
        self.held = held
        self.deleted: list[str] = []
        self.asked: list[str] = []

    async def for_practitioner(self, practitioner_id: str) -> list[Any]:
        self.asked.append(practitioner_id)
        return [item for item in self.held if item.practitioner_id == practitioner_id]

    async def delete(self, device_id: str) -> None:
        self.deleted.append(device_id)


class _PersonUnit:
    def __init__(self, held: list[Any]) -> None:
        self.people = _People()
        self.push_subscriptions = _Subscriptions(held)

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"a person push must not use the unit's {name}")


def _held(person: str = PERSON, device: str = "app-1") -> Any:
    from diucs.application.ports.outbound.messaging import PushSubscription

    return PushSubscription(
        device_id=device,
        practitioner_id=person,
        subscription=dict(SUBSCRIPTION_JSON),
        saved_at=datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
    )


async def test_a_person_push_goes_to_every_app_of_the_person_at_high_urgency() -> None:
    sender = RecordingPushSender()
    runner = PushMessageSender(
        sender,
        SEALER,
        "https://diucs.example/reporter",
        FixedClock(datetime(2026, 10, 30, 9, 0, tzinfo=UTC)),
    )
    unit = _PersonUnit([_held(device="app-1"), _held(device="app-2"), _held("someone-else", "app-3")])

    await runner(_message(_person_payload()), unit)  # type: ignore[arg-type]

    assert unit.push_subscriptions.asked == [PERSON]
    assert [(p.title, p.body, p.urgency) for p in sender.sent] == [
        ("UCR West is over capacity", "Tap to acknowledge.", "high"),
        ("UCR West is over capacity", "Tap to acknowledge.", "high"),
    ]
    assert {p.url for p in sender.sent} == {"https://diucs.example/reporter"}


async def test_a_person_with_no_subscription_is_not_an_error_and_sends_nothing() -> None:
    sender = RecordingPushSender()
    runner = PushMessageSender(
        sender, SEALER, "https://diucs.example/reporter", FixedClock(datetime(2026, 10, 30, tzinfo=UTC))
    )

    await runner(_message(_person_payload()), _PersonUnit([]))  # type: ignore[arg-type]

    assert sender.sent == []


async def test_a_subscription_the_provider_reports_gone_is_deleted() -> None:
    sender = RecordingPushSender()
    sender.gone_next()
    runner = PushMessageSender(
        sender, SEALER, "https://diucs.example/reporter", FixedClock(datetime(2026, 10, 30, tzinfo=UTC))
    )
    unit = _PersonUnit([_held(device="app-1")])

    await runner(_message(_person_payload()), unit)  # type: ignore[arg-type]

    assert unit.push_subscriptions.deleted == ["app-1"]
    assert sender.sent == []


@pytest.mark.parametrize(
    "changes",
    [
        {"title": ""},
        {"title": None},
        {"body": " "},
        {"body": 5},
        {"recipient_practitioner_id": ""},
        {"recipient_practitioner_id": 7},
        {"title": "x" * 200},
        {"body": "x" * 400},
        {"message_id": "C1"},
        {"message_id": "nonsense"},
    ],
)
async def test_a_person_push_that_cannot_be_sent_is_refused_before_the_unit_of_work(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(PermanentError):
        await _sender()(_message(_person_payload(**changes)), _Untouched())  # type: ignore[arg-type]


async def test_a_person_payload_on_another_channel_is_refused() -> None:
    with pytest.raises(PermanentError) as refused:
        await _sender()(_message(_person_payload(channel="text")), _Untouched())  # type: ignore[arg-type]
    assert str(refused.value) == BAD_CHANNEL


async def test_a_payload_that_names_a_person_and_a_role_is_refused() -> None:
    # One recipient kind per message: a role's message is sealed under the role, a person's is not.
    with pytest.raises(PermanentError):
        await _sender()(  # type: ignore[arg-type]
            _message(_person_payload(recipient_role_id=ROLE)), _Untouched()
        )
