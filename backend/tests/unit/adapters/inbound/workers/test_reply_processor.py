"""ReplyProcessor payload rules (I08). No Docker: every case here is refused before any unit of work
opens, so the factory must never be called. The flow on real Neo4j is in
tests/integration/adapters/inbound/workers/test_reply_processor.py."""

from typing import Any

import pytest

from diucs.adapters.inbound.sms_webhook import routes
from diucs.adapters.inbound.workers.consumer import MAX_REASON_LENGTH, Outcome
from diucs.adapters.inbound.workers.reply_processor import (
    CONSUMER_NAME,
    REPLY_EVENT,
    ReplyProcessor,
    reply_key,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.tenancy import TenantNotBound, bind_tenant
from diucs.application.use_cases.handle_inbound_text import (
    HandleInboundTextCommand,
    HandleInboundTextResult,
)

PHONE = "ab" * 32
SECRET_TEXT = "SECRET-REPLY-TEXT"


class _NeverUsedUseCase:
    def __init__(self) -> None:
        self.commands: list[HandleInboundTextCommand] = []

    async def execute(self, command: HandleInboundTextCommand) -> HandleInboundTextResult:
        self.commands.append(command)
        raise AssertionError("the use case must not run for a refused message")


def _no_unit() -> UnitOfWork:
    raise AssertionError("no unit of work may open for a refused message")


def _payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "phone_hash": PHONE,
        "text": SECRET_TEXT,
        "received_at": "2026-10-23T09:12:00+00:00",
        "provider_message_id": "SM123",
    }
    payload.update(changes)
    return {name: value for name, value in payload.items() if value is not ...}


def _message(payload: dict[str, Any], event_type: str = REPLY_EVENT) -> BusMessage:
    return BusMessage(
        id="SM123",
        topic="inbound.replies",
        event_type=event_type,
        payload=payload,
        tenant_id="tenant-a",
    )


def _processor(use_case: _NeverUsedUseCase) -> ReplyProcessor:
    return ReplyProcessor(use_case, _no_unit)


def test_the_names_are_the_ones_the_webhook_and_the_prompt_fix() -> None:
    assert CONSUMER_NAME == "reply-processor"
    assert REPLY_EVENT == routes.REPLY_EVENT


@pytest.mark.parametrize("field", ["phone_hash", "text", "received_at", "provider_message_id"])
async def test_a_missing_field_is_dead_lettered(field: str) -> None:
    use_case = _NeverUsedUseCase()

    with bind_tenant("tenant-a"):
        outcome = await _processor(use_case).handle(_message(_payload(**{field: ...})))

    assert outcome.kind == "dead-letter"
    assert outcome.reason is not None
    assert field in outcome.reason
    assert use_case.commands == []


@pytest.mark.parametrize(
    "changes",
    [
        {"phone_hash": 7},
        {"phone_hash": ""},
        {"text": None},
        {"text": 4},
        {"received_at": 20261023},
        {"received_at": "yesterday"},
        {"received_at": "2026-10-23T09:12:00"},  # no offset: a wall time, not an instant
        {"provider_message_id": ""},
        {"provider_message_id": ["SM123"]},
    ],
)
async def test_a_field_of_the_wrong_kind_is_dead_lettered(changes: dict[str, Any]) -> None:
    use_case = _NeverUsedUseCase()

    with bind_tenant("tenant-a"):
        outcome = await _processor(use_case).handle(_message(_payload(**changes)))

    assert outcome.kind == "dead-letter"
    assert use_case.commands == []


async def test_a_message_of_another_kind_is_dead_lettered() -> None:
    use_case = _NeverUsedUseCase()

    with bind_tenant("tenant-a"):
        outcome = await _processor(use_case).handle(_message(_payload(), event_type="SmsOther"))

    assert outcome.kind == "dead-letter"
    assert use_case.commands == []


async def test_a_refusal_never_repeats_the_text_the_phone_or_the_id() -> None:
    bad = [
        _payload(phone_hash=...),
        _payload(received_at="not a time " + SECRET_TEXT),
        _payload(provider_message_id=...),
    ]
    for payload in bad:
        with bind_tenant("tenant-a"):
            outcome = await _processor(_NeverUsedUseCase()).handle(_message(payload))
        assert outcome.kind == "dead-letter"
        assert outcome.reason is not None
        assert len(outcome.reason) <= MAX_REASON_LENGTH
        for secret in (SECRET_TEXT, PHONE, "SM123"):
            assert secret not in outcome.reason


def test_the_idempotency_key_carries_the_bound_tenant() -> None:
    with bind_tenant("tenant-a"):
        first = reply_key("SM123")
    with bind_tenant("tenant-b"):
        second = reply_key("SM123")

    assert first != second
    assert "tenant-a" in first
    assert "SM123" in first


def test_the_idempotency_key_is_never_built_without_a_tenant() -> None:
    with pytest.raises(TenantNotBound):
        reply_key("SM123")


def test_the_outcome_type_is_the_consumers() -> None:
    assert Outcome("dead-letter", "x").kind == "dead-letter"
