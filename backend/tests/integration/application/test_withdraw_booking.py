"""Integration tests for WithdrawBooking, ReportNotReached, AcknowledgeWithdrawal and
EscalateWithdrawal (U21), against the real Neo4j.

Each booking is requested by RequestBooking and confirmed by RespondToBooking before the exception
is tested. Every assertion reads back through a fresh unit of work or the harness helpers. Sample
values only.
"""

from datetime import datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.application.use_cases.respond_to_booking import (
    RespondToBooking,
    RespondToBookingCommand,
)
from diucs.application.use_cases.withdraw_booking import (
    AcknowledgeWithdrawal,
    AcknowledgeWithdrawalCommand,
    EscalateWithdrawal,
    EscalateWithdrawalCommand,
    ReportNotReached,
    ReportNotReachedCommand,
    WithdrawBooking,
    WithdrawBookingCommand,
)
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import (
    BookingStatus,
    NotReachedReason,
    ReportSource,
    WithdrawReason,
)
from diucs.domain.errors import InvalidTransition, NotAllowed
from diucs.domain.model.booking import Booking
from tests.support.booking_rig import (
    ADVISOR,
    OTHER_REPORTER,
    REPORTER,
    SERVICE_ID,
    at,
    request,
    sealer,
    seed_world,
)
from tests.support.neo4j import node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _driver_idem(driver: AsyncDriver) -> DriverIdempotencyStore:
    return DriverIdempotencyStore(driver)


async def _confirmed(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, key: str, *, at_time: datetime
) -> str:
    """Request a booking, then confirm it as the service at `at_time`; returns the booking id."""
    booked = await request(uow_factory, driver, key)
    await RespondToBooking(
        uow_factory,
        _driver_idem(driver),
        FixedClock(at_time),
        SequentialIds(f"rp-{key}"),
        sealer(),
    ).execute(
        RespondToBookingCommand(
            idempotency_key=f"rp-{key}",
            actor=REPORTER,
            booking_id=booked.booking_id,
            decision="confirm",
            channel=ReportSource.TEXT,
        )
    )
    return booked.booking_id


def withdraw_use_case(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime
) -> WithdrawBooking:
    return WithdrawBooking(
        uow_factory, _driver_idem(driver), FixedClock(now), SequentialIds(f"wd-{now.isoformat()}")
    )


async def booking_of(uow_factory: UnitOfWorkFactory, booking_id: str) -> Booking:
    async with uow_factory() as uow:
        booking = await uow.bookings.get(booking_id)
    assert booking is not None
    return booking


async def event_count(uow_factory: UnitOfWorkFactory, event_type: str) -> int:
    async with uow_factory() as uow:
        messages = await uow.outbox.pending(200)
    return sum(1 for message in messages if message.event_type == event_type)


