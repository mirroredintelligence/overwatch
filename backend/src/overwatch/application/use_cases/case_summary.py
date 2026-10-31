"""BuildCaseSummary: the summary an advisor copies into the referral, for a case that is still open
(H-322, W8A K6, DEC-294).

`build_summary` (record_outcome.py) writes the rows from the case. This use case gives it what the
case alone does not hold: the destination the advisor is referring to, whether a booking was made
there for this case, and how old the destination's figure was. Without a destination those three
rows are left out (a row with no value is not written), so a summary never says a patient is going
anywhere the advisor did not name.

The destination is a service of the viewer's own tenant that is active; another tenant's service,
an unknown one and an inactive one are the same not found. The booking is the most recent booking
made for this case at that service that still holds (requested or confirmed, or completed after a
confirmation); a declined, expired, cancelled, withdrawn or not-reached booking is not a booked
line. A closed case has no postcode or needs left and no summary (Conflict, as build_summary
says). The postcode row is the district (DEC-294).

Read only: nothing is written and nothing is audited, as the case read is not (DEC-398).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.open_case import check_role
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.application.use_cases.record_outcome import build_summary
from diucs.domain.codes import BookingStatus
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.booking import Booking
from diucs.domain.rules.freshness import data_age_text
from diucs.domain.rules.london_time import to_london

NO_FIGURE: Final = "No figure reported"
_HOLDING: Final = frozenset(
    {BookingStatus.REQUESTED, BookingStatus.CONFIRMED, BookingStatus.COMPLETED}
)


@dataclass(frozen=True, slots=True)
class CaseSummary:
    reference: str
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class BuildCaseSummaryQuery:
    actor: Actor
    case_id: str
    destination_service_id: str | None = None


def _clock_text(at: datetime) -> str:
    return to_london(at).strftime("%H:%M")


def booking_line(booking: Booking) -> str | None:
    """The "Booked" row for a booking, or None when the booking did not hold. Times are London."""
    if booking.status not in _HOLDING:
        return None
    if booking.status is BookingStatus.REQUESTED:
        return f"Requested {_clock_text(booking.requested_at)}, waiting for the service to confirm"
    if booking.confirmed_at is None:
        return "Confirmed"
    return f"Confirmed {_clock_text(booking.confirmed_at)}"


def data_age_line(reported_at: datetime | None, now: datetime) -> str:
    """How old the destination figure was, in words; no figure reads as that, never as a time."""
    if reported_at is None:
        return NO_FIGURE
    return data_age_text(now - reported_at)


class BuildCaseSummary:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, query_board: QueryBoard
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._query_board = query_board

    async def execute(self, query: BuildCaseSummaryQuery) -> CaseSummary:
        check_role(query.actor)
        # The board is its own unit of work, read before this one opens (one open unit at a time).
        board = (
            None
            if query.destination_service_id is None
            else await self._query_board.execute(QueryBoardQuery(query.actor))
        )
        async with self._uow_factory() as uow:
            case = await uow.cases.get(query.case_id)
            if case is None:
                raise NotFound("no case with this id")
            if case.closed_at is not None:
                raise Conflict("the summary is built only while the case is open")
            destination_name: str | None = None
            booked: str | None = None
            age: str | None = None
            if query.destination_service_id is not None and board is not None:
                profile = await uow.services.get(query.destination_service_id)
                if profile is None or not profile.active:
                    raise NotFound("no active service with this id")
                destination_name = profile.name
                held = [
                    line
                    for booking in await uow.bookings.for_case(case.id)
                    if booking.service_id == profile.id
                    and (line := booking_line(booking)) is not None
                ]
                booked = held[0] if held else None
                entry = next((e for e in board.entries if e.service_id == profile.id), None)
                age = data_age_line(None if entry is None else entry.reported_at, self._clock.now())
        rows = build_summary(
            case, destination_name=destination_name, booking_line=booked, data_age_line=age
        )
        return CaseSummary(reference=case.reference, rows=tuple(rows))
