"""Scheduled-work consumer (I05): the consumer of the `scheduled.work` queue.

A `ScheduledWorkDue` message (the relay's, DEC-157, with the tenant property set) names one
ScheduledWork row. The consumer reads it under the tenant the message bound, runs the handler of its
kind when the row is still `scheduled`, and marks the row `done`. The shape is the reply processor's
(DEC-190): the handler runs with no unit of work held, because the missed-report ladder opens its
own units (DEC-146 item 4), and the message is marked after the work, so a crash redelivers it.

Outcomes follow the I04 framework: completed and duplicate are settled; dead-letter is for a message
that can never succeed (a payload that cannot be read, work that is not stored, work that disagrees
with the message, a kind with no handler, a handler that refuses the work with NotFound or
ValidationFailed); retry is any other failure. Work already `cancelled` or `done` is completed and
its handler does not run: cancel can race with delivery.

A handler must be idempotent by work id: a crash after it, or two deliveries at once, can run it
twice (DEC-190 item 4). No payload text, tenant id or stored text is put in a reason or a log line.
"""

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final

from diucs.adapters.inbound.workers.consumer import MAX_REASON_LENGTH, Outcome, PermanentError
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.work import DONE, SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.errors import NotFound, ValidationFailed

logger = logging.getLogger(__name__)

CONSUMER_NAME: Final = "scheduler"
EVENT_TYPE: Final = "ScheduledWorkDue"

MALFORMED: Final = "scheduled work message is malformed"
NOT_STORED: Final = "no scheduled work for this message"
DISAGREE: Final = "message and scheduled work disagree"
REFUSED: Final = "the handler refused the scheduled work"

WorkHandler = Callable[[ScheduledWork], Awaitable[None]]


class ScheduledWorkDispatcher:
    """The dispatch table: one handler for each work kind, each run with the stored work."""

    def __init__(self, handlers: Mapping[WorkKind, WorkHandler]) -> None:
        self._handlers: Mapping[WorkKind, WorkHandler] = MappingProxyType(dict(handlers))

    @property
    def handlers(self) -> Mapping[WorkKind, WorkHandler]:
        return self._handlers

    @property
    def kinds(self) -> frozenset[WorkKind]:
        return frozenset(self._handlers)

    async def __call__(self, work: ScheduledWork) -> None:
        handler = self._handlers.get(work.kind)
        if handler is None:
            raise PermanentError(f"no handler for {work.kind.value}")
        await handler(work)


@dataclass(frozen=True, slots=True)
class _Reference:
    work_id: str
    kind: WorkKind
    about_id: str


def _text(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise PermanentError(MALFORMED)
    return value


def _reference(message: BusMessage) -> _Reference:
    if message.event_type != EVENT_TYPE:
        raise PermanentError(MALFORMED)
    payload = message.payload
    work_id = _text(payload, "work_id")
    about_id = _text(payload, "about_id")
    try:
        kind = WorkKind(_text(payload, "kind"))
    except ValueError:
        raise PermanentError(MALFORMED) from None
    return _Reference(work_id, kind, about_id)


class ScheduledWorkConsumer:
    """A consumer (`handle(message)`), not an I04 handler: see the module text. Wrap it in a
    `TenantBoundConsumer` (`build_scheduled_work_consumer`), which binds the tenant first."""

    def __init__(self, dispatcher: ScheduledWorkDispatcher, uow_factory: UnitOfWorkFactory) -> None:
        self._dispatcher = dispatcher
        self._uow_factory = uow_factory

    async def handle(self, message: BusMessage) -> Outcome:
        try:
            reference = _reference(message)
            if await self._seen(message):
                return Outcome("duplicate")
            work = await self._load(reference)
            if work.status == SCHEDULED:
                await self._run(work)
            if not await self._settle(message, work.id):
                return Outcome("duplicate")
        except PermanentError as error:
            return Outcome("dead-letter", str(error)[:MAX_REASON_LENGTH])
        except Exception as error:
            logger.warning(
                "consumer %s will retry message %s: %s",
                CONSUMER_NAME,
                message.id,
                type(error).__name__,
            )
            return Outcome("retry", type(error).__name__)
        return Outcome("completed")

    async def _seen(self, message: BusMessage) -> bool:
        async with self._uow_factory() as uow:
            return await uow.processed.seen(message.id, CONSUMER_NAME)

    async def _load(self, reference: _Reference) -> ScheduledWork:
        async with self._uow_factory() as uow:
            try:
                stored = await uow.scheduled_work.get(reference.work_id)
            except NotFound:
                raise PermanentError(NOT_STORED) from None
        if stored.kind is not reference.kind or stored.about_id != reference.about_id:
            raise PermanentError(DISAGREE)
        return stored

    async def _run(self, work: ScheduledWork) -> None:
        try:
            await self._dispatcher(work)
        except NotFound, ValidationFailed:
            # The text of these can name a field or a value: it is not repeated (L166).
            raise PermanentError(REFUSED) from None

    async def _settle(self, message: BusMessage, work_id: str) -> bool:
        """Mark the message and, while the row is still scheduled, save it done, in one unit.
        A cancel that landed while the handler ran is kept. False when another delivery settled."""
        async with self._uow_factory() as uow:
            if not await uow.processed.mark_if_new(message.id, CONSUMER_NAME):
                return False
            await _finish(uow, work_id)
            await uow.commit()
        return True


async def _finish(uow: UnitOfWork, work_id: str) -> None:
    stored = await uow.scheduled_work.get(work_id)
    if stored.status == SCHEDULED:
        await uow.scheduled_work.save(replace(stored, status=DONE))


def build_scheduled_work_consumer(
    handlers: Mapping[WorkKind, WorkHandler],
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
    observe: Observe = untraced,
) -> TenantBoundConsumer:
    """The consumer of `scheduled.work`: the tenant bound from the message, then the work run once
    per message id, with the handler table of the composition root."""
    consumer = ScheduledWorkConsumer(ScheduledWorkDispatcher(handlers), uow_factory)
    return TenantBoundConsumer(consumer, tenants, observe)
