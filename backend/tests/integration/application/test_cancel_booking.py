"""Integration tests for CancelBooking (U20), against the real Neo4j the harness starts.

The advisor cancels a request before the service answers, or a confirmation after it. The slot goes
back on the board, the service is told by its own channel, and every change is in one unit of work.
"""

from datetime import datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.cancel_booking import (
    CancelBooking,
    CancelBookingCommand,
    CancelBookingResult,
)
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.application.use_cases.respond_to_booking import (
    RespondToBooking,
    RespondToBookingCommand,
)
from diucs.domain.codes import BookingStatus, CancelReason, ReportSource
from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed
from tests.support.booking_rig import (
    ADVISOR,
    REPORTER,
    SERVICE_ID,
    at,
    request,
    sealer,
    seed_world,
)
from tests.support.neo4j import count_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")


def cancel_use_case(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime
) -> CancelBooking:
    return CancelBooking(
        uow_factory, DriverIdempotencyStore(driver), FixedClock(now), SequentialIds("cb")
    )


def cancel(
    key: str, booking_id: str, reason: CancelReason = CancelReason.CALLER_DECLINED
) -> CancelBookingCommand:
    return CancelBookingCommand(
        idempotency_key=key, actor=ADVISOR, booking_id=booking_id, reason=reason
    )


async def status_of(uow_factory: UnitOfWorkFactory, booking_id: str) -> BookingStatus:
    async with uow_factory() as uow:
        booking = await uow.bookings.get(booking_id)
    assert booking is not None
    return booking.status


async def test_cancelling_a_request_at_1420_is_cancelled_before_with_timers_and_b6(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "cx-1")
    result = await cancel_use_case(uow_factory, neo4j_driver, at(14, 20)).execute(
        cancel("cc-1", booked.booking_id)
    )
    assert isinstance(result, CancelBookingResult)
    assert result.status is BookingStatus.CANCELLED_BEFORE
    assert await status_of(uow_factory, booked.booking_id) is BookingStatus.CANCELLED_BEFORE
    async with uow_factory() as uow:
        timers = await uow.scheduled_work.for_about(booked.booking_id)
        messages = await uow.outbox.pending(200)
    assert sorted(t.status for t in timers) == ["cancelled", "cancelled"]
    types = [m.event_type for m in messages]
    assert "BookingCancelled" in types
    sent = [m.payload["message_id"] for m in messages if m.event_type == "SendMessage"]
    assert sent == ["B1", "B6"]


async def test_cancelling_a_confirmed_booking_gives_the_slot_back_on_the_board(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "cx-2")
    await RespondToBooking(
        uow_factory,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 19)),
        SequentialIds("rp"),
        sealer(),
    ).execute(
        RespondToBookingCommand(
            idempotency_key="rp-cx-2",
            actor=REPORTER,
            booking_id=booked.booking_id,
            decision="confirm",
            channel=ReportSource.TEXT,
        )
    )
    board_before = await QueryBoard(uow_factory, FixedClock(at(14, 20))).execute(
        QueryBoardQuery(actor=ADVISOR)
    )
    assert next(e for e in board_before.entries if e.service_id == SERVICE_ID).effective_available == 3
    result = await cancel_use_case(uow_factory, neo4j_driver, at(14, 21)).execute(
        cancel("cc-2", booked.booking_id)
    )
    assert result.status is BookingStatus.CANCELLED_AFTER
    board_after = await QueryBoard(uow_factory, FixedClock(at(14, 21))).execute(
        QueryBoardQuery(actor=ADVISOR)
    )
    assert next(e for e in board_after.entries if e.service_id == SERVICE_ID).effective_available == 4


async def test_cancelling_a_declined_booking_is_an_invalid_transition_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "cx-3")
    await RespondToBooking(
        uow_factory,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 19)),
        SequentialIds("rp"),
        sealer(),
    ).execute(
        RespondToBookingCommand(
            idempotency_key="rp-cx-3",
            actor=REPORTER,
            booking_id=booked.booking_id,
            decision="decline",
            channel=ReportSource.TEXT,
        )
    )
    before = await count_nodes(neo4j_driver, "AuditEvent")
    with pytest.raises(InvalidTransition):
        await cancel_use_case(uow_factory, neo4j_driver, at(14, 20)).execute(
            cancel("cc-3", booked.booking_id)
        )
    assert await status_of(uow_factory, booked.booking_id) is BookingStatus.DECLINED
    assert await count_nodes(neo4j_driver, "AuditEvent") == before


async def test_a_missing_reason_is_refused_and_a_reporter_is_not_allowed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "cx-4")
    use_case = cancel_use_case(uow_factory, neo4j_driver, at(14, 20))
    with pytest.raises(ValidationFailed):
        await use_case.execute(cancel("cc-4a", booked.booking_id, reason=None))  # type: ignore[arg-type]
    with pytest.raises(NotAllowed):
        await use_case.execute(
            CancelBookingCommand(
                idempotency_key="cc-4b",
                actor=REPORTER,
                booking_id=booked.booking_id,
                reason=CancelReason.OTHER_ROUTE_FOUND,
            )
        )
    assert await status_of(uow_factory, booked.booking_id) is BookingStatus.REQUESTED


async def test_a_replay_gives_one_audit_entry(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "cx-5")
    use_case = cancel_use_case(uow_factory, neo4j_driver, at(14, 20))
    first = await use_case.execute(cancel("cc-5", booked.booking_id))
    second = await use_case.execute(cancel("cc-5", booked.booking_id))
    assert first == second
    # one audit entry for the request and one for the cancellation
    assert await count_nodes(neo4j_driver, "AuditEvent") == 2
