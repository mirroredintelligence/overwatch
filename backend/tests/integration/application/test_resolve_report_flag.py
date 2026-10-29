"""Integration tests for resolving report flags (U39), against the real Neo4j the harness starts.

The lead lists the open flags with their descriptions, and resolves each one. A resolved flag keeps
its outcome, the lead who resolved it and the time, and is never resolved twice. The capacity report
is never edited. Values are synthetic: there is no patient data. Times are on Friday 23 October 2026
(London is on BST, one hour ahead of UTC): 14:10 London is 13:10 UTC.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.application.use_cases.resolve_report_flag import (
    ListReportFlags,
    ListReportFlagsQuery,
    ResolveReportFlag,
    ResolveReportFlagCommand,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportFlagReason,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import Conflict, NotAllowed, NotFound
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import REPORT_FLAG_CHECKED, ReportFlag
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import node_props

Seed = Callable[..., Awaitable[None]]
pytestmark = pytest.mark.asyncio(loop_scope="session")

LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
UCR_EAST = ServiceProfile(
    id="ucr-east",
    name="UCR East",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
FIRST = datetime(2026, 10, 23, 13, 10, tzinfo=UTC)
SECOND = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)


async def _seed_flag(uow_factory: UnitOfWorkFactory, seed_service: Seed) -> None:
    await seed_service(UCR_EAST)
    async with uow_factory() as uow:
        for number, (value, at) in enumerate(((40, FIRST), (40, SECOND)), start=1):
            await uow.capacity.add(
                CapacityReport(
                    id=f"obs-{number}",
                    service_id="ucr-east",
                    value=value,
                    measure=Measure.REFERRALS_ACCEPTABLE,
                    effective_at=at,
                    source=ReportSource.TEXT,
                    report_type=ReportType.NUMBER,
                )
            )
        await uow.commit()
    async with uow_factory() as uow:
        await uow.flags.add_report_flag(
            ReportFlag(
                id="flag-1",
                report_id="obs-2",
                service_id="ucr-east",
                reason=ReportFlagReason.OUT_OF_RANGE_TWICE,
                status="open",
                created_at=SECOND,
            )
        )
        await uow.commit()


def _resolve(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver) -> ResolveReportFlag:
    clock = FixedClock(datetime(2026, 10, 23, 13, 30, tzinfo=UTC))
    ids = SequentialIds()
    report_capacity = ReportCapacity(uow_factory, clock, ids, DriverIdempotencyStore(neo4j_driver))
    return ResolveReportFlag(uow_factory, report_capacity, clock)


async def test_the_out_of_range_description_matches_the_example_exactly(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await _seed_flag(uow_factory, seed_service)
    [view] = await ListReportFlags(uow_factory).execute(ListReportFlagsQuery(LEAD))
    assert view.description == (
        "UCR East reported 40, twice. Usual range 0 to 8. Sent 14:10 and 14:12 by text."
    )


async def test_checked_records_the_lead_and_time_and_leaves_both_reports_unchanged(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_flag(uow_factory, seed_service)
    before = [await node_props(neo4j_driver, "Observation", id=f"obs-{n}") for n in (1, 2)]
    resolved = await _resolve(uow_factory, neo4j_driver).execute(
        ResolveReportFlagCommand("resolve-1", LEAD, "flag-1", "checked")
    )
    assert resolved.status == REPORT_FLAG_CHECKED
    async with uow_factory() as uow:
        flag = await uow.flags.report_flag("flag-1")
    assert flag is not None
    assert flag.status == REPORT_FLAG_CHECKED
    assert flag.outcome == "checked"
    assert flag.resolved_by == "prac-lead"
    assert flag.resolved_at == datetime(2026, 10, 23, 13, 30, tzinfo=UTC)
    after = [await node_props(neo4j_driver, "Observation", id=f"obs-{n}") for n in (1, 2)]
    assert after == before


async def test_phoned_with_three_records_an_advisor_phoned_report_and_resolves_the_flag(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_flag(uow_factory, seed_service)
    result = await _resolve(uow_factory, neo4j_driver).execute(
        ResolveReportFlagCommand("resolve-2", LEAD, "flag-1", "phoned", phoned_value=3)
    )
    assert result.phoned_report_id is not None
    async with uow_factory() as uow:
        latest = await uow.capacity.latest("ucr-east")
        flag = await uow.flags.report_flag("flag-1")
    assert latest is not None and latest.source is ReportSource.ADVISOR_PHONED
    assert latest.value == 3
    assert flag is not None and flag.outcome == "phoned"


async def test_resolving_a_flag_twice_is_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_flag(uow_factory, seed_service)
    resolve = _resolve(uow_factory, neo4j_driver)
    await resolve.execute(ResolveReportFlagCommand("resolve-3", LEAD, "flag-1", "checked"))
    with pytest.raises(Conflict):
        await resolve.execute(ResolveReportFlagCommand("resolve-4", LEAD, "flag-1", "accepted"))


async def test_an_advisor_may_not_list_or_resolve_flags(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_flag(uow_factory, seed_service)
    with pytest.raises(NotAllowed):
        await ListReportFlags(uow_factory).execute(ListReportFlagsQuery(ADVISOR))
    with pytest.raises(NotAllowed):
        await _resolve(uow_factory, neo4j_driver).execute(
            ResolveReportFlagCommand("resolve-5", ADVISOR, "flag-1", "checked")
        )


async def test_a_flag_that_does_not_exist_is_not_found_and_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_flag(uow_factory, seed_service)
    with pytest.raises(NotFound):
        await _resolve(uow_factory, neo4j_driver).execute(
            ResolveReportFlagCommand("resolve-6", LEAD, "flag-missing", "checked")
        )
    flag = await _flag(uow_factory)
    assert flag.status == "open"


async def _flag(uow_factory: UnitOfWorkFactory) -> ReportFlag:
    async with uow_factory() as uow:
        flag = await uow.flags.report_flag("flag-1")
    assert flag is not None
    return flag
