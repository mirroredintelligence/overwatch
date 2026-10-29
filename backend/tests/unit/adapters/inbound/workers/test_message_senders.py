"""Outbound message senders: the payload rules and the refusals that need no database (I10).

Every case here is refused before the unit of work is used, so no Docker is needed. Content is
sealed with the real AES-GCM sealer (DEC-116) and a fixed secret. The behaviour on real Neo4j is in
tests/integration/adapters/inbound/workers/test_message_senders.py. The sample values are not
patient data.
"""

import json
from typing import Any

import pytest

from diucs.adapters.inbound.workers.consumer import PermanentError
from diucs.adapters.inbound.workers.message_senders import (
    BAD_CHANNEL,
    BAD_CONTENT,
    BAD_PAYLOAD,
    CONSUMER_EMAIL,
    CONSUMER_SMS,
    EMAIL_SUBSCRIPTION,
    MESSAGES_TOPIC,
    NO_TENANT,
    PUSH_SUBSCRIPTION,
    SEND_MESSAGE_EVENT,
    SMS_SUBSCRIPTION,
    EmailMessageSender,
    OutboundMessage,
    SmsMessageSender,
    is_handled,
    parse_outbound,
)
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import Communication
from diucs.domain.codes import Channel

SECRET = b"link-token-test-secret-0123456789abcdef"
SEALER = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))
TENANT = "tenant-a"
ROLE = "role-1"
OUTBOX_ID = "outbox-1"
TEXT = "How many referrals can you take in the next 2 hrs? Reply with a number. UCR West"
SUBJECT = "DIUCS Dorset: capacity question for UCR West"
HTML = "<p>How many referrals can you take in the next 2 hrs?</p>"
BODY_SENTINEL = "SENTINEL-BODY-TEXT-do-not-echo"


