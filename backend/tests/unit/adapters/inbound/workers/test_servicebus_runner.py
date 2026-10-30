"""The Service Bus runner settles each message by the consumer's outcome (I04). No Docker: the
receiver and the consumer are stubs. Only the runner imports azure.servicebus."""

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from diucs.adapters.inbound.workers import consumer as consumer_module
from diucs.adapters.inbound.workers.consumer import IdempotentConsumer, Outcome
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.servicebus_runner import (
    ConsumerNotTenantBound,
    ServiceBusRunner,
)
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.application.ports.outbound.event_bus import BusMessage


class _Receiver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def complete_message(self, message: Any) -> None:
        self.calls.append(("complete", None))

    async def abandon_message(self, message: Any) -> None:
        self.calls.append(("abandon", None))

    async def dead_letter_message(
        self, message: Any, reason: str | None = None, error_description: str | None = None
    ) -> None:
        self.calls.append(("dead-letter", (reason, error_description)))


class _Consumer:
    name = "board-projector"
    binds_tenant = True  # as TenantBoundConsumer does: the runner refuses a consumer that does not

    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.seen: list[BusMessage] = []

    async def handle(self, message: BusMessage) -> Outcome:
        self.seen.append(message)
        return self.outcome


def _raw(body: bytes = b'{"service": "svc-1"}', **overrides: Any) -> Any:
    # As the adapter sends it (TEN-020): the ids are qualified with the tenant and the tenant is
    # an application property. A test that wants another shape overrides it.
    fields: dict[str, Any] = {
        "message_id": "tenant-a:m-1",
        "body": iter([body]),
        "subject": "CapacityReported",
        "session_id": None,
        "application_properties": {"tenantId": "tenant-a"},
        "delivery_count": 1,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _runner(consumer: Any, **options: Any) -> ServiceBusRunner:
    return ServiceBusRunner(
        client=None,  # type: ignore[arg-type]
        entity="capacity.events",
        subscription="board-projector",
        consumer=consumer,
        **options,
    )


async def test_completed_completes_the_message() -> None:
    receiver, consumer = _Receiver(), _Consumer(Outcome("completed"))
    await _runner(consumer).process(receiver, _raw())
    assert receiver.calls == [("complete", None)]


async def test_duplicate_completes_the_message() -> None:
    receiver = _Receiver()
    await _runner(_Consumer(Outcome("duplicate"))).process(receiver, _raw())
    assert receiver.calls == [("complete", None)]


async def test_retry_abandons_the_message() -> None:
    receiver = _Receiver()
    await _runner(_Consumer(Outcome("retry", "RuntimeError"))).process(receiver, _raw())
    assert receiver.calls == [("abandon", None)]


async def test_dead_letter_dead_letters_with_the_reason() -> None:
    receiver = _Receiver()
    await _runner(_Consumer(Outcome("dead-letter", "unknown kind"))).process(receiver, _raw())
    assert receiver.calls == [("dead-letter", ("unknown kind", "unknown kind"))]


async def test_the_message_is_converted_for_the_consumer() -> None:
    consumer = _Consumer(Outcome("completed"))
    raw = _raw(
        json.dumps({"a": 1}).encode(),
        message_id="tenant-a:m-9",
        session_id="tenant-a:svc-1",
        subject="BookingMade",
    )
    await _runner(consumer).process(_Receiver(), raw)
    assert consumer.seen == [
        BusMessage(
            id="m-9",
            topic="capacity.events",
            event_type="BookingMade",
            payload={"a": 1},
            session_id="svc-1",
            tenant_id="tenant-a",
        )
    ]


async def test_the_event_type_falls_back_to_the_application_property() -> None:
    consumer = _Consumer(Outcome("completed"))
    raw = _raw(
        subject=None,
        application_properties={b"tenantId": b"tenant-a", b"event_type": b"PromptDue"},
    )
    await _runner(consumer).process(_Receiver(), raw)
    assert consumer.seen[0].event_type == "PromptDue"


@pytest.mark.parametrize(
    ("key", "value"), [("tenantId", "tenant-a"), (b"tenantId", b"tenant-a")], ids=["text", "bytes"]
)
async def test_the_tenant_comes_from_the_tenant_id_application_property(
    key: str | bytes, value: str | bytes
) -> None:
    """I08: a consumer binds the tenant from the message, so the runner must carry the property
    the bus adapter sends (DEC-130 item 7). The key may arrive as text or as bytes."""
    consumer = _Consumer(Outcome("completed"))
    raw = _raw(application_properties={key: value})

    await _runner(consumer).process(_Receiver(), raw)

    assert consumer.seen[0].tenant_id == "tenant-a"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, "tenant-missing"),
        ("", "tenant-missing"),
        (7, "tenant-malformed"),
        (True, "tenant-malformed"),
        (b"\xff", "tenant-malformed"),
        ("Tenant-A", "tenant-malformed"),
        ("a:b", "tenant-malformed"),
    ],
)
async def test_a_tenant_property_that_is_not_a_tenant_dead_letters_the_message_with_its_reason(
    value: Any, reason: str
) -> None:
    # TEN-025: the reader is `from_wire`, and the dead letter says which of the fixed reasons it is.
    receiver, consumer = _Receiver(), _Consumer(Outcome("completed"))
    raw = _raw(application_properties={"tenantId": value})

    await _runner(consumer).process(receiver, raw)

    assert consumer.seen == []
    assert receiver.calls == [("dead-letter", (reason, reason))]


