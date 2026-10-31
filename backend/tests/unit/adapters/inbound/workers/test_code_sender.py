"""The consumer of `codes.dispatch`: it texts a text code to a known number (KI-270, N1).

The consumer opens the sealed code and number with the outbox message id, the bound tenant and the
recipient key as their associated data, renders the K1 wording, and sends it from the bound
tenant's own sender. It writes nothing: no Communication, no audit entry, no log line holds the
code or the number. A code for an unknown number (DiscardCode) is never sent. The provider is a
recording fake: nothing real is called. Sample numbers only (07700 900xxx).
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.inbound.workers.code_sender import (
    CODE_SUBSCRIPTION,
    CODES_TOPIC,
    CONSUMER_CODE,
    EXPIRED,
    CodeMessageSender,
    code_runner,
)
from diucs.adapters.inbound.workers.consumer import IdempotentConsumer, PermanentError
from diucs.adapters.inbound.workers.message_senders import (
    BAD_CONTENT,
    BAD_PAYLOAD,
    NO_CHANNEL,
    NO_TENANT,
    NOT_A_SEND,
    REFUSED,
    SEND_FAILED,
)
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import FixedSenderResolver, RecordingSmsSender
from diucs.application.ports.outbound.messaging import (
    SendFailedError,
    SendReceipt,
    TransientSendError,
)
from diucs.application.use_cases.text_code import DISCARD_CODE, SEND_CODE
from diucs.domain.codes import Channel
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.rules.identity_policy import CODE_VALID_FOR
from tests.support.bus import message_with_tenant
from tests.support.tenancy import as_tenant

SEALER = AesGcmContentSealer(
    FixedSecretStore({"link-token": b"link-token-test-secret-0123456789abcdef"})
)
TENANT = "tenant-a"
OTHER = "tenant-b"
OUTBOX_ID = "outbox-code-1"
KEY = "code:" + "ab" * 32 + ":setup"
CODE = "482913"
PHONE = "+447700900123"
ISSUED = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
NOW = ISSUED + timedelta(seconds=5)


class _Untouched:
    """A unit of work whose every attribute is a failure: the code sender writes nothing."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work must not be used: {name}")


def _payload(
    *,
    code: str = CODE,
    phone: str = PHONE,
    tenant: str = TENANT,
    message_id: str = OUTBOX_ID,
    key: str = KEY,
    purpose: str = "setup",
    issued: datetime = ISSUED,
) -> dict[str, Any]:
    return {
        "sealed_code": SEALER.seal(
            code, message_id=message_id, tenant_id=tenant, recipient_role_id=key
        ),
        "sealed_phone": SEALER.seal(
            phone, message_id=message_id, tenant_id=tenant, recipient_role_id=key
        ),
        "recipient_key": key,
        "purpose": purpose,
        "issued_at": issued.isoformat(),
    }


def _message(payload: dict[str, Any], event: str = SEND_CODE, tenant: str | None = TENANT) -> Any:
    return message_with_tenant(
        tenant, id=OUTBOX_ID, topic=CODES_TOPIC, event_type=event, payload=payload
    )


def _sender(
    sms: Any = None, *, now: datetime = NOW, tenants: tuple[str, ...] = (TENANT,)
) -> tuple[CodeMessageSender, RecordingSmsSender]:
    recording = sms if sms is not None else RecordingSmsSender("+441234567890")
    resolver = FixedSenderResolver(sms={tenant: recording for tenant in tenants})
    return CodeMessageSender(resolver, SEALER, FixedClock(now)), recording


async def _handle(sender: CodeMessageSender, message: Any, tenant: str = TENANT) -> None:
    with as_tenant(tenant):
        await sender(message, _Untouched())  # type: ignore[arg-type]


# --- the names the Service Bus config fixes ----------------------------------------------------


def test_the_names_are_the_ones_the_config_fixes() -> None:
    assert CODES_TOPIC == "codes.dispatch"
    assert CODE_SUBSCRIPTION == "code-sender"
    assert CONSUMER_CODE == "sender-code"


# --- a known number is texted ------------------------------------------------------------------


async def test_a_code_is_texted_to_the_sealed_number_in_the_k1_wording() -> None:
    sender, sms = _sender()

    await _handle(sender, _message(_payload()))

    wording = render(MessageId.K1, Channel.TEXT, code=CODE).text
    assert [(s.to, s.text, s.message_id) for s in sms.sent] == [(PHONE, wording, OUTBOX_ID)]
    assert sms.sent[0].tenant == TENANT
    assert sms.sent[0].identity == "+441234567890"


@pytest.mark.parametrize("purpose", ["register", "setup", "reverify", "pin-reset", "new-device"])
async def test_every_purpose_is_texted_the_same_way(purpose: str) -> None:
    sender, sms = _sender()

    key = f"code:{'ab' * 32}:{purpose}"
    await _handle(sender, _message(_payload(purpose=purpose, key=key)))

    assert len(sms.sent) == 1


