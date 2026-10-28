"""Idempotent message consumer core (I04). Red-commit stub (DEC-010)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.domain.errors import DomainError

OutcomeKind = Literal["completed", "duplicate", "dead-letter", "retry"]
Handler = Callable[[BusMessage, UnitOfWork], Awaitable[None]]


class PermanentError(DomainError):
    """A message that can never succeed."""


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    reason: str | None = None


class IdempotentConsumer:
    def __init__(self, name: str, handler: Handler, uow_factory: UnitOfWorkFactory) -> None:
        self.name = name
        self._handler = handler
        self._uow_factory = uow_factory

    async def handle(self, message: BusMessage) -> Outcome:
        return Outcome("retry", "stub")
