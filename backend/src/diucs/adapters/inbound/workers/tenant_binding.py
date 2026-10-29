"""Binds the tenant of one bus message before any unit of work opens (I08, DEC-165).

A consumer has no request and no token. The tenant it works for is the one the producer put on the
message, as the Service Bus application property `tenantId` (DEC-130 item 7, DEC-157): the I07
webhook sets it from the number called, the outbox relay from the tenant it read the row under.
`TenantBoundConsumer` wraps a consumer and, for each message:

1. refuses a message with no tenant, a tenant that is not a valid tenant id (a network id included)
   or a tenant the directory does not list as active, by dead-lettering it. A suspended tenant is
   not listed as active, so it reads the same as an unknown one. The inner consumer never runs and
   no unit of work opens, scoped or not: a message is never processed unscoped.
2. binds the tenant for the whole handling of the message, so every unit of work the inner consumer
   (or a use case it calls) opens binds that one scope (DEC-146). The binding is restored when the
   message is done, whatever the outcome.

If the directory cannot answer, the message is a retry: it says nothing about the message. The
dead-letter reasons are fixed texts that hold no tenant id and no payload.

Trace context (O01): `observe` is called with the message and its result is entered around the
handling, after the tenant is bound. It does nothing now. O01 gives the runner the `traceparent`
application property and makes `observe` open a span from it; no consumer changes.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Final

from diucs.adapters.inbound.workers.consumer import MessageConsumer, Outcome, PermanentError
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import ScopeId, ScopeInvalid, bind_scope

logger = logging.getLogger(__name__)

NO_TENANT: Final = "message has no tenant"
BAD_TENANT: Final = "message tenant is not valid"
UNKNOWN_TENANT: Final = "message tenant is unknown or not active"

Observe = Callable[[BusMessage], AbstractContextManager[object]]


def untraced(message: BusMessage) -> AbstractContextManager[object]:
    """The trace hook until O01: nothing."""
    return nullcontext()


class TenantBoundConsumer:
    def __init__(
        self, inner: MessageConsumer, tenants: ActiveTenants, observe: Observe = untraced
    ) -> None:
        self._inner = inner
        self._tenants = tenants
        self._observe = observe

    async def handle(self, message: BusMessage) -> Outcome:
        try:
            scope = await self._scope(message)
        except PermanentError as error:
            return Outcome("dead-letter", str(error))
        except Exception as error:
            # The directory could not answer: this says nothing about the message. The class name
            # only is logged, because the text of an error can carry data.
            logger.warning(
                "tenant check for message %s failed: %s", message.id, type(error).__name__
            )
            return Outcome("retry", type(error).__name__)
        with bind_scope(scope), self._observe(message):
            return await self._inner.handle(message)

    async def _scope(self, message: BusMessage) -> ScopeId:
        tenant_id = message.tenant_id
        if not tenant_id:
            raise PermanentError(NO_TENANT)
        try:
            scope = ScopeId.tenant(tenant_id)
        except ScopeInvalid:
            raise PermanentError(BAD_TENANT) from None
        if tenant_id not in await self._tenants.active_tenant_ids():
            raise PermanentError(UNKNOWN_TENANT)
        return scope