async def test_a_message_with_no_tenant_property_is_dead_lettered_before_the_consumer() -> None:
    receiver, consumer = _Receiver(), _Consumer(Outcome("completed"))

    await _runner(consumer).process(receiver, _raw(application_properties={}))

    assert consumer.seen == []
    assert receiver.calls == [("dead-letter", ("tenant-missing", "tenant-missing"))]


@pytest.mark.parametrize(
    "overrides",
    [
        {"message_id": "m-1"},
        {"message_id": "tenant-b:m-1"},
        {"session_id": "tenant-b:svc-1"},
        {"session_id": "svc-1"},
    ],
    ids=["id-not-qualified", "id-of-another-tenant", "session-of-another-tenant", "session-bare"],
)
async def test_ids_that_do_not_belong_to_the_property_tenant_dead_letter_the_message(
    overrides: dict[str, Any],
) -> None:
    receiver, consumer = _Receiver(), _Consumer(Outcome("completed"))

    await _runner(consumer).process(receiver, _raw(**overrides))

    assert consumer.seen == []
    assert receiver.calls == [("dead-letter", ("tenant-mismatch", "tenant-mismatch"))]


@pytest.mark.parametrize(
    "raw",
    [
        _raw(b"not json at all 4821"),
        _raw(b"[1, 2]"),
        _raw(b"\xff\xfe"),
        _raw(message_id=None),
        _raw(subject=None),
    ],
    ids=["not-json", "not-an-object", "not-utf8", "no-id", "no-type"],
)
async def test_a_message_that_cannot_be_read_is_dead_lettered_without_the_consumer(
    raw: Any,
) -> None:
    receiver, consumer = _Receiver(), _Consumer(Outcome("completed"))
    await _runner(consumer).process(receiver, raw)
    assert consumer.seen == []
    assert [name for name, _ in receiver.calls] == ["dead-letter"]
    (_, (reason, description)) = receiver.calls[0]
    assert reason == "malformed message"
    assert "4821" not in str(description)


async def test_a_settlement_failure_does_not_stop_the_runner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Broken(_Receiver):
        async def complete_message(self, message: Any) -> None:
            raise RuntimeError("lock lost for 4821")

    with caplog.at_level("DEBUG"):
        await _runner(_Consumer(Outcome("completed"))).process(Broken(), _raw())
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "m-1" in text
    assert "RuntimeError" in text
    assert "4821" not in text


async def test_a_dead_letter_logs_the_id_entity_and_reason_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO"):
        await _runner(_Consumer(Outcome("dead-letter", "unknown kind"))).process(
            _Receiver(), _raw(b'{"secret": "DT4 8XX"}')
        )
    text = " ".join(record.getMessage() for record in caplog.records)
    assert "m-1" in text and "capacity.events" in text and "unknown kind" in text
    assert "DT4 8XX" not in text


async def test_run_returns_once_stop_is_set() -> None:
    stop = asyncio.Event()
    stop.set()
    await asyncio.wait_for(_runner(_Consumer(Outcome("completed"))).run(stop), timeout=5)


def test_the_consumer_core_does_not_import_the_azure_sdk() -> None:
    tree = ast.parse(Path(consumer_module.__file__).read_text(encoding="utf-8"))
    imported = {
        name
        for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
    }
    assert not [name for name in imported if name.split(".")[0] == "azure"]


async def test_a_body_that_is_plain_bytes_is_read() -> None:
    consumer = _Consumer(Outcome("completed"))
    raw = _raw()
    raw.body = b'{"a": 2}'
    await _runner(consumer).process(_Receiver(), raw)
    assert consumer.seen[0].payload == {"a": 2}


def test_serve_is_the_name_the_process_entries_call_for_run() -> None:
    assert ServiceBusRunner.serve is ServiceBusRunner.run


# --- the runner serves only a consumer that binds the tenant (TEN-025) --------------------------


class _Unbound:
    async def handle(self, message: BusMessage) -> Outcome:
        raise AssertionError("an unbound consumer must never be asked")


def test_a_consumer_that_does_not_bind_the_tenant_is_refused_when_the_runner_is_built() -> None:
    with pytest.raises(ConsumerNotTenantBound) as refused:
        _runner(_Unbound())
    assert str(refused.value) == (
        "a queue runner needs a consumer that binds the tenant of each message"
    )


def test_an_idempotent_consumer_alone_is_not_enough() -> None:
    consumer = IdempotentConsumer("board-projector", _never, lambda: None)  # type: ignore[arg-type, return-value]
    with pytest.raises(ConsumerNotTenantBound):
        _runner(consumer)


def test_a_tenant_bound_consumer_is_accepted() -> None:
    inner = IdempotentConsumer("board-projector", _never, lambda: None)  # type: ignore[arg-type, return-value]
    _runner(TenantBoundConsumer(inner, StaticTenants(["tenant-a"])))


def test_the_marker_cannot_be_claimed_by_a_truthy_value() -> None:
    class Claims:
        binds_tenant = "yes"

        async def handle(self, message: BusMessage) -> Outcome:
            raise AssertionError

    with pytest.raises(ConsumerNotTenantBound):
        _runner(Claims())


async def _never(message: BusMessage, uow: Any) -> None:
    raise AssertionError("the handler must not run")
