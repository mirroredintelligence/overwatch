"""Network boards built by hand for the tests of what is made from a board (TEN-082): rows with a
status, an organisation and nothing else that matters. Synthetic values only."""

from datetime import UTC, datetime

from diucs.domain.codes import ServiceCategory, Status
from diucs.domain.model.network import DirectorySource
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.network_board import NetworkBoard, NetworkBoardEntry
from diucs.domain.rules.pressure import Pressure, all_limited_or_worse, system_pressure

BOARD_AT = datetime(2026, 10, 26, 9, 40, tzinfo=UTC)


def board_entry(
    ref: str, organisation: str, status: Status | None, *, stale: bool = False
) -> NetworkBoardEntry:
    shown = status is not None
    return NetworkBoardEntry(
        row_ref=ref,
        organisation_name=organisation,
        service_name=f"Service {ref}",
        category=ServiceCategory.REABLEMENT,
        presentation=ListingPresentation.SHOWN if shown else ListingPresentation.UNAVAILABLE,
        status=status,
        unit_label="beds" if shown else None,
        effective_available=2 if shown else None,
        over_by=None,
        used=None,
        established=10 if shown else None,
        reported_at=BOARD_AT if shown else None,
        stale_warning=stale,
        was_due_at=None,
        source=DirectorySource.MANUAL,
    )


def board_of(*entries: NetworkBoardEntry, at: datetime = BOARD_AT) -> NetworkBoard:
    statuses = [e.status for e in entries if e.status is not None]
    pressure: Pressure = system_pressure(statuses)
    return NetworkBoard(
        entries=entries,
        pressure=pressure,
        all_limited_or_worse=all_limited_or_worse(statuses),
        generated_at=at,
    )
