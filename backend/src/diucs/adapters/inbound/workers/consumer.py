"""Idempotent message consumer core (I04, DEC-012).

A message is handled at most once per consumer name. Inside one unit of work the consumer marks
(message id, consumer) as processed, runs the handler on the same unit of work and commits, so
the marker and the handler's writes commit together or not at all. Service Bus delivers at least
once, so the same id can come again: the second delivery finds the marker and does nothing.

Outcomes: completed and duplicate are settled as complete; dead-letter is for a message that can
never succeed (PermanentError); retry is any other failure, abandoned so the bus redelivers, and
dead-lettered by the bus after its max delivery count. This module does not import the Azure SDK.

No payload text leaves this module: a retry reason is the exception class name, and a dead-letter
reason is the PermanentError text cut to MAX_REASON_LENGTH. A handler must not put payload text
in a PermanentError.

The tenant (TEN-025, DEC-130 item 7). The tenant property of a bus message is unsigned, so it is
never trusted on its own: `TenantBoundConsumer` has already checked it against the tenant directory
and bound it, and this consumer checks the binding again before it opens a unit of work, and the
scope the unit opened under before it marks the message processed or runs the handler. A message
whose tenant is not the bound scope, or a unit that opened under another scope, is dead-lettered
with `tenant-mismatch` and nothing is written, so a consumer that is wired without the binding
cannot process a message unscoped.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, current_scope_or_none
from diucs.domain.errors import DomainError

logger = logging.getLogger(__name__)

MAX_REASON_LENGTH = 100
TENANT_MISMATCH = "tenant-mismatch"

OutcomeKind = Literal["completed", "duplicate", "dead-letter", "retry"]
Handler = Callable[[BusMessage, UnitOfWork], Awaitable[None]]


class PermanentError(DomainError):
    """A message that can never succeed (bad payload, unknown kind, validation). It is
    dead-lettered at once instead of being retried."""


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    reason: str | None = None


class MessageConsumer(Protocol):
    """What the Service Bus runner needs from a consumer: handle one message and say how it ended.
    IdempotentConsumer is one; TenantBoundConsumer wraps one and binds the tenant first (I08)."""

    async def handle(self, message: BusMessage) -> Outcome: ...


def _is_the_tenant_of(scope: ScopeId | None, message: BusMessage) -> bool:
    return scope is not None and scope.kind is ScopeKind.TENANT and scope.value == message.tenant_id


class IdempotentConsumer:
    def __init__(self, name: str, handler: Handler, uow_factory: UnitOfWorkFactory) -> None:
        self.name = name
        self._handler = handler
        self._uow_factory = uow_factory

    async def handle(self, message: BusMessage) -> Outcome:
        try:
            if not _is_the_tenant_of(current_scope_or_none(), message):
                raise PermanentError(TENANT_MISMATCH)
            async with self._uow_factory() as uow:
                if not _is_the_tenant_of(uow.unit_scope, message):
                    raise PermanentError(TENANT_MISMATCH)
                if not await uow.processed.mark_if_new(message.id, self.name):
                    return Outcome("duplicate")
                await self._handler(message, uow)
                await uow.commit()
        except PermanentError as error:
            return Outcome("dead-letter", str(error)[:MAX_REASON_LENGTH])
        except Exception as error:
            logger.warning(
                "consumer %s will retry message %s: %s", self.name, message.id, type(error).__name__
            )
            return Outcome("retry", type(error).__name__)
        return Outcome("completed")