async def test_the_text_leaves_from_the_bound_tenants_own_sender() -> None:
    a, b = RecordingSmsSender("number-a"), RecordingSmsSender("number-b")
    resolver = FixedSenderResolver(sms={TENANT: a, OTHER: b})
    sender = CodeMessageSender(resolver, SEALER, FixedClock(NOW))

    await _handle(sender, _message(_payload(tenant=OTHER), tenant=OTHER), OTHER)

    assert (len(a.sent), len(b.sent)) == (0, 1)
    assert b.sent[0].identity == "number-b"


# --- an unknown number is never texted ----------------------------------------------------------


async def test_a_code_for_an_unknown_number_is_discarded_and_nothing_is_opened_or_sent() -> None:
    sender, sms = _sender()
    payload = _payload()
    payload["sealed_phone"] = "not-even-sealed"  # a discard is not opened at all

    await _handle(sender, _message(payload, event=DISCARD_CODE))

    assert sms.sent == []


async def test_a_discard_does_not_ask_the_resolver_for_a_sender() -> None:
    class _Resolver:
        async def sms_for(self) -> Any:
            raise AssertionError("a discarded code must not reach a sender")

    sender = CodeMessageSender(_Resolver(), SEALER, FixedClock(NOW))  # type: ignore[arg-type]

    await _handle(sender, _message(_payload(), event=DISCARD_CODE))


@pytest.mark.parametrize("event", ["SendMessage", "Other", ""])
async def test_any_other_event_is_permanent(event: str) -> None:
    sender, sms = _sender()

    with pytest.raises(PermanentError) as refused:
        await _handle(sender, _message(_payload(), event=event))

    assert str(refused.value) == NOT_A_SEND
    assert sms.sent == []


# --- the payload and the seal -------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["sealed_code", "sealed_phone", "recipient_key", "purpose", "issued_at"]
)
async def test_a_payload_missing_a_field_is_permanent_and_sends_nothing(field: str) -> None:
    sender, sms = _sender()
    payload = _payload()
    del payload[field]

    with pytest.raises(PermanentError) as refused:
        await _handle(sender, _message(payload))

    assert str(refused.value) == BAD_PAYLOAD
    assert sms.sent == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "login"),
        ("purpose", 3),
        ("issued_at", "yesterday"),
        ("issued_at", "2026-10-29T14:00:00"),  # no zone: refused, never guessed
        ("recipient_key", "role-1"),
        ("recipient_key", "code:abc:reverify"),  # a key for another purpose
        ("sealed_code", ""),
    ],
)
async def test_a_field_that_is_not_what_the_request_writes_is_permanent(
    field: str, value: Any
) -> None:
    sender, sms = _sender()
    payload = _payload()
    payload[field] = value

    with pytest.raises(PermanentError):
        await _handle(sender, _message(payload))

    assert sms.sent == []


async def test_a_key_that_is_not_this_purposes_code_key_is_refused() -> None:
    # Each key is sealed under itself, so only the checks on the key can refuse it.
    sender, sms = _sender()
    hashed = "ab" * 32
    cases = (
        ("setup", f"code:{hashed}:reverify"),
        ("login", f"code:{hashed}:login"),
        ("setup", f"role-{hashed}:setup"),
        ("setup", "code::setup"),
    )
    for purpose, key in cases:
        with pytest.raises(PermanentError) as refused:
            await _handle(sender, _message(_payload(purpose=purpose, key=key)))
        assert str(refused.value) == BAD_PAYLOAD
    assert sms.sent == []


async def test_a_code_sealed_for_another_tenant_is_refused_without_its_text() -> None:
    sender, sms = _sender()

    with pytest.raises(PermanentError) as refused:
        await _handle(sender, _message(_payload(tenant=OTHER)))

    assert str(refused.value) == BAD_CONTENT
    assert sms.sent == []


@pytest.mark.parametrize("which", ["sealed_code", "sealed_phone"])
async def test_a_part_sealed_for_another_message_or_recipient_is_refused(which: str) -> None:
    sender, sms = _sender()
    for kwargs in ({"message_id": "outbox-other"}, {"key": "code:" + "cd" * 32 + ":setup"}):
        payload = _payload()
        payload[which] = _payload(**kwargs)[which]

        with pytest.raises(PermanentError) as refused:
            await _handle(sender, _message(payload))

        assert str(refused.value) == BAD_CONTENT
    assert sms.sent == []


async def test_a_number_that_is_not_an_international_uk_mobile_is_refused() -> None:
    sender, sms = _sender()

    for phone in ("07700 900123", "+4412345", "", "+15550100"):
        with pytest.raises(PermanentError) as refused:
            await _handle(sender, _message(_payload(phone=phone)))
        assert str(refused.value) == BAD_CONTENT
    assert sms.sent == []


