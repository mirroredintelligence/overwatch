"""Test doubles and builders for the inbound queue workers (I08).

Nothing here stores a record: the Processed markers, the Communications and the capacity reports
are the real Neo4j ones. The doubles stand in for the use case, for a store that fails once, and for
the Service Bus receiver. Each failing double fails at one call only (lesson L128).
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace, TracebackType
from typing import Any, Self

from diucs.application.ports.outbound.event_bus import BusMessage, to_wire
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, current_scope_or_none
from diucs.application.use_cases.handle_inbound_text import (
    HandleInboundTextCommand,
    HandleInboundTextResult,
)

PHONE = "ab" * 32
RECEIVED_AT = datetime(2026, 10, 23, 9, 12, tzinfo=UTC)


def reply_message(
    tenant_id: str | None,
    message_id: str = "SM100",
    *,
    text: str = "4",
    phone_hash: str = PHONE,
    received_at: datetime = RECEIVED_AT,
    omit: tuple[str, ...] = (),
    **payload_changes: Any,
) -> BusMessage:
    """What the I07 webhook queues on inbound.replies (DEC-149 item 5)."""
    payload: dict[str, Any] = {
        "phone_hash": phone_hash,
        "text": text,
        "received_at": received_at.isoformat(),
        "provider_message_id": message_id,
    }
    payload.update(payload_changes)
    return BusMessage(
        id=message_id,
        topic="inbound.replies",
        event_type="SmsReceived",
        payload={name: value for name, value in payload.items() if name not in omit},
        tenant_id=tenant_id,
    )


def receipt_message(
    tenant_id: str | None,
    provider_message_id: str,
    status: str,
    error_code: str | None = None,
    omit: tuple[str, ...] = (),
    **payload_changes: Any,
) -> BusMessage:
    """What the I07 webhook queues on inbound.receipts (DEC-149 item 8): the id is the Twilio
    message id and the provider status, so each status of a message has its own bus id."""
    payload: dict[str, Any] = {
        "provider_message_id": provider_message_id,
        "status": status,
        "error_code": error_code,
    }
    payload.update(payload_changes)
    return BusMessage(
        id=f"{provider_message_id}:{status}",
        topic="inbound.receipts",
        event_type="SmsDeliveryReceived",
        payload={name: value for name, value in payload.items() if name not in omit},
        tenant_id=tenant_id,
    )


class RecordingUseCase:
    """A HandleInboundText stand-in. It records each command with the tenant bound when it ran,
    opens its own unit of work as the real one does (so a unit held around it would be refused), and
    can be told to raise."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory | None = None, outcome: str = "recorded"
    ) -> None:
        self._uow_factory = uow_factory
        self._outcome = outcome
        self.commands: list[HandleInboundTextCommand] = []
        self.tenants: list[str | None] = []
        self.raises: list[Exception] = []

    async def execute(self, command: HandleInboundTextCommand) -> HandleInboundTextResult:
        self.commands.append(command)
        scope = current_scope_or_none()
        self.tenants.append(None if scope is None else scope.value)
        if self.raises:
            raise self.raises.pop(0)
        if self._uow_factory is not None:
            async with self._uow_factory():
                pass
        return HandleInboundTextResult(self._outcome, ())


class _FlakyProcessed:
    def __init__(self, target: Any, state: UnitLog) -> None:
        self._target = target
        self._state = state

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    async def mark_if_new(self, message_id: str, consumer: str) -> bool:
        if self._state.fail_marks:
            self._state.fail_marks -= 1
            raise RuntimeError("the store went away")
        return await self._target.mark_if_new(message_id, consumer)


class UnitLog:
    """What a LoggingFactory saw: the scope of every unit it opened, and the marks still to fail."""

    def __init__(self, fail_marks: int = 0) -> None:
        self.scopes: list[ScopeId | None] = []
        self.fail_marks = fail_marks


class _LoggedUnit:
    def __init__(self, unit: UnitOfWork, log: UnitLog) -> None:
        self._unit = unit
        self._log = log

    def __getattr__(self, name: str) -> Any:
        return getattr(self._unit, name)

    @property
    def processed(self) -> Any:
        return _FlakyProcessed(self._unit.processed, self._log)

    async def __aenter__(self) -> Self:
        await self._unit.__aenter__()
        self._log.scopes.append(self._unit.unit_scope)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._unit.__aexit__(exc_type, exc, tb)


def logging_factory(factory: UnitOfWorkFactory, log: UnitLog) -> UnitOfWorkFactory:
    """A factory over a real one: it records the scope of each unit it opens, and the first
    `log.fail_marks` calls of mark_if_new raise."""
    return lambda: _LoggedUnit(factory(), log)  # type: ignore[return-value]


class Receiver:
    """A Service Bus receiver that records how each message was settled."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def complete_message(self, message: Any) -> None:
        self.calls.append(("complete", message.message_id))

    async def abandon_message(self, message: Any) -> None:
        self.calls.append(("abandon", message.message_id))

    async def dead_letter_message(
        self, message: Any, reason: str | None = None, error_description: str | None = None
    ) -> None:
        self.calls.append(("dead-letter", message.message_id))


def raw(message: BusMessage) -> Any:
    """The received form of a BusMessage, as the Azure SDK shows it to the runner."""
    wire = to_wire(message)  # TEN-020: the qualified ids and the tenant property
    return SimpleNamespace(
        message_id=wire.message_id,
        body=iter([json.dumps(message.payload).encode("utf-8")]),
        subject=wire.subject,
        session_id=wire.session_id,
        application_properties=dict(wire.application_properties),
        delivery_count=1,
    )
