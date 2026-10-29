"""Integration tests for the booking timers (U19), against the real Neo4j the harness starts.

The bookings are created by RequestBooking at 14:16. The phone prompt fires at 14:21 and the expiry
at 14:26. Every assertion reads back through a fresh unit of work or the harness helpers.
"""

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.scheduler.scheduled_work_consumer import ScheduledWorkDispatcher
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.booking_timers import (
    BookingPhonePrompt,
    BookingPhonePromptCommand,
    ExpireBooking,
    ExpireBookingCommand,
    booking_timer_handlers,
)
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.application.work import WorkKind
from diucs.domain.codes import BookingStatus
from tests.support.booking_rig import (
    ADVISOR,
    REQUESTED_AT,
    SERVICE_ID,
    at,
    open_case,
    request,
    seed_world,
)
from tests.support.neo4j import count_nodes, node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")

PROMPT_AT = at(14, 21)
EXPIRY_AT = at(14, 26)


async def work_for(uow_factory: UnitOfWorkFactory, booking_id: str, kind: WorkKind) -> str:
    async with uow_factory() as uow:
        found = await uow.scheduled_work.for_about(booking_id, kind)
    assert len(found) == 1
    return found[0].id


async def set_status(uow_factory: UnitOfWorkFactory, booking_id: str, target: BookingStatus) -> None:
    async with uow_factory() as uow:
        booking = await uow.bookings.get(booking_id)
        assert booking is not None
        await uow.bookings.save(booking.with_status(target, REQUESTED_AT))
        await uow.commit()


async def test_the_phone_prompt_on_a_requested_booking_emits_the_prompt_and_marks_the_work_done(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "tm-1")
    work_id = await work_for(uow_factory, booked.booking_id, WorkKind.BOOKING_PHONE_PROMPT)
    result = await BookingPhonePrompt(uow_factory, FixedClock(PROMPT_AT)).execute(
        BookingPhonePromptCommand(work_id=work_id, booking_id=booked.booking_id)
    )
    assert result.acted is True
    assert await count_nodes(neo4j_driver, "BookingPhonePrompt") == 1
    work = await node_props(neo4j_driver, "ScheduledWork", id=work_id)
    assert work["status"] == "done"


async def test_the_phone_prompt_on_a_confirmed_booking_emits_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "tm-2")
    await set_status(uow_factory, booked.booking_id, BookingStatus.CONFIRMED)
    work_id = await work_for(uow_factory, booked.booking_id, WorkKind.BOOKING_PHONE_PROMPT)
    result = await BookingPhonePrompt(uow_factory, FixedClock(PROMPT_AT)).execute(
        BookingPhonePromptCommand(work_id=work_id, booking_id=booked.booking_id)
    )
    assert result.acted is False
    assert await count_nodes(neo4j_driver, "BookingPhonePrompt") == 0


async def test_the_expiry_of_a_requested_booking_is_stored_expired_with_its_event_and_audit(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "tm-3")
    work_id = await work_for(uow_factory, booked.booking_id, WorkKind.BOOKING_EXPIRE)
    audit_before = await count_nodes(neo4j_driver, "AuditEvent")
    result = await ExpireBooking(uow_factory, FixedClock(EXPIRY_AT)).execute(
        ExpireBookingCommand(work_id=work_id, booking_id=booked.booking_id)
    )
    assert result.acted is True
    async with uow_factory() as uow:
        booking = await uow.bookings.get(booked.booking_id)
    assert booking is not None
    assert booking.status is BookingStatus.EXPIRED
    task = await node_props(neo4j_driver, "Task", id=booked.booking_id)
    assert task["status"] == "cancelled"
    assert task["businessStatus"] == "expired"
    assert await count_nodes(neo4j_driver, "BookingExpired") == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == audit_before + 1
    board = await QueryBoard(uow_factory, FixedClock(EXPIRY_AT)).execute(
        QueryBoardQuery(actor=ADVISOR)
    )
    assert next(e for e in board.entries if e.service_id == SERVICE_ID).pending == 0


async def test_the_expiry_of_a_declined_booking_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "tm-4")
    await set_status(uow_factory, booked.booking_id, BookingStatus.DECLINED)
    work_id = await work_for(uow_factory, booked.booking_id, WorkKind.BOOKING_EXPIRE)
    result = await ExpireBooking(uow_factory, FixedClock(EXPIRY_AT)).execute(
        ExpireBookingCommand(work_id=work_id, booking_id=booked.booking_id)
    )
    assert result.acted is False
    async with uow_factory() as uow:
        booking = await uow.bookings.get(booked.booking_id)
    assert booking is not None
    assert booking.status is BookingStatus.DECLINED
    assert await count_nodes(neo4j_driver, "BookingExpired") == 0


async def test_the_same_work_delivered_twice_emits_one_event(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "tm-5")
    work_id = await work_for(uow_factory, booked.booking_id, WorkKind.BOOKING_EXPIRE)
    use_case = ExpireBooking(uow_factory, FixedClock(EXPIRY_AT))
    first = await use_case.execute(ExpireBookingCommand(work_id=work_id, booking_id=booked.booking_id))
    second = await use_case.execute(
        ExpireBookingCommand(work_id=work_id, booking_id=booked.booking_id)
    )
    assert (first.acted, second.acted) == (True, False)
    assert await count_nodes(neo4j_driver, "BookingExpired") == 1


async def test_after_an_expiry_a_new_request_for_the_service_succeeds(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "tm-6a")
    work_id = await work_for(uow_factory, booked.booking_id, WorkKind.BOOKING_EXPIRE)
    await ExpireBooking(uow_factory, FixedClock(EXPIRY_AT)).execute(
        ExpireBookingCommand(work_id=work_id, booking_id=booked.booking_id)
    )
    async with uow_factory() as uow:
        await uow.cases.add(open_case("case-1002"))
        await uow.commit()
    second = await request(uow_factory, neo4j_driver, "tm-6b", now=at(14, 30), case_id="case-1002")
    assert second.booking_id != booked.booking_id


async def test_the_consumer_dispatch_routes_booking_expire_work_to_expire_booking(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "tm-7")
    async with uow_factory() as uow:
        work = (await uow.scheduled_work.for_about(booked.booking_id, WorkKind.BOOKING_EXPIRE))[0]
    handlers = booking_timer_handlers(
        BookingPhonePrompt(uow_factory, FixedClock(PROMPT_AT)),
        ExpireBooking(uow_factory, FixedClock(EXPIRY_AT)),
    )
    dispatcher = ScheduledWorkDispatcher(handlers)
    assert WorkKind.BOOKING_EXPIRE in dispatcher.kinds
    await dispatcher(work)
    assert await count_nodes(neo4j_driver, "BookingExpired") == 1
    async with uow_factory() as uow:
        stored = await uow.bookings.get(booked.booking_id)
    assert stored is not None
    assert stored.status is BookingStatus.EXPIRED
