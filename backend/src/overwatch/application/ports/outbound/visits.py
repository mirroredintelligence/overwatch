"""Outbound port: visit offers and the practitioner's visit settings (DEC-1309).

Everything is read and written in the caller's tenant (the unit of work's bound scope). An offer is
found by its own id, and the use case checks that it is the caller's: another practitioner's or
another tenant's offer is not there. Adapter: Neo4jVisitRepository
(graph_store/visit_repository.py).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from overwatch.domain.model.visit import VisitOffer, VisitSettings, VisitState


class VisitRepository(Protocol):
    async def add_many(self, offers: Sequence[VisitOffer]) -> None:
        """Store new offers. An offer whose practitioner or service is not in the tenant raises
        NotFound, and nothing of the batch is kept by the unit of work."""
        ...

    async def get(self, offer_id: str) -> VisitOffer | None:
        """The offer with this id in the bound tenant, or None."""
        ...

    async def for_booking(self, booking_id: str) -> list[VisitOffer]:
        """Every offer made for the booking, ordered by id."""
        ...

    async def for_practitioner(
        self, practitioner_id: str, since: datetime, now: datetime
    ) -> list[VisitOffer]:
        """The practitioner's offers that can still be answered at `now` (offered and not past
        their time), their visits that are under way (accepted, on the way or arrived), and those
        that changed state at or after `since`, ordered by when they were offered."""
        ...

    async def change(self, offer: VisitOffer, expected: VisitState) -> bool:
        """Write the offer's state, time, sector, sealed details and estimate, only if it still
        holds the state `expected`. False when it does not (someone else moved it first): nothing
        is written."""
        ...

    async def settings(self, practitioner_id: str) -> VisitSettings | None:
        """The practitioner's settings, or None when none were ever saved."""
        ...

    async def save_settings(self, settings: VisitSettings) -> None:
        """Insert the practitioner's settings, or replace them."""
        ...
