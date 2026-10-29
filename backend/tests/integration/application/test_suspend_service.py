"""Integration tests for SuspendService and ResumeService (U36), against the real Neo4j.

UCR East has a report at 13:00, a text reporter, and two requested bookings with their timers and a
prompt-due job. The suspension is checked in Neo4j: the flag, the expired requests, the cancelled
timers, the K4 echo to the service and the StatusChanged event. K4 needs the tenant's wording, which
is read through the real tenant directory, seeded here with the sample wording.
"""

import os
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.driver import Neo4jConnection
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.application.use_cases.suspend_service import (
    ResumeService,
    ResumeServiceCommand,
    SuspendService,
    SuspendServiceCommand,
    SuspendServiceResult,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import BookingStatus, Status
from diucs.domain.errors import Conflict, NotAllowed, ValidationFailed
from diucs.domain.model.booking import Booking
from tests.integration.graph_store.test_tenant_directory import seed_tenant
from tests.support.booking_rig import ADVISOR, LEAD, SECRETS, at, open_case, seed_world
from tests.support.ladder_rig import PHONE_HASH_1, reporter, seed_people
from tests.support.link_rig import ucr_west
from tests.support.neo4j import count_nodes
from tests.support.tenant_samples import SAMPLE_WORDING, make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

EAST = "ucr-east"
PROMPT_DUE_AT = at(15, 0)


@pytest_asyncio.fixture(loop_scope="session")
async def connection() -> AsyncIterator[Neo4jConnection]:
    conn = Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )
    await conn.open()
    try:
        yield conn
    finally:
        await conn.close()


async def seed_east(uow_factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str) -> list[str]:
    """UCR East with a report and a text reporter, two requested bookings with their timers, and
    a prompt-due job. Returns the two booking ids. The tenant's wording is seeded too."""
    await seed_world(uow_factory, driver)
    await seed_people(uow_factory, reporter(2, PHONE_HASH_1, service_id=EAST))
    await seed_tenant(driver, make_tenant(id=tenant, values=SAMPLE_WORDING))
    ids: list[str] = []
    async with uow_factory() as uow:
        await uow.services.save(ucr_west(EAST))
        for number in (1, 2):
            case_id = f"case-{2000 + number}"
            await uow.cases.add(open_case(case_id, reference=f"{2000 + number}"))
            booking = Booking(
                id=f"bk-east-{number}",
                reference=f"{2000 + number}",
                service_id=EAST,
                case_id=case_id,
                requester_id="advisor-1",
                status=BookingStatus.REQUESTED,
                requested_at=at(14, 16),
                reply_by=at(14, 26),
            )
            await uow.bookings.add(booking)
            await schedule_work(
                uow,
                SequentialIds(f"tm{number}"),
                kind=WorkKind.BOOKING_EXPIRE,
                about_id=booking.id,
                due_at=at(14, 26),
                now=at(14, 16),
            )
            ids.append(booking.id)
        await schedule_work(
            uow,
            SequentialIds("pd"),
            kind=WorkKind.PROMPT_DUE,
            about_id=EAST,
            due_at=PROMPT_DUE_AT,
            now=at(14, 16),
        )
        await uow.commit()
    return ids


def suspend(
    uow_factory: UnitOfWorkFactory,
    driver: AsyncDriver,
    connection: Neo4jConnection,
    now: datetime,
    *,
    sealer: object | None = None,
) -> SuspendService:
    return SuspendService(
        uow_factory,
        DriverIdempotencyStore(driver),
        FixedClock(now),
        SequentialIds("su"),
        sealer or AesGcmContentSealer(SECRETS),  # type: ignore[arg-type]
        Neo4jTenantDirectory(connection),
    )


def resume(uow_factory: UnitOfWorkFactory, driver: AsyncDriver, now: datetime) -> ResumeService:
    return ResumeService(
        uow_factory, DriverIdempotencyStore(driver), FixedClock(now), SequentialIds("rs")
    )


def suspend_command(key: str, actor: Actor = LEAD) -> SuspendServiceCommand:
    return SuspendServiceCommand(
        idempotency_key=key, actor=actor, service_id=EAST, reason="closed-unexpectedly"
    )


async def statuses(uow_factory: UnitOfWorkFactory, ids: list[str]) -> list[BookingStatus]:
    out: list[BookingStatus] = []
    async with uow_factory() as uow:
        for booking_id in ids:
            booking = await uow.bookings.get(booking_id)
            assert booking is not None
            out.append(booking.status)
    return out


async def test_suspending_at_1420_flags_the_service_and_expires_its_two_requests(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    clean_graph: None,
) -> None:
    ids = await seed_east(uow_factory, neo4j_driver, tenant_id)
    result = await suspend(uow_factory, neo4j_driver, connection, at(14, 20)).execute(
        suspend_command("su-1")
    )
    assert isinstance(result, SuspendServiceResult)
    assert result.expired_requests == 2
    assert await statuses(uow_factory, ids) == [BookingStatus.EXPIRED, BookingStatus.EXPIRED]
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 1


