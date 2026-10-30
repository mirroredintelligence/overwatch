"""Integration tests for the advisor's phoned figure and declines (U13), against the real Neo4j the
harness starts. Written in the build wave and NOT RUN there: the batch run happens later.

Each assertion reads back through a fresh unit of work or a harness helper (DEC-004). Values are the
sample values of the prompt: UCR West, case 4821 (80+, fall and frailty, within 2 hrs). No patient
data appears here.
"""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.advisor_phoned import (
    RecordAdvisorPhoned,
    RecordAdvisorPhonedCommand,
)
from diucs.application.use_cases.query_board import QueryBoard
from diucs.application.use_cases.record_decline import (
    ListDeclinesSince,
    RecordDecline,
    RecordDeclineCommand,
)
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.domain.codes import (
    AgeBand,
    Cadence,
    Channel,
    DeclineReason,
    Measure,
    NeedCategory,
    ReferrerType,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
    Urgency,
)
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.case import Case
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, read_tx

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 13, tzinfo=UTC)  # 14:13 BST
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
REPORTER = dataclasses.replace(
    ADVISOR, role=Role.REPORTER, practitioner_id=None, service_ids=frozenset({"svc-ucr-west"})
)
WEST = "svc-ucr-west"
CASE_ID = "case-4821"


