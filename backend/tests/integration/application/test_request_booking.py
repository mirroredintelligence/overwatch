"""Integration tests for RequestBooking (U17), against the real Neo4j the harness starts.

An advisor asks one service to take the patient on an open case. The booking is stored as requested,
with its audit entry, its outbound request and its two timers, in one unit of work. Every assertion
reads back through a fresh unit of work or the harness helpers. Values are the sample values of the
prompt: no patient data.
"""

import random
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.query_board import QueryBoard
from diucs.application.use_cases.request_booking import (
    RequestBooking,
    RequestBookingCommand,
    RequestBookingResult,
)
from diucs.domain.codes import (
    AgeBand,
    BookingStatus,
    Channel,
    NeedCategory,
    ReferrerType,
    Role,
    Urgency,
)
from diucs.domain.errors import Conflict, NotAllowed, ValidationFailed
from diucs.domain.model.case import Case
from tests.support.ladder_rig import PHONE_HASH_1, reporter, seed_people, seed_report
from tests.support.link_rig import ucr_west
from tests.support.neo4j import count_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE_ID = "ucr-west"
CASE_ID = "case-1001"
# A case reference is four digits with no leading zero (case_repository._check_reference).
REFERENCES = {"case-1001": "1001", "case-1002": "1002", "case-1003": "1003", "case-closed": "1004"}
REQUESTED_AT = datetime(2026, 10, 29, 14, 16, tzinfo=UTC)
# The sample full postcode. A case stores its district only (DEC-067 item 1), so open_case holds
# DISTRICT; the full postcode must appear in no outbox payload.
POSTCODE = "DT4 8XX"
DISTRICT = "DT4"
LINK_HOST = "https://dorset.diucs.example"
SECRETS = FixedSecretStore({LINK_TOKEN_SECRET: b"link-token-test-secret-0123456789abcdef"})

ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
CLINICAL = Actor(
    role=Role.CLINICAL,
    practitioner_id="clinical-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-1",
    device_id=None,
    channel="text",
    service_ids=frozenset({SERVICE_ID}),
)


def open_case(case_id: str = CASE_ID, **changes: Any) -> Case:
    case = Case(
        id=case_id,
        reference=REFERENCES[case_id],
        referrer_type=ReferrerType.GP,
        age_band=AgeBand.A80_PLUS,
        postcode=DISTRICT,
        needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(),
        opened_at=REQUESTED_AT,
    )
    return replace(case, **changes)


def request_booking(
    uow_factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    *,
    link_tokens_fail: bool = False,
    rng_seed: int = 7,
) -> RequestBooking:
    clock = FixedClock(REQUESTED_AT)

    def tokens(repo: Any) -> Any:
        if link_tokens_fail:

            class _Refusing:
                def issue(self, *args: Any, **kwargs: Any) -> Any:
                    raise RuntimeError("the link service is down")

            return _Refusing()
        return LinkTokenService(repo, SECRETS, clock)

    return RequestBooking(
        uow_factory,
        DriverIdempotencyStore(driver),
        tokens,
        clock,
        SequentialIds("bk"),
        random.Random(rng_seed),
        QueryBoard(uow_factory, clock),
        link_base_url_for=lambda scope: LINK_HOST,
    )


def command(key: str, actor: Actor = ADVISOR, case_id: str = CASE_ID) -> RequestBookingCommand:
    return RequestBookingCommand(
        idempotency_key=key, actor=actor, case_id=case_id, service_id=SERVICE_ID
    )


