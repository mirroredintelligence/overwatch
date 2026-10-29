"""Outbound port: support tickets (R18, under O06). A support person asks for a session to be
opened on a ticket; a shift lead approves the ticket; only then may support open the session
with it (DEC-206 item 2).

A ticket belongs to the tenant of the unit of work, like a code or an access: another tenant's
ticket reads as not found. Its id is the ticket reference the person typed (A-Z, a-z, 0-9,
hyphen, at most 32).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

TicketState = Literal["pending", "approved"]


@dataclass(frozen=True, slots=True)
class SupportTicketRecord:
    id: str
    session_id: str
    requested_by: str
    state: TicketState
    approved_by: str | None
    requested_at: datetime
    approved_at: datetime | None


class SupportTicketRepository(Protocol):
    async def add(self, record: SupportTicketRecord) -> bool:
        """Store a pending ticket for a session of the tenant. False when the session is not the
        tenant's, or the ticket id is already taken in the tenant.
        """
        ...

    async def get(self, ticket_id: str) -> SupportTicketRecord | None:
        """The tenant's ticket with this id, or None."""
        ...

    async def approve(self, ticket_id: str, approved_by: str, at: datetime) -> bool:
        """Move a pending ticket to approved, by this practitioner, at this time. False when the
        ticket
        is not the tenant's or is not pending.
        """
        ...