def _west() -> ServiceProfile:
    return ServiceProfile(
        id=WEST,
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day_all_day(),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def _case() -> Case:
    return Case(
        id=CASE_ID,
        reference="4821",
        referrer_type=ReferrerType.AMBULANCE_CREW,
        age_band=AgeBand.A80_PLUS,
        postcode="DT4",
        needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(),
        opened_at=datetime(2026, 10, 23, 13, 10, tzinfo=UTC),
    )


def _phoned(factory: UnitOfWorkFactory, driver: AsyncDriver) -> RecordAdvisorPhoned:
    capacity = ReportCapacity(
        factory,
        FixedClock(NOW),
        SequentialIds.scoped(ACTOR_TENANT, "a"),
        DriverIdempotencyStore(driver),
    )
    return RecordAdvisorPhoned(capacity, factory)


def _decliner(factory: UnitOfWorkFactory, driver: AsyncDriver) -> RecordDecline:
    clock = FixedClock(NOW)
    return RecordDecline(
        factory,
        clock,
        SequentialIds.scoped(ACTOR_TENANT, "d"),
        DriverIdempotencyStore(driver),
        QueryBoard(factory, clock),
    )


async def _seed(factory: UnitOfWorkFactory, seed_service: Seed) -> None:
    await seed_service(_west())
    async with factory() as uow:
        await uow.cases.add(_case())
        await uow.commit()


async def _latest(factory: UnitOfWorkFactory) -> CapacityReport | None:
    async with factory() as uow:
        return await uow.capacity.latest(WEST)


async def _last_audit(factory: UnitOfWorkFactory) -> Any:
    async with factory() as uow:
        return (await uow.audit.records())[-1].entry


async def _outbox_count(driver: AsyncDriver, event_type: str) -> int:
    async def work(tx: Any) -> int:
        record = await (
            await tx.run(
                "MATCH (m:OutboxMessage {eventType: $event}) RETURN count(m) AS total",
                event=event_type,
            )
        ).single()
        return int(record["total"])

    return await read_tx(driver, work)


async def test_phoned_accepting_three_is_stored_as_advisor_phoned_with_no_echo(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)

    result = await _phoned(uow_factory, neo4j_driver).execute(
        RecordAdvisorPhonedCommand("phoned-1", ADVISOR, WEST, "accepting", 3, CASE_ID)
    )

    latest = await _latest(uow_factory)
    assert latest is not None
    assert latest.value == 3
    assert latest.source is ReportSource.ADVISOR_PHONED
    assert latest.id == result.report_id
    assert await _outbox_count(neo4j_driver, "SendMessage") == 0
    entry = await _last_audit(uow_factory)
    assert entry.snapshot["told"] == "accepting"
    assert entry.snapshot["case_id"] == CASE_ID


async def test_phoned_not_accepting_stores_zero_and_the_board_shows_not_accepting(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)

    result = await _phoned(uow_factory, neo4j_driver).execute(
        RecordAdvisorPhonedCommand("phoned-2", ADVISOR, WEST, "not-accepting", None)
    )

    latest = await _latest(uow_factory)
    assert latest is not None
    assert latest.value == 0
    assert result.status is Status.NOT_ACCEPTING


async def test_phoned_accepting_without_a_number_is_refused_and_nothing_is_written(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)
    before = await count_nodes(neo4j_driver, "Observation")

    with pytest.raises(ValidationFailed) as refused:
        await _phoned(uow_factory, neo4j_driver).execute(
            RecordAdvisorPhonedCommand("phoned-3", ADVISOR, WEST, "accepting", None)
        )

    assert refused.value.field == "value"
    assert await count_nodes(neo4j_driver, "Observation") == before


async def test_a_decline_records_what_the_advisor_saw_and_writes_the_outbox_message(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)
    async with uow_factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id="obs-west-4",
                service_id=WEST,
                value=4,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=datetime(2026, 10, 23, 13, 4, tzinfo=UTC),
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()

    await _decliner(uow_factory, neo4j_driver).execute(
        RecordDeclineCommand("decline-1", ADVISOR, CASE_ID, WEST, DeclineReason.OUTSIDE_CRITERIA)
    )

    entry = await _last_audit(uow_factory)
    assert entry.use_case == "RecordDecline"
    assert entry.snapshot["status_seen"] == "accepting"
    assert entry.snapshot["number_seen"] == 4
    assert await _outbox_count(neo4j_driver, "DeclinedDespiteCapacity") == 1


async def test_the_declines_since_midnight_carry_no_practitioner(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)
    await _decliner(uow_factory, neo4j_driver).execute(
        RecordDeclineCommand("decline-2", ADVISOR, CASE_ID, WEST, DeclineReason.FULL)
    )

    declines = await ListDeclinesSince(uow_factory).execute(
        datetime(2026, 10, 23, 0, 0, tzinfo=UTC)
    )

    assert [(item.service_id, item.reason) for item in declines] == [(WEST, DeclineReason.FULL)]
    assert not hasattr(declines[0], "practitioner_id")


async def test_a_reporter_may_not_phone_or_decline_and_a_replay_writes_no_second_record(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)
    phoned = _phoned(uow_factory, neo4j_driver)

    with pytest.raises(NotAllowed):
        await phoned.execute(RecordAdvisorPhonedCommand("phoned-r", REPORTER, WEST, "accepting", 2))
    with pytest.raises(NotAllowed):
        await _decliner(uow_factory, neo4j_driver).execute(
            RecordDeclineCommand("decline-r", REPORTER, CASE_ID, WEST, DeclineReason.OTHER)
        )

    command = RecordAdvisorPhonedCommand("phoned-once", ADVISOR, WEST, "limited", 2)
    first = await phoned.execute(command)
    replay = await phoned.execute(command)

    assert replay.replayed is True
    assert replay.report_id == first.report_id
    async with uow_factory() as uow:
        assert len(await uow.capacity.reports_since(WEST, NOW.replace(year=2000))) == 1


async def test_an_unknown_case_is_not_found_and_nothing_is_written(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed(uow_factory, seed_service)
    before = await count_nodes(neo4j_driver, "Observation")

    with pytest.raises(NotFound):
        await _phoned(uow_factory, neo4j_driver).execute(
            RecordAdvisorPhonedCommand("phoned-x", ADVISOR, WEST, "accepting", 3, "no-such-case")
        )

    assert await count_nodes(neo4j_driver, "Observation") == before


async def test_tenant_b_cannot_phone_or_decline_a_service_it_does_not_hold(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
) -> None:
    await _seed(uow_factory, seed_service)

    with pytest.raises(NotFound):
        await _phoned(uow_factory_b, neo4j_driver).execute(
            RecordAdvisorPhonedCommand("b-phoned", ADVISOR, WEST, "accepting", 3)
        )
    with pytest.raises(NotFound):
        await _decliner(uow_factory_b, neo4j_driver).execute(
            RecordDeclineCommand("b-decline", ADVISOR, CASE_ID, WEST, DeclineReason.FULL)
        )