class _Untouched:
    """A unit of work whose every attribute is a failure: a refused message must not reach it."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work must not be used: {name}")


def _sealed(
    text: str = TEXT,
    subject: str | None = None,
    html: str | None = None,
    *,
    message_id: str = OUTBOX_ID,
    tenant: str = TENANT,
    role: str = ROLE,
) -> str:
    content = json.dumps(
        {"text": text, "subject": subject, "html": html},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return SEALER.seal(content, message_id=message_id, tenant_id=tenant, recipient_role_id=role)


def _payload(channel: Any = "text", subject: str | None = None, html: str | None = None) -> dict:
    return {
        "communication_id": "comm-1",
        "message_id": "C1",
        "channel": channel,
        "recipient_role_id": ROLE,
        "sealed_content": _sealed(TEXT, subject, html),
    }


def _open(payload: dict[str, Any], *, message_id: str = OUTBOX_ID, tenant: str = TENANT):
    return parse_outbound(payload, message_id=message_id, tenant_id=tenant, sealer=SEALER)


def _message(payload: dict[str, Any], tenant_id: str | None = TENANT) -> BusMessage:
    return BusMessage(
        id=OUTBOX_ID,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload=payload,
        tenant_id=tenant_id,
    )


# --- the names the Service Bus config and the prompt fix ----------------------------------------


def test_the_names_are_the_ones_the_config_and_the_prompt_fix() -> None:
    assert MESSAGES_TOPIC == "messages.outbound"
    assert SEND_MESSAGE_EVENT == "SendMessage"
    assert (CONSUMER_SMS, CONSUMER_EMAIL) == ("sender-sms", "sender-email")
    assert (SMS_SUBSCRIPTION, EMAIL_SUBSCRIPTION, PUSH_SUBSCRIPTION) == (
        "text-sender",
        "email-sender",
        "push-sender",
    )


# --- opening the payload ----------------------------------------------------------------------


def test_a_text_payload_opens_to_its_text_and_has_no_subject_or_html() -> None:
    opened = _open(_payload("text"))

    assert opened == OutboundMessage(
        communication_id="comm-1",
        channel=Channel.TEXT,
        recipient_role_id=ROLE,
        message_id="C1",
        text=TEXT,
        subject=None,
        html=None,
    )


def test_an_email_payload_opens_with_its_subject_text_and_html() -> None:
    opened = _open(_payload("email", subject=SUBJECT, html=HTML))

    assert opened.channel is Channel.EMAIL
    assert (opened.subject, opened.text, opened.html) == (SUBJECT, TEXT, HTML)


@pytest.mark.parametrize("channel", ["fax", "", "TEXT", None, 3])
def test_a_channel_that_is_not_a_known_channel_is_permanent(channel: Any) -> None:
    with pytest.raises(PermanentError):
        _open(_payload(channel))


@pytest.mark.parametrize(
    "field", ["communication_id", "recipient_role_id", "message_id", "sealed_content", "channel"]
)
def test_a_payload_missing_a_field_is_permanent(field: str) -> None:
    payload = _payload()
    del payload[field]

    with pytest.raises(PermanentError) as refused:
        _open(payload)

    assert str(refused.value) == BAD_PAYLOAD


@pytest.mark.parametrize("message_id", ["outbox-2", "outbox-1 "])
def test_content_sealed_for_another_message_is_refused_without_its_text(message_id: str) -> None:
    with pytest.raises(PermanentError) as refused:
        _open(_payload(), message_id=message_id)

    assert str(refused.value) == BAD_CONTENT


def test_content_sealed_for_another_tenant_is_refused() -> None:
    with pytest.raises(PermanentError) as refused:
        _open(_payload(), tenant="tenant-b")

    assert str(refused.value) == BAD_CONTENT


def test_content_sealed_for_another_recipient_is_refused() -> None:
    payload = _payload()
    payload["recipient_role_id"] = "role-2"

    with pytest.raises(PermanentError):
        _open(payload)


def test_sealed_text_that_is_not_a_json_object_is_refused() -> None:
    payload = _payload()
    payload["sealed_content"] = SEALER.seal(
        "not json", message_id=OUTBOX_ID, tenant_id=TENANT, recipient_role_id=ROLE
    )

    with pytest.raises(PermanentError) as refused:
        _open(payload)

    assert str(refused.value) == BAD_CONTENT


@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_text_is_refused(text: str) -> None:
    payload = _payload()
    payload["sealed_content"] = _sealed(text)

    with pytest.raises(PermanentError):
        _open(payload)


def test_an_email_without_a_subject_is_refused() -> None:
    with pytest.raises(PermanentError):
        _open(_payload("email", subject=None, html=HTML))


def test_a_refusal_never_names_the_body_text() -> None:
    payload = _payload()
    payload["sealed_content"] = _sealed(BODY_SENTINEL, message_id="other")

    with pytest.raises(PermanentError) as refused:
        _open(payload)

    assert BODY_SENTINEL not in str(refused.value)


# --- the channel and the tenant are checked before any unit of work ---------------------------


async def test_a_push_payload_is_refused_by_the_text_sender_before_the_unit_of_work() -> None:
    sender = SmsMessageSender(senders=None, sealer=SEALER)

    with pytest.raises(PermanentError) as refused:
        await sender(_message(_payload("push")), _Untouched())  # type: ignore[arg-type]

    assert str(refused.value) == BAD_CHANNEL


async def test_an_email_payload_is_refused_by_the_text_sender() -> None:
    sender = SmsMessageSender(senders=None, sealer=SEALER)

    with pytest.raises(PermanentError) as refused:
        await sender(_message(_payload("email", SUBJECT, HTML)), _Untouched())  # type: ignore[arg-type]

    assert str(refused.value) == BAD_CHANNEL


async def test_a_text_payload_is_refused_by_the_email_sender() -> None:
    sender = EmailMessageSender(senders=None, sealer=SEALER)

    with pytest.raises(PermanentError) as refused:
        await sender(_message(_payload("text")), _Untouched())  # type: ignore[arg-type]

    assert str(refused.value) == BAD_CHANNEL


async def test_a_message_without_a_tenant_is_refused_before_the_unit_of_work() -> None:
    sender = SmsMessageSender(senders=None, sealer=SEALER)

    with pytest.raises(PermanentError) as refused:
        await sender(_message(_payload("text"), tenant_id=None), _Untouched())  # type: ignore[arg-type]

    assert str(refused.value) == NO_TENANT


# --- whether a communication has already been handled ----------------------------------------


def _communication(status: str, provider_id: str | None) -> Communication:
    from datetime import UTC, datetime

    return Communication(
        id="comm-1",
        message_id="C1",
        channel=Channel.TEXT,
        recipient_role_id=ROLE,
        about_id=None,
        payload_text=TEXT,
        sent_at=datetime(2026, 10, 29, 9, 0, tzinfo=UTC),
        delivery_status=status,
        provider_message_id=provider_id,
    )


@pytest.mark.parametrize(
    ("status", "provider_id", "handled"),
    [
        ("queued", None, False),
        ("queued", "SM1", True),
        ("sent", None, True),
        ("sent", "SM1", True),
        ("failed", None, True),
        ("delivered", "SM1", True),
    ],
)
def test_a_communication_is_handled_once_it_has_a_provider_id_or_has_left_queued(
    status: str, provider_id: str | None, handled: bool
) -> None:
    assert is_handled(_communication(status, provider_id)) is handled
