"""Scheduled-work consumer (I05). Red stub: every name exists and raises until the green commit."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Final

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.work import ScheduledWork, WorkKind

CONSUMER_NAME: Final = "scheduler"
EVENT_TYPE: Final = "ScheduledWorkDue"

WorkHandler = Callable[[ScheduledWork], Awaitable[None]]


class ScheduledWorkDispatcher:
    def __init__(self, handlers: Mapping[WorkKind, WorkHandler]) -> None:
        raise NotImplementedError

    @property
    def handlers(self) -> Mapping[WorkKind, WorkHandler]:
        raise NotImplementedError

    @property
    def kinds(self) -> frozenset[WorkKind]:
        raise NotImplementedError

    async def __call__(self, work: ScheduledWork) -> None:
        raise NotImplementedError


class ScheduledWorkConsumer:
    def __init__(self, dispatcher: ScheduledWorkDispatcher, uow_factory: UnitOfWorkFactory) -> None:
        raise NotImplementedError

    async def handle(self, message: BusMessage) -> Outcome:
        raise NotImplementedError


def build_scheduled_work_consumer(
    handlers: Mapping[WorkKind, WorkHandler],
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
    observe: Observe = untraced,
) -> TenantBoundConsumer:
    raise NotImplementedError


__all__ = [
    "CONSUMER_NAME",
    "EVENT_TYPE",
    "ScheduledWorkConsumer",
    "ScheduledWorkDispatcher",
    "WorkHandler",
    "build_scheduled_work_consumer",
]
