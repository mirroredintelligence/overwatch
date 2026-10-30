"""A bus message that skips the checks `BusMessage` makes when it is built (TEN-020).

A consumer still checks the tenant it is handed (defence in depth: a message built by a path that
bypasses validation must not be handled). Those checks can no longer be reached with a normally
built message, so their tests build one with a tenant the constructor would refuse.
"""

from typing import Any

from diucs.application.ports.outbound.event_bus import BusMessage

_PLACEHOLDER_TENANT = "placeholder-tenant"


def unvalidated_tenant(message: BusMessage, tenant_id: Any) -> BusMessage:
    """The same message with this tenant set directly, whatever it is (None, an empty text, a
    network id, a string that is not a tenant id)."""
    object.__setattr__(message, "tenant_id", tenant_id)
    return message


def message_with_tenant(tenant_id: Any, **fields: Any) -> BusMessage:
    """A `BusMessage` of these fields whose tenant is set without the constructor's check."""
    return unvalidated_tenant(BusMessage(tenant_id=_PLACEHOLDER_TENANT, **fields), tenant_id)