async def test_the_prompt_work_is_cancelled_and_k4_expiries_and_status_are_queued(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory, neo4j_driver, tenant_id)
    await suspend(uow_factory, neo4j_driver, connection, at(14, 20)).execute(suspend_command("su-2"))
    async with uow_factory() as uow:
        prompt_work = await uow.scheduled_work.for_about(EAST, WorkKind.PROMPT_DUE)
        messages = await uow.outbox.pending(500)
    assert [w.status for w in prompt_work] == ["cancelled"]
    events = [m.event_type for m in messages]
    assert events.count("BookingExpired") == 2
    assert "StatusChanged" in events
    sent = [m.payload["message_id"] for m in messages if m.event_type == "SendMessage"]
    assert sent == ["K4"]


async def test_the_board_shows_the_suspended_service_as_not_updated(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory, neo4j_driver, tenant_id)
    await suspend(uow_factory, neo4j_driver, connection, at(14, 20)).execute(suspend_command("su-3"))
    board = await QueryBoard(uow_factory, FixedClock(at(14, 21))).execute(
        QueryBoardQuery(actor=ADVISOR)
    )
    assert next(e for e in board.entries if e.service_id == EAST).status is Status.NOT_UPDATED


async def test_suspending_an_already_suspended_service_is_a_conflict_and_writes_nothing(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory, neo4j_driver, tenant_id)
    await suspend(uow_factory, neo4j_driver, connection, at(14, 20)).execute(suspend_command("su-4a"))
    before = await count_nodes(neo4j_driver, "AuditEvent")
    with pytest.raises(Conflict):
        await suspend(uow_factory, neo4j_driver, connection, at(14, 21)).execute(
            suspend_command("su-4b")
        )
    assert await count_nodes(neo4j_driver, "AuditEvent") == before


async def test_a_resume_with_only_one_check_is_a_validation_failure(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory, neo4j_driver, tenant_id)
    await suspend(uow_factory, neo4j_driver, connection, at(14, 20)).execute(suspend_command("su-5a"))
    with pytest.raises(ValidationFailed):
        await resume(uow_factory, neo4j_driver, at(15, 0)).execute(
            ResumeServiceCommand(
                idempotency_key="rs-5",
                actor=LEAD,
                service_id=EAST,
                phoned_register_number=True,
                reason_resolved=False,
            )
        )


async def test_a_resume_with_both_checks_clears_the_flag_schedules_the_next_prompt_and_is_audited(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory, neo4j_driver, tenant_id)
    await suspend(uow_factory, neo4j_driver, connection, at(14, 20)).execute(suspend_command("su-6a"))
    audit_before = await count_nodes(neo4j_driver, "AuditEvent")
    await resume(uow_factory, neo4j_driver, at(15, 0)).execute(
        ResumeServiceCommand(
            idempotency_key="rs-6",
            actor=LEAD,
            service_id=EAST,
            phoned_register_number=True,
            reason_resolved=True,
        )
    )
    async with uow_factory() as uow:
        flags = await uow.flags.service_flags(EAST)
        prompts = await uow.scheduled_work.for_about(EAST, WorkKind.PROMPT_DUE)
    assert not any(flag.active for flag in flags)
    assert [w.status for w in prompts if w.due_at > at(15, 0)] == ["scheduled"]
    assert await count_nodes(neo4j_driver, "AuditEvent") == audit_before + 1


async def test_an_advisor_cannot_suspend_a_service(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    clean_graph: None,
) -> None:
    ids = await seed_east(uow_factory, neo4j_driver, tenant_id)
    with pytest.raises(NotAllowed):
        await suspend(uow_factory, neo4j_driver, connection, at(14, 20)).execute(
            suspend_command("su-7a", actor=ADVISOR)
        )
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 0
    assert await statuses(uow_factory, ids) == [BookingStatus.REQUESTED, BookingStatus.REQUESTED]


class _FailingSealer:
    """Fails when a message is sealed: the unit of work fails after the flag and the expiries are
    written, and before it commits (the rollback case)."""

    def seal(self, content: str, **_: str) -> str:
        raise RuntimeError("the sealer is down")


async def test_a_unit_that_fails_before_commit_leaves_no_flag_and_no_booking_change(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    clean_graph: None,
) -> None:
    ids = await seed_east(uow_factory, neo4j_driver, tenant_id)
    with pytest.raises(RuntimeError):
        await suspend(
            uow_factory, neo4j_driver, connection, at(14, 20), sealer=_FailingSealer()
        ).execute(suspend_command("su-8"))
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 0
    assert await statuses(uow_factory, ids) == [BookingStatus.REQUESTED, BookingStatus.REQUESTED]
