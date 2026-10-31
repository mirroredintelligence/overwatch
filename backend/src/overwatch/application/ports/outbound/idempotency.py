"""Consumer idempotency: a message is handled once per consumer (P15, DEC-012).

Providers and Service Bus deliver at least once. A consumer calls mark_if_new inside its own unit
of work before it acts, so the marker commits with the work it protects.

A marker belongs to the tenant bound to its unit of work (DEC-130 item 6, TEN-016): the same message
id in two tenants is two markers, and a tenant never sees another tenant's marker.
"""

from typing import Protocol


class ProcessedMessages(Protocol):
    async def mark_if_new(self, message_id: str, consumer: str) -> bool:
        """True when this unit of work created the marker, False when it already existed."""
        ...

    async def seen(self, message_id: str, consumer: str) -> bool:
        """True when this consumer has already marked this message, in the bound scope. Writes
        nothing: a consumer that cannot hold one unit of work around its work (I08) asks first,
        works, then marks."""
        ...
