"""Integration tests for booking replies by text in HandleInboundText (U22), against the real Neo4j.

The bookings are requested by RequestBooking and the phone is the reporter of the service (and, for
the two-booking test, of a second service). Every assertion reads back through a fresh unit of work
or the harness helpers. Sample values only: the phone is a hash, no number is stored.
"""

import dataclasses
from datetime import datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.booking_timers import ExpireBooking, ExpireBookingCommand
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity
from diucs.application.use_cases.handle_inbound_text import (
    HandleInboundText,
    HandleInboundTextCommand,
    HandleInboundTextResult,
)
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.application.use_cases.request_booking import RequestBookingCommand
from diucs.application.use_cases.respond_to_booking import (
    RespondToBooking,
    SetDeclineReason,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import BookingStatus, Channel, DeclineReason
from diucs.domain.model.booking import Booking
from diucs.domain.model.people import PractitionerRole
from tests.support.booking_rig import (
    ADVISOR,
    REQUESTED_AT,
    SERVICE_ID,
    at,
    request,
    request_use_case,
    sealer,
    seed_world,
)
from tests.support.ladder_rig import PHONE_HASH_1, seed_report
from tests.support.link_rig import ucr_west
from tests.support.neo4j import node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")

EAST = "ucr-east"
PHONE_HASH = PHONE_HASH_1
PROMPT_ROLE_WEST = "role-1"


def handler(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime
) -> HandleInboundText:
    clock = FixedClock(now)
    store = DriverIdempotencyStore(driver)
    return HandleInboundText(
        uow_factory,
        clock,
        SequentialIds(f"in-{now.isoformat()}"),
        store,
        InMemoryCache(FixedClock(now)),
        ReportCapacity(uow_factory, clock, SequentialIds(f"rc-{now.isoformat()}"), store),
        ConfirmCapacity(uow_factory, clock, SequentialIds(f"cc-{now.isoformat()}"), store),
        respond_to_booking=RespondToBooking(
            uow_factory,
            store,
            clock,
            SequentialIds(f"rp-{now.isoformat()}"),
            sealer(),
        ),
        set_decline_reason=SetDeclineReason(uow_factory, store, clock),
    )


async def say(
    uow_factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    text: str,
    at_time: datetime,
    key: str,
) -> HandleInboundTextResult:
    return await handler(uow_factory, driver, at_time).execute(
        HandleInboundTextCommand(
            idempotency_key=key,
            from_phone_hash=PHONE_HASH,
            text=text,
            received_at=at_time,
        )
    )


async def booking_of(uow_factory: UnitOfWorkFactory, booking_id: str) -> Booking:
    async with uow_factory() as uow:
        booking = await uow.bookings.get(booking_id)
    assert booking is not None
    return booking


async def sent_message_ids(uow_factory: UnitOfWorkFactory) -> list[str]:
    async with uow_factory() as uow:
        messages = await uow.outbox.pending(200)
    return [m.payload["message_id"] for m in messages if m.event_type == "SendMessage"]


async def _request_for(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, key: str, service_id: str, case_id: str
) -> str:
    result = await request_use_case(uow_factory, driver, REQUESTED_AT, prefix=f"bk-{key}").execute(
        RequestBookingCommand(
            idempotency_key=key, actor=ADVISOR, case_id=case_id, service_id=service_id
        )
    )
    return result.booking_id


async def _seed_phone_on_east(uow_factory: UnitOfWorkFactory) -> None:
    """The same phone is also a reporter of UCR East, which has its own figure."""
    west = await _west_role(uow_factory)
    east = dataclasses.replace(west, id="role-east", service_id=EAST)
    async with uow_factory() as uow:
        await uow.services.save(ucr_west(EAST, name="UCR East"))
        await uow.people.save_role(east)
        await uow.commit()
    await seed_report(uow_factory, at(13, 0), service_id=EAST, value=4, report_id="seed-east")


async def _west_role(uow_factory: UnitOfWorkFactory) -> PractitionerRole:
    async with uow_factory() as uow:
        role = await uow.people.get_role(PROMPT_ROLE_WEST)
    assert role is not None
    return role


async def test_a_confirmed_text_with_one_open_booking_confirms_it_and_echoes_b4(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "u22-1")
    result = await say(uow_factory, neo4j_driver, "CONFIRMED", at(14, 19), "in-u22-1")
    assert result.outcome == "booking-confirmed"
    assert result.service_ids == (SERVICE_ID,)
    booking = await booking_of(uow_factory, booked.booking_id)
    assert booking.status is BookingStatus.CONFIRMED
    assert "B4" in await sent_message_ids(uow_factory)


async def test_confirmed_with_a_reference_is_matched_by_it(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "u22-2")
    booking = await booking_of(uow_factory, booked.booking_id)
    result = await say(
        uow_factory, neo4j_driver, f"confirmed {booking.reference}", at(14, 19), "in-u22-2"
    )
    assert result.outcome == "booking-confirmed"
    assert (await booking_of(uow_factory, booked.booking_id)).status is BookingStatus.CONFIRMED


async def test_a_bare_confirmed_with_two_open_bookings_lists_the_references_and_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    await _seed_phone_on_east(uow_factory)
    west_id = await _request_for(uow_factory, neo4j_driver, "u22-3w", SERVICE_ID, "case-1001")
    east_id = await _request_for(uow_factory, neo4j_driver, "u22-3e", EAST, "case-1002")
    result = await say(uow_factory, neo4j_driver, "CONFIRMED", at(14, 19), "in-u22-3")
    assert result.outcome == "booking-ask-reference"
    assert (await booking_of(uow_factory, west_id)).status is BookingStatus.REQUESTED
    assert (await booking_of(uow_factory, east_id)).status is BookingStatus.REQUESTED
    assert "B7" in await sent_message_ids(uow_factory)


async def test_decline_then_a_two_a_minute_later_sets_outside_criteria(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "u22-4")
    await say(uow_factory, neo4j_driver, "DECLINE", at(14, 20), "in-u22-4a")
    result = await say(uow_factory, neo4j_driver, "2", at(14, 21), "in-u22-4b")
    assert result.outcome == "booking-reason-set"
    booking = await booking_of(uow_factory, booked.booking_id)
    assert booking.status is BookingStatus.DECLINED
    assert booking.reason == DeclineReason.OUTSIDE_CRITERIA.value
    assert "B5" in await sent_message_ids(uow_factory)


async def test_decline_then_a_two_after_fifteen_minutes_is_a_capacity_figure(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "u22-5")
    await say(uow_factory, neo4j_driver, "DECLINE", at(14, 20), "in-u22-5a")
    async with uow_factory() as uow:
        await uow.communications.add(
            Communication(
                id="prompt-u22-5",
                message_id="C1",
                channel=Channel.TEXT,
                recipient_role_id=PROMPT_ROLE_WEST,
                about_id=SERVICE_ID,
                payload_text="DIUCS: UCR West. We have 4 referrals in the next 2 hrs.",
                sent_at=at(14, 30),
                delivery_status="sent",
            )
        )
        await uow.commit()
    result = await say(uow_factory, neo4j_driver, "2", at(14, 35), "in-u22-5b")
    assert result.outcome != "booking-reason-set"
    booking = await booking_of(uow_factory, booked.booking_id)
    assert booking.reason is None
    async with uow_factory() as uow:
        latest = await uow.capacity.latest(SERVICE_ID)
    assert latest is not None
    assert latest.value == 2


async def test_a_confirmed_after_expiry_says_it_expired_and_books_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "u22-6")
    async with uow_factory() as uow:
        (expiry,) = await uow.scheduled_work.for_about(booked.booking_id, WorkKind.BOOKING_EXPIRE)
    await ExpireBooking(uow_factory, FixedClock(at(14, 26))).execute(
        ExpireBookingCommand(work_id=expiry.id, booking_id=booked.booking_id)
    )
    result = await say(uow_factory, neo4j_driver, "CONFIRMED", at(14, 27), "in-u22-6")
    assert result.outcome == "booking-expired"
    assert (await booking_of(uow_factory, booked.booking_id)).status is BookingStatus.EXPIRED
    assert "B9" in await sent_message_ids(uow_factory)