async def test_a_code_that_is_not_six_digits_is_refused() -> None:
    sender, sms = _sender()

    for code in ("12345", "1234567", "12345a", ""):
        with pytest.raises(PermanentError) as refused:
            await _handle(sender, _message(_payload(code=code)))
        assert str(refused.value) == BAD_CONTENT
    assert sms.sent == []


async def test_a_message_with_no_tenant_is_permanent() -> None:
    sender, sms = _sender()

    with pytest.raises(PermanentError) as refused:
        await _handle(sender, _message(_payload(), tenant=None))

    assert str(refused.value) == NO_TENANT
    assert sms.sent == []


# --- a code is useful for ten minutes only ------------------------------------------------------


async def test_a_code_one_tick_inside_its_ten_minutes_is_sent() -> None:
    sender, sms = _sender(now=ISSUED + CODE_VALID_FOR - timedelta(microseconds=1))

    await _handle(sender, _message(_payload()))

    assert len(sms.sent) == 1


async def test_a_code_at_its_ten_minutes_is_not_sent_and_is_not_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender, sms = _sender(now=ISSUED + CODE_VALID_FOR)

    with caplog.at_level(logging.DEBUG):
        await _handle(sender, _message(_payload()))

    assert sms.sent == []
    assert EXPIRED in caplog.text


async def test_a_code_stamped_in_the_future_is_still_sent() -> None:
    # A clock a few seconds apart between the hosts must not stop a code that is current.
    sender, sms = _sender(now=ISSUED - timedelta(seconds=3))

    await _handle(sender, _message(_payload()))

    assert len(sms.sent) == 1


# --- failures ------------------------------------------------------------------------------------


async def test_a_tenant_with_no_text_channel_sends_nothing_and_is_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender, sms = _sender(tenants=())

    with caplog.at_level(logging.DEBUG):
        await _handle(sender, _message(_payload()))

    assert sms.sent == []
    assert NO_CHANNEL in caplog.text


async def test_an_unreachable_provider_is_retried() -> None:
    class _Unreachable:
        async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
            raise TransientSendError("the provider could not be reached")

    sender, _ = _sender(_Unreachable())

    with pytest.raises(TransientSendError):
        await _handle(sender, _message(_payload()))


async def test_a_refusal_the_provider_will_not_change_is_logged_by_reason_and_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Refuses:
        async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
            raise SendFailedError("the provider answered 400 with code 21211")

    sender, _ = _sender(_Refuses())

    with caplog.at_level(logging.DEBUG):
        await _handle(sender, _message(_payload()))

    assert SEND_FAILED in caplog.text


async def test_a_text_the_provider_does_not_accept_is_logged_by_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sms = RecordingSmsSender()
    sms.fail_next()
    sender, _ = _sender(sms)

    with caplog.at_level(logging.DEBUG):
        await _handle(sender, _message(_payload()))

    assert sms.sent == []
    assert REFUSED in caplog.text


# --- nothing about the code or the number is written anywhere ------------------------------------


async def test_no_log_line_holds_the_code_the_number_or_the_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sms = RecordingSmsSender()
    sender, _ = _sender(sms)

    with caplog.at_level(logging.DEBUG):
        await _handle(sender, _message(_payload()))  # sent
        sms.fail_next()
        await _handle(sender, _message(_payload()))  # refused
        await _handle(sender, _message(_payload(), event=DISCARD_CODE))
        with pytest.raises(PermanentError):
            await _handle(sender, _message(_payload(tenant=OTHER)))

    for secret in (CODE, "7700900123", "07700900123", "900123", "Do not share"):
        assert secret not in caplog.text
    assert OUTBOX_ID in caplog.text  # the message id is what a log may hold


async def test_a_permanent_error_text_holds_no_code_or_number() -> None:
    sender, _ = _sender()

    for payload in (_payload(tenant=OTHER), _payload(code="12")):
        with pytest.raises(PermanentError) as refused:
            await _handle(sender, _message(payload))
        text = json.dumps(str(refused.value))
        assert CODE not in text and "900123" not in text


async def test_the_sender_never_touches_the_unit_of_work() -> None:
    # _Untouched raises on any attribute: no Communication, audit entry or contact is read or
    # written, so no code reaches the graph through this consumer.
    sender, sms = _sender()

    await _handle(sender, _message(_payload()))

    assert len(sms.sent) == 1


# --- the runner ----------------------------------------------------------------------------------


def test_the_runner_reads_the_code_subscription_and_binds_the_tenant_first() -> None:
    runner = code_runner(
        None,  # type: ignore[arg-type]
        lambda: _Untouched(),  # type: ignore[arg-type, return-value]
        StaticTenants([TENANT]),
        FixedSenderResolver(),
        SEALER,
        FixedClock(NOW),
    )

    assert (runner._entity, runner._subscription, runner._sessions) == (
        "codes.dispatch",
        "code-sender",
        False,
    )
    assert isinstance(runner._consumer, TenantBoundConsumer)
    inner = runner._consumer._inner
    assert isinstance(inner, IdempotentConsumer)
    assert inner.name == "sender-code"
