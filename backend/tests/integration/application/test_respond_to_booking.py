"""Integration tests for RespondToBooking and SetDeclineReason (U18), against the real Neo4j.

The bookings are created by RequestBooking at 14:16, as the service is asked. Every assertion reads
back through a fresh unit of work or the harness helpers. Sample values only.
"""

from datetime import datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.application.use_cases.respond_to_booking import (
    RespondToBooking,
    RespondToBookingCommand,
    RespondToBookingResult,
    SetDeclineReason,
    SetDeclineReasonCommand,
)
from diucs.domain.codes import BookingStatus, DeclineReason, ReportSource, Role
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed
from diucs.domain.model.booking import Booking
from tests.support.booking_rig import (
    ADVISOR,
    OTHER_REPORTER,
    REPORTER,
    SERVICE_ID,
    at,
    open_case,
    request,
    sealer,
    seed_world,
)
from tests.support.neo4j import count_nodes, node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")


def respond_use_case(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime
) -> RespondToBooking:
    return RespondToBooking(
        uow_factory,
        DriverIdempotencyStore(driver),
        FixedClock(now),
        SequentialIds("rp"),
        sealer(),
    )


def decline_reason_use_case(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime
) -> SetDeclineReason:
    return SetDeclineReason(uow_factory, DriverIdempotencyStore(driver), FixedClock(now))


def reply(
    key: str,
    booking_id: str,
    decision: str,
    *,
    reason: DeclineReason | None = None,
    actor: Actor = REPORTER,
) -> RespondToBookingCommand:
    return RespondToBookingCommand(
        idempotency_key=key,
        actor=actor,
        booking_id=booking_id,
        decision=decision,  # type: ignore[arg-type]
        reason=reason,
        channel=ReportSource.TEXT,
    )


async def booking_of(uow_factory: UnitOfWorkFactory, booking_id: str) -> Booking:
    async with uow_factory() as uow:
        booking = await uow.bookings.get(booking_id)
    assert booking is not None
    return booking


async def sent_messages(uow_factory: UnitOfWorkFactory) -> list[str]:
    async with uow_factory() as uow:
        messages = await uow.outbox.pending(200)
    return [m.payload["message_id"] for m in messages if m.event_type == "SendMessage"]


async def test_a_confirmation_at_1419_is_stored_confirmed_and_echoed_as_b4(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "rq-1")
    result = await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-1", booked.booking_id, "confirm")
    )
    assert isinstance(result, RespondToBookingResult)
    assert result.status is BookingStatus.CONFIRMED
    assert result.already_final is False
    booking = await booking_of(uow_factory, booked.booking_id)
    assert booking.status is BookingStatus.CONFIRMED
    assert booking.responded_at == at(14, 19)
    task = await node_props(neo4j_driver, "Task", id=booked.booking_id)
    assert task["status"] == "accepted"
    assert task["businessStatus"] == "confirmed"
    assert "B4" in await sent_messages(uow_factory)
    async with uow_factory() as uow:
        events = [m.event_type for m in await uow.outbox.pending(200)]
    assert "BookingResponded" in events


async def test_the_timers_are_cancelled_and_the_query_board_shows_three_free(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "rq-2")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-2", booked.booking_id, "confirm")
    )
    async with uow_factory() as uow:
        timers = await uow.scheduled_work.for_about(booked.booking_id)
        messages = await uow.outbox.pending(200)
    assert sorted(t.status for t in timers) == ["cancelled", "cancelled"]
    assert [m.event_type for m in messages if m.topic == "scheduled.work"].count("CancelWork") == 2
    board = await QueryBoard(uow_factory, FixedClock(at(14, 20))).execute(
        QueryBoardQuery(actor=ADVISOR)
    )
    entry = next(e for e in board.entries if e.service_id == SERVICE_ID)
    assert entry.effective_available == 3
    assert entry.pending == 0


