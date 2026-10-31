"""Outbound port: the support-access tickets of the platform (TEN-075, TEN-084).

A ticket is the platform's record that a support person asked one tenant for access and what the
tenant's administrator answered (`domain/rules/support_ticket.py`). It is read from two sides: the
support person lists the tickets they asked for, and the tenant's administrator lists the tickets
that name their tenant. So it lives in the platform scope (the registry's), not in a tenant's: one
record, one state, moved by compare and set, with no copy to fall out of step.

Each read and each write names the side it is for. A tenant's side is given the tenant's id by the
use case, which takes it from the bound scope and from nothing else; the store never reads one from
a request. Another tenant's ticket, and another person's, reads as not found.

Adapter: `adapters/outbound/graph_store/support_ticket_store.py`. A ticket holds no secret: the
keyed hash of the code, never the code, and the opaque reference of the support person, never a
name.
"""

from typing import Protocol

from diucs.domain.rules.support_ticket import SupportTicket, TicketState


class CrossTenantTicketStore(Protocol):
    async def add(self, ticket: SupportTicket) -> None:
        """Store a new ticket. An id that exists is `Conflict`."""
        ...

    async def for_tenant(self, tenant_id: str, ticket_id: str) -> SupportTicket | None:
        """The ticket with this id when it names this tenant, else None."""
        ...

    async def for_principal(self, principal_ref: str, ticket_id: str) -> SupportTicket | None:
        """The ticket with this id when this support person asked for it, else None."""
        ...

    async def of_tenant(self, tenant_id: str, limit: int) -> list[SupportTicket]:
        """The tenant's tickets, newest first."""
        ...

    async def of_principal(self, principal_ref: str, limit: int) -> list[SupportTicket]:
        """The support person's tickets, newest first."""
        ...

    async def move(self, ticket: SupportTicket, expected: TicketState) -> bool:
        """Write the ticket when the stored one is still in the state the caller read (compare and
        set). False when it is not, or when there is no such ticket for its tenant: nothing is
        written."""
        ...
