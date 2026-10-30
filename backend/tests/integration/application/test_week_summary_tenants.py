"""Two-tenant tests for the week summary (U35, DEC-130 to DEC-132, DEC-142).

Tenant A and tenant B hold the same service id, the same case, report, booking and prompt ids, and
the same week. A's summary counts A's records only, B's counts B's only, and a B case id given to
A's unit of work reads as not found. Every statement the summary reads is tenant-scoped
(Q-CASE-OPENED-BETWEEN and the other three range reads, and the converted reads behind them), so
these tests are not marked: they are expected to pass. Runs on contracted_container() (DEC-159,
lesson L168) because the superseded single-property keys would refuse a shared key.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.week_summary import GetWeekSummary, GetWeekSummaryCommand
from diucs.domain.codes import Cadence, Channel, Measure, ReportSource, Role, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support import seed
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import wipe_all
from tests.support.tenant_seed import contracted_container

pytestmark = pytest.mark.asyncio(loop_scope="session")

MONDAY = datetime(2026, 10, 19, tzinfo=UTC).date()
SERVICE = "ucr-west"
MIDWEEK = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


@dataclass(frozen=True, slots=True)
class Settings:
    minutes_per_avoided_call: int | None = 4


def _profile() -> ServiceProfile:
    return ServiceProfile(
        id=SERVICE,
        name="UCR West",
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


async def _seed_tenant(factory: UnitOfWorkFactory, cases: int, reports: int, prompts: int) -> None:
    """Both tenants get the same service and the same ids; the numbers differ."""
    async with factory() as uow:
        await uow.services.save(_profile())
        for n in range(cases):
            await uow.cases.add(seed.case(n, MIDWEEK))
        for n in range(reports):
            await uow.capacity.add(seed.report(n, SERVICE, MIDWEEK, ReportSource.TEXT))
        for n in range(prompts):
            await uow.communications.add(seed.prompt(n, SERVICE, MIDWEEK))
        await uow.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    return two_tenant_driver


@pytest_asyncio.fixture(loop_scope="session")
async def two(two_tenant_driver: AsyncDriver) -> AsyncIterator[None]:
    await wipe_all(two_tenant_driver)
    yield
    await wipe_all(two_tenant_driver)


@pytest_asyncio.fixture(loop_scope="session")
async def tenants(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    two: None,
) -> None:
    # A: twelve cases, twelve reports, twelve prompts. B: three cases, nothing else.
    await _seed_tenant(uow_factory_a, cases=12, reports=12, prompts=12)
    await _seed_tenant(uow_factory_b, cases=3, reports=0, prompts=0)


def _summary(factory: UnitOfWorkFactory) -> GetWeekSummary:
    return GetWeekSummary(factory, Settings(), FixedClock(MIDWEEK + timedelta(hours=2)))


async def test_tenant_a_summary_counts_only_tenant_a(
    uow_factory_a: UnitOfWorkFactory, tenants: None
) -> None:
    summary = await _summary(uow_factory_a).execute(GetWeekSummaryCommand(LEAD, MONDAY))
    assert summary.referrals.value == 12
    assert summary.updates_by_channel["text"].value == 12
    assert summary.on_time_pct.value == 100


async def test_tenant_b_summary_does_not_see_tenant_a_records(
    uow_factory_b: UnitOfWorkFactory, tenants: None
) -> None:
    summary = await _summary(uow_factory_b).execute(GetWeekSummaryCommand(LEAD, MONDAY))
    # Three cases is under the small-group line: hidden, and never twelve.
    assert summary.referrals.hidden is True
    assert summary.referrals.value is None
    assert summary.updates_by_channel["text"].hidden is True
    assert summary.on_time_pct.hidden is True


async def test_a_case_id_of_tenant_a_given_to_tenant_b_is_not_found(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: None,
) -> None:
    async with uow_factory_b() as uow:
        assert await uow.cases.get("case-11") is None
        assert await uow.cases.get_by_reference("1011") is None
    async with uow_factory_a() as uow:
        assert await uow.cases.get("case-11") is not None