async def test_a_decline_with_a_reason_is_stored_and_echoed_as_b5(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "rq-3")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-3", booked.booking_id, "decline", reason=DeclineReason.OUTSIDE_CRITERIA)
    )
    booking = await booking_of(uow_factory, booked.booking_id)
    assert booking.status is BookingStatus.DECLINED
    assert booking.reason == DeclineReason.OUTSIDE_CRITERIA.value
    assert "B5" in await sent_messages(uow_factory)


async def test_a_decline_without_a_reason_takes_one_later_and_a_second_reason_conflicts(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "rq-4")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-4", booked.booking_id, "decline")
    )
    later = SetDeclineReasonCommand(
        idempotency_key="dr-4",
        actor=REPORTER,
        booking_id=booked.booking_id,
        reason=DeclineReason.FULL,
    )
    await decline_reason_use_case(uow_factory, neo4j_driver, at(14, 21)).execute(later)
    assert (await booking_of(uow_factory, booked.booking_id)).reason == "full"
    with pytest.raises(Conflict):
        await decline_reason_use_case(uow_factory, neo4j_driver, at(14, 22)).execute(
            SetDeclineReasonCommand(
                idempotency_key="dr-4b",
                actor=REPORTER,
                booking_id=booked.booking_id,
                reason=DeclineReason.OTHER,
            )
        )
    assert (await booking_of(uow_factory, booked.booking_id)).reason == "full"


async def test_a_reply_to_a_confirmed_booking_is_invalid_and_an_expired_one_is_already_final(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    confirmed = await request(uow_factory, neo4j_driver, "rq-5a")
    await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
        reply("rp-5a", confirmed.booking_id, "confirm")
    )
    with pytest.raises(InvalidTransition):
        await respond_use_case(uow_factory, neo4j_driver, at(14, 20)).execute(
            reply("rp-5b", confirmed.booking_id, "decline")
        )
    # The service has no open request now, so a second one can be made and left to expire.
    async with uow_factory() as uow:
        await uow.cases.add(open_case("case-1002"))
        await uow.commit()
    second = await request(uow_factory, neo4j_driver, "rq-5c", now=at(14, 30), case_id="case-1002")
    async with uow_factory() as uow:
        waiting = await uow.bookings.get(second.booking_id)
        assert waiting is not None
        await uow.bookings.save(waiting.with_status(BookingStatus.EXPIRED, at(14, 40)))
        await uow.commit()
    before = await count_nodes(neo4j_driver, "AuditEvent")
    result = await respond_use_case(uow_factory, neo4j_driver, at(14, 41)).execute(
        reply("rp-5d", second.booking_id, "confirm")
    )
    assert result.already_final is True
    assert result.status is BookingStatus.EXPIRED
    assert await count_nodes(neo4j_driver, "AuditEvent") == before


async def test_a_reply_from_another_service_is_not_allowed_and_names_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "rq-6")
    with pytest.raises(NotAllowed) as refused:
        await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
            reply("rp-6", booked.booking_id, "confirm", actor=OTHER_REPORTER)
        )
    assert booked.reference not in str(refused.value)
    assert (await booking_of(uow_factory, booked.booking_id)).status is BookingStatus.REQUESTED


async def test_a_staff_role_cannot_answer_for_a_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "rq-6b")
    assert ADVISOR.role is Role.ADVISOR
    with pytest.raises(NotAllowed):
        await respond_use_case(uow_factory, neo4j_driver, at(14, 19)).execute(
            reply("rp-6b", booked.booking_id, "confirm", actor=ADVISOR)
        )


async def test_a_replay_gives_one_audit_entry_and_one_echo(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "rq-7")
    use_case = respond_use_case(uow_factory, neo4j_driver, at(14, 19))
    first = await use_case.execute(reply("rp-7", booked.booking_id, "confirm"))
    second = await use_case.execute(reply("rp-7", booked.booking_id, "confirm"))
    assert first == second
    assert await sent_messages(uow_factory) == ["B1", "B4"]
    assert await count_nodes(neo4j_driver, "AuditEvent") == 2  # the request and the reply