@pytest.fixture
async def seeded(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    """UCR West accepting 4 (a report an hour earlier), one text reporter, and an open case."""
    await ensure_audit_head(neo4j_driver)
    async with uow_factory() as uow:
        await uow.services.save(ucr_west(SERVICE_ID))
        await uow.cases.add(open_case())
        await uow.commit()
    await seed_people(uow_factory, reporter(1, PHONE_HASH_1, service_id=SERVICE_ID))
    await seed_report(uow_factory, REQUESTED_AT.replace(hour=13), service_id=SERVICE_ID, value=4)


async def _reporter_on(uow_factory: UnitOfWorkFactory, channel: Channel) -> None:
    """The service's one reporter role, sent on this channel (the role decides the message)."""
    _, role = reporter(1, PHONE_HASH_1, service_id=SERVICE_ID)
    async with uow_factory() as uow:
        await uow.people.save_role(replace(role, channel=channel))
        await uow.commit()


async def test_a_request_at_1416_is_stored_requested_with_reply_by_1426(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    result = await request_booking(uow_factory, neo4j_driver).execute(command("req-1"))
    assert isinstance(result, RequestBookingResult)
    assert result.reply_by == datetime(2026, 10, 29, 14, 26, tzinfo=UTC)
    async with uow_factory() as uow:
        booking = await uow.bookings.get(result.booking_id)
    assert booking is not None
    assert booking.status is BookingStatus.REQUESTED
    assert booking.reply_by == datetime(2026, 10, 29, 14, 26, tzinfo=UTC)
    assert await count_nodes(neo4j_driver, "Task") == 1


async def test_two_timers_are_scheduled_at_1421_and_1426_with_schedule_messages(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    result = await request_booking(uow_factory, neo4j_driver).execute(command("req-2"))
    async with uow_factory() as uow:
        work = await uow.scheduled_work.for_about(result.booking_id)
        messages = await uow.outbox.pending(100)
    due = sorted((w.kind.value, w.due_at, w.status) for w in work)
    assert due == [
        ("booking-expire", datetime(2026, 10, 29, 14, 26, tzinfo=UTC), "scheduled"),
        ("booking-phone-prompt", datetime(2026, 10, 29, 14, 21, tzinfo=UTC), "scheduled"),
    ]
    assert [m.event_type for m in messages if m.topic == "scheduled.work"] == [
        "ScheduleWork",
        "ScheduleWork",
    ]


async def test_the_request_writes_one_audit_entry_and_the_b1_and_booking_events(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await request_booking(uow_factory, neo4j_driver).execute(command("req-3"))
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1
    async with uow_factory() as uow:
        messages = await uow.outbox.pending(100)
    types = sorted(m.event_type for m in messages)
    assert "BookingRequested" in types
    sent = [m for m in messages if m.event_type == "SendMessage"]
    assert len(sent) == 1
    assert sent[0].payload["message_id"] == "B1"


async def test_a_second_request_for_the_same_service_conflicts_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await request_booking(uow_factory, neo4j_driver).execute(command("req-4a"))
    before = await count_nodes(neo4j_driver, "Task")
    await seed_case(uow_factory, open_case("case-1002"))
    with pytest.raises(Conflict):
        await request_booking(uow_factory, neo4j_driver).execute(
            command("req-4b", case_id="case-1002")
        )
    assert await count_nodes(neo4j_driver, "Task") == before


async def test_after_the_first_is_declined_a_new_request_succeeds(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    first = await request_booking(uow_factory, neo4j_driver).execute(command("req-5a"))
    async with uow_factory() as uow:
        booking = await uow.bookings.get(first.booking_id)
        assert booking is not None
        await uow.bookings.save(booking.with_status(BookingStatus.DECLINED, REQUESTED_AT))
        await uow.commit()
    await seed_case(uow_factory, open_case("case-1003"))
    second = await request_booking(uow_factory, neo4j_driver).execute(
        command("req-5b", case_id="case-1003")
    )
    assert second.booking_id != first.booking_id


async def test_a_closed_case_is_a_validation_failure_and_a_reporter_is_not_allowed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await seed_case(uow_factory, open_case("case-closed", closed_at=REQUESTED_AT))
    with pytest.raises(ValidationFailed):
        await request_booking(uow_factory, neo4j_driver).execute(
            command("req-6a", case_id="case-closed")
        )
    with pytest.raises(NotAllowed):
        await request_booking(uow_factory, neo4j_driver).execute(command("req-6b", actor=REPORTER))
    assert await count_nodes(neo4j_driver, "Task") == 0


@pytest.mark.parametrize(
    ("channel", "message_id"), [(Channel.EMAIL, "B2"), (Channel.PUSH, "B3"), (Channel.TEXT, "B1")]
)
async def test_each_channel_gets_its_booking_message(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seeded: None,
    channel: Channel,
    message_id: str,
) -> None:
    await _reporter_on(uow_factory, channel)
    await request_booking(uow_factory, neo4j_driver).execute(command(f"req-7-{channel}"))
    async with uow_factory() as uow:
        sent = [m for m in await uow.outbox.pending(100) if m.event_type == "SendMessage"]
    assert [m.payload["message_id"] for m in sent] == [message_id]
    if channel is Channel.EMAIL:
        assert sent[0].payload.get("subject")


async def test_no_stored_text_or_outbox_payload_holds_the_postcode(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await request_booking(uow_factory, neo4j_driver).execute(command("req-8"))
    async with uow_factory() as uow:
        messages = await uow.outbox.pending(100)
    assert all(POSTCODE not in repr(m.payload) for m in messages)
    assert all(POSTCODE not in str(m.payload) for m in messages)


async def test_the_same_key_twice_gives_one_booking_and_one_audit_entry(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    first = await request_booking(uow_factory, neo4j_driver).execute(command("req-9"))
    second = await request_booking(uow_factory, neo4j_driver).execute(command("req-9"))
    assert first == second
    assert await count_nodes(neo4j_driver, "Task") == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1


async def test_a_failure_after_the_booking_is_saved_leaves_no_task_outbox_or_timer(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    before = (
        await count_nodes(neo4j_driver, "Task"),
        await count_nodes(neo4j_driver, "ScheduledWork"),
        await count_nodes(neo4j_driver, "OutboxMessage"),
    )
    with pytest.raises(RuntimeError):
        await request_booking(uow_factory, neo4j_driver, link_tokens_fail=True).execute(
            command("req-10")
        )
    after = (
        await count_nodes(neo4j_driver, "Task"),
        await count_nodes(neo4j_driver, "ScheduledWork"),
        await count_nodes(neo4j_driver, "OutboxMessage"),
    )
    assert after == before


async def seed_case(uow_factory: UnitOfWorkFactory, case: Case) -> None:
    async with uow_factory() as uow:
        await uow.cases.add(case)
        await uow.commit()