async def test_withdrawing_for_staffing_at_1441_is_stored_withdrawn_and_escalates_at_1451(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _confirmed(uow_factory, neo4j_driver, "wd-1", at_time=at(14, 19))
    result = await withdraw_use_case(uow_factory, neo4j_driver, at(14, 41)).execute(
        WithdrawBookingCommand(
            idempotency_key="wd-1",
            actor=REPORTER,
            booking_id=booking_id,
            reason=WithdrawReason.STAFFING,
        )
    )
    assert result.status is BookingStatus.WITHDRAWN
    assert result.escalation_due_at == at(14, 51)
    booking = await booking_of(uow_factory, booking_id)
    assert booking.status is BookingStatus.WITHDRAWN
    assert booking.reason == WithdrawReason.STAFFING.value
    task = await node_props(neo4j_driver, "Task", id=booking_id)
    assert task["status"] == "cancelled"
    assert task["businessStatus"] == "withdrawn"
    assert await event_count(uow_factory, "BookingWithdrawn") == 1
    (escalation,) = await _works(uow_factory, booking_id)
    assert escalation.due_at == at(14, 51)
    assert escalation.status == SCHEDULED


async def test_acknowledging_at_1445_cancels_the_escalation_which_then_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _confirmed(uow_factory, neo4j_driver, "wd-2", at_time=at(14, 19))
    await withdraw_use_case(uow_factory, neo4j_driver, at(14, 41)).execute(
        WithdrawBookingCommand(
            idempotency_key="wd-2",
            actor=REPORTER,
            booking_id=booking_id,
            reason=WithdrawReason.STAFFING,
        )
    )
    ack = await AcknowledgeWithdrawal(
        uow_factory, _driver_idem(neo4j_driver), FixedClock(at(14, 45))
    ).execute(
        AcknowledgeWithdrawalCommand(idempotency_key="ack-2", actor=ADVISOR, booking_id=booking_id)
    )
    assert ack.cancelled_escalation is True
    (work,) = await _works(uow_factory, booking_id)
    assert work.status == "cancelled"
    async with uow_factory() as uow:
        cancel_messages = [
            m
            for m in await uow.outbox.pending(200)
            if m.event_type == "CancelWork" and m.payload["work_id"] == work.id
        ]
    assert len(cancel_messages) == 1

    # The scheduled time comes: the cancelled escalation writes nothing.
    outcome = await EscalateWithdrawal(uow_factory, FixedClock(at(14, 51))).execute(
        EscalateWithdrawalCommand(work_id=work.id, booking_id=booking_id)
    )
    assert outcome.acted is False
    assert await event_count(uow_factory, "WithdrawalEscalated") == 0


async def test_an_unacknowledged_withdrawal_escalates_once_even_if_delivered_twice(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _confirmed(uow_factory, neo4j_driver, "wd-3", at_time=at(14, 19))
    await withdraw_use_case(uow_factory, neo4j_driver, at(14, 41)).execute(
        WithdrawBookingCommand(
            idempotency_key="wd-3",
            actor=REPORTER,
            booking_id=booking_id,
            reason=WithdrawReason.STAFFING,
        )
    )
    (work,) = await _works(uow_factory, booking_id)
    escalate = EscalateWithdrawal(uow_factory, FixedClock(at(14, 51)))
    command = EscalateWithdrawalCommand(work_id=work.id, booking_id=booking_id)
    first = await escalate.execute(command)
    second = await escalate.execute(command)
    assert first.acted is True
    assert second.acted is False
    assert await event_count(uow_factory, "WithdrawalEscalated") == 1
    done = await _works(uow_factory, booking_id)
    assert [w.status for w in done] == ["done"]


async def test_reporting_not_reached_no_answer_stores_not_reached_and_no_timer(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _confirmed(uow_factory, neo4j_driver, "wd-4", at_time=at(14, 19))
    result = await ReportNotReached(
        uow_factory, _driver_idem(neo4j_driver), FixedClock(at(14, 40))
    ).execute(
        ReportNotReachedCommand(
            idempotency_key="nr-4",
            actor=REPORTER,
            booking_id=booking_id,
            reason=NotReachedReason.NO_ANSWER,
        )
    )
    assert result.status is BookingStatus.NOT_REACHED
    booking = await booking_of(uow_factory, booking_id)
    assert booking.status is BookingStatus.NOT_REACHED
    task = await node_props(neo4j_driver, "Task", id=booking_id)
    assert task["status"] == "failed"
    assert await event_count(uow_factory, "BookingNotReached") == 1
    assert await _works(uow_factory, booking_id) == []


async def test_withdrawing_a_requested_booking_is_an_invalid_transition_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "wd-5")
    with pytest.raises(InvalidTransition):
        await withdraw_use_case(uow_factory, neo4j_driver, at(14, 30)).execute(
            WithdrawBookingCommand(
                idempotency_key="wd-5",
                actor=REPORTER,
                booking_id=booked.booking_id,
                reason=WithdrawReason.OTHER,
            )
        )
    booking = await booking_of(uow_factory, booked.booking_id)
    assert booking.status is BookingStatus.REQUESTED
    assert await event_count(uow_factory, "BookingWithdrawn") == 0
    assert await _works(uow_factory, booked.booking_id) == []


async def test_the_query_board_shows_the_figure_again_after_a_withdrawal(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _confirmed(uow_factory, neo4j_driver, "wd-6", at_time=at(14, 19))
    board = await QueryBoard(uow_factory, FixedClock(at(14, 20))).execute(
        QueryBoardQuery(actor=ADVISOR)
    )
    assert next(e for e in board.entries if e.service_id == SERVICE_ID).effective_available == 3
    await withdraw_use_case(uow_factory, neo4j_driver, at(14, 41)).execute(
        WithdrawBookingCommand(
            idempotency_key="wd-6",
            actor=REPORTER,
            booking_id=booking_id,
            reason=WithdrawReason.NOW_FULL,
        )
    )
    board = await QueryBoard(uow_factory, FixedClock(at(14, 42))).execute(
        QueryBoardQuery(actor=ADVISOR)
    )
    assert next(e for e in board.entries if e.service_id == SERVICE_ID).effective_available == 4


async def test_a_reporter_of_another_service_cannot_withdraw_the_booking(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _confirmed(uow_factory, neo4j_driver, "wd-7", at_time=at(14, 19))
    with pytest.raises(NotAllowed):
        await withdraw_use_case(uow_factory, neo4j_driver, at(14, 41)).execute(
            WithdrawBookingCommand(
                idempotency_key="wd-7",
                actor=OTHER_REPORTER,
                booking_id=booking_id,
                reason=WithdrawReason.STAFFING,
            )
        )
    booking = await booking_of(uow_factory, booking_id)
    assert booking.status is BookingStatus.CONFIRMED
    assert await event_count(uow_factory, "BookingWithdrawn") == 0


async def _works(uow_factory: UnitOfWorkFactory, booking_id: str) -> list[ScheduledWork]:
    async with uow_factory() as uow:
        return await uow.scheduled_work.for_about(booking_id, WorkKind.WITHDRAWAL_ESCALATE)


async def test_a_second_acknowledgement_with_a_new_key_writes_no_second_audit_entry(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    """R17: the advisor acknowledges again (a new key): 200 with nothing cancelled, and one
    acknowledgement in the audit log, not two."""
    await seed_world(uow_factory, neo4j_driver)
    booking_id = await _confirmed(uow_factory, neo4j_driver, "wd-3", at_time=at(14, 19))
    await withdraw_use_case(uow_factory, neo4j_driver, at(14, 41)).execute(
        WithdrawBookingCommand(
            idempotency_key="wd-3",
            actor=REPORTER,
            booking_id=booking_id,
            reason=WithdrawReason.STAFFING,
        )
    )
    first = await AcknowledgeWithdrawal(
        uow_factory, _driver_idem(neo4j_driver), FixedClock(at(14, 45))
    ).execute(
        AcknowledgeWithdrawalCommand(idempotency_key="ack-3a", actor=ADVISOR, booking_id=booking_id)
    )
    second = await AcknowledgeWithdrawal(
        uow_factory, _driver_idem(neo4j_driver), FixedClock(at(14, 46))
    ).execute(
        AcknowledgeWithdrawalCommand(idempotency_key="ack-3b", actor=ADVISOR, booking_id=booking_id)
    )
    assert first.cancelled_escalation is True
    assert second.cancelled_escalation is False
    async with uow_factory() as uow:
        records = await uow.audit.records_for(booking_id)
    acknowledgements = [r for r in records if r.entry.use_case == "AcknowledgeWithdrawal"]
    assert len(acknowledgements) == 1
