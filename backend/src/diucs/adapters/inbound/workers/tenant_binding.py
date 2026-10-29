"""Binds the tenant of one bus message before any unit of work opens (I08, DEC-165). Stub."""

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Final

from diucs.adapters.inbound.workers.consumer import MessageConsumer, Outcome
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.application.ports.outbound.event_bus import BusMessage

NO_TENANT: Final = "message has no tenant"
BAD_TENANT: Final = "message tenant is not valid"
UNKNOWN_TENANT: Final = "message tenant is unknown or not active"

Observe = Callable[[BusMessage], AbstractContextManager[object]]


def untraced(message: BusMessage) -> AbstractContextManager[object]:
    return nullcontext()


class TenantBoundConsumer:
    def __init__(
        self, inner: MessageConsumer, tenants: ActiveTenants, observe: Observe = untraced
    ) -> None:
        self._inner = inner

    async def handle(self, message: BusMessage) -> Outcome:
        return await self._inner.handle(message)