async def test_confirmed_with_nothing_waiting_says_so_and_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    result = await say(uow_factory, neo4j_driver, "CONFIRMED", at(14, 19), "in-u22-7")
    assert result.outcome == "booking-none"
    assert "B8" in await sent_message_ids(uow_factory)


async def test_a_text_from_an_unknown_phone_gets_no_reply_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "u22-8")
    result = await handler(uow_factory, neo4j_driver, at(14, 19)).execute(
        HandleInboundTextCommand(
            idempotency_key="in-u22-8",
            from_phone_hash="ef" * 32,
            text="CONFIRMED",
            received_at=at(14, 19),
        )
    )
    assert result.outcome == "dropped"
    assert await sent_message_ids(uow_factory) == []
    assert (await booking_of(uow_factory, booked.booking_id)).status is BookingStatus.REQUESTED


async def test_the_same_provider_message_twice_confirms_once(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    booked = await request(uow_factory, neo4j_driver, "u22-9")
    first = await say(uow_factory, neo4j_driver, "CONFIRMED", at(14, 19), "in-u22-9")
    second = await say(uow_factory, neo4j_driver, "CONFIRMED", at(14, 19), "in-u22-9")
    assert first.outcome == "booking-confirmed"
    assert second.replayed is True
    assert (await booking_of(uow_factory, booked.booking_id)).status is BookingStatus.CONFIRMED
    confirmed = await node_props(neo4j_driver, "Task", id=booked.booking_id)
    assert confirmed["businessStatus"] == "confirmed"
