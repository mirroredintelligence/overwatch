"""Integration tests for the planning analysis (U43), against the real Neo4j the harness starts.

The decision snapshots (OpenCase, FilterOptions, RecordOutcome, RecordDecline) are written through
the real audit log with the shapes the use cases write, through one committed unit of work per
test. Clock: Friday 23 October 2026, 14:30 London. Synthetic values only: no case id or reference
of these tests appears in any result, and the result is checked for that.
"""

import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.planning_analysis import (
    HiddenCount,
    PlanningQuery,
    PlanningResult,
    RunPlanningAnalysis,
    RunPlanningCommand,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import NotAllowed
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, wipe
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 30, tzinfo=UTC)
THU_BASE = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)  # Thursday 13:00 BST
UCR_WEST = "svc-ucr-west"
HOME = "svc-hospital-at-home"
ED = "svc-emergency-department"
WARD_B = "svc-ward-b"
WARD_A = "svc-ward-a"
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
EXEC = dataclasses.replace(LEAD, role=Role.EXEC, practitioner_id="prac-exec-1")
ADVISOR = dataclasses.replace(LEAD, role=Role.ADVISOR, practitioner_id="prac-advisor-1")
COHORT_NEEDS = ["fall-no-injury", "frailty"]

Seed = Callable[..., Awaitable[None]]


def _profile(service_id: str, name: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
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


def _row(service_id: str, status: str, number: int | None) -> dict[str, Any]:
    return {
        "id": service_id,
        "status": status,
        "number": number,
        "data_age_seconds": 120,
        "criteria_version": 1,
        "shown_as": "option",
    }


def _case_entries(
    key: str,
    opened: datetime,
    *,
    best: dict[str, Any],
    destination: str | None,
    age: str = "80+",
    urgency: str = "within-2-hrs",
    referrer: str = "ambulance-crew",
    needs: list[str] | None = None,
) -> list[AuditEntry]:
    """One case's OpenCase, FilterOptions and RecordOutcome entries, as the use cases write them."""
    closed = opened + timedelta(minutes=10)
    services = [best, _row(WARD_B, "accepting", 5)]
    reference = key.removeprefix("case-")
    return [
        AuditEntry(
            action="C",
            use_case="OpenCase",
            actor=LEAD,
            entity_ids=(key,),
            snapshot={
                "reference": reference,
                "referrer_type": referrer,
                "age_band": age,
                "needs": needs or COHORT_NEEDS,
                "urgency": urgency,
            },
            at=opened,
        ),
        AuditEntry(
            action="R",
            use_case="FilterOptions",
            actor=LEAD,
            entity_ids=(key, best["id"], WARD_B),
            snapshot={"reference": reference, "services": services},
            at=opened + timedelta(minutes=1),
        ),
        AuditEntry(
            action="U",
            use_case="RecordOutcome",
            actor=LEAD,
            entity_ids=(key,) if destination is None else (key, destination),
            snapshot={
                "reference": reference,
                "age_band": age,
                "needs": needs or COHORT_NEEDS,
                "urgency": urgency,
                "scores": [],
                "destination_service_id": destination,
                "outcome": "accepted-and-booked" if destination else "declined",
                "best_fit_not_used": None,
                "opened_at": opened,
                "closed_at": closed,
            },
            at=closed,
        ),
    ]


def _decline(key: str, service_id: str, at: datetime) -> AuditEntry:
    return AuditEntry(
        action="C",
        use_case="RecordDecline",
        actor=ADVISOR,
        entity_ids=(key, service_id),
        snapshot={
            "reference": key.removeprefix("case-"),
            "service_id": service_id,
            "reason": "no-beds",
            "status_seen": "accepting",
            "number_seen": 3,
        },
        at=at,
    )


async def _write(factory: UnitOfWorkFactory, entries: list[AuditEntry]) -> None:
    async with factory() as uow:
        for entry in entries:
            await uow.audit.append(entry)
        await uow.commit()


async def _seed_services(factory: UnitOfWorkFactory) -> None:
    async with factory() as uow:
        for service_id, name in (
            (UCR_WEST, "UCR West"),
            (HOME, "Hospital at home"),
            (ED, "Emergency department"),
            (WARD_B, "Community hospital · Ward B"),
            (WARD_A, "Ward A"),
        ):
            await uow.services.save(_profile(service_id, name))
        await uow.commit()


def _best(status: str, number: int | None, service_id: str = UCR_WEST) -> dict[str, Any]:
    return _row(service_id, status, number)


def _run(factory: UnitOfWorkFactory, actor: Actor = EXEC) -> Any:
    analysis = RunPlanningAnalysis(factory, FixedClock(NOW))
    return analysis.execute(RunPlanningCommand(actor, PlanningQuery(30, "all")))


@pytest.fixture
def factory(uow_factory: UnitOfWorkFactory, tenant_id: str) -> UnitOfWorkFactory:
    return uow_factory


async def _seed_base(factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str) -> None:
    await ensure_audit_heads(driver, tenant)
    await _seed_services(factory)


async def test_the_best_fit_share_is_eighteen_per_cent(
    factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed_base(factory, neo4j_driver, tenant_id)
    entries: list[AuditEntry] = []
    for index in range(640):
        closed_status = index < 112
        best = _best("not-accepting", 0) if closed_status else _best("accepting", 4)
        destination = WARD_B if closed_status else UCR_WEST
        entries += _case_entries(
            f"case-{index}",
            THU_BASE + timedelta(minutes=index),
            best=best,
            destination=destination,
        )
    await _write(factory, entries)
    result: PlanningResult = await _run(factory)
    assert result.referrals == HiddenCount(640, False)
    assert result.best_fit_unavailable == HiddenCount(112, False)
    assert result.best_fit_unavailable_pct == HiddenCount(18, False)


async def test_a_flow_of_six_is_hidden_and_eighteen_is_shown(
    factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed_base(factory, neo4j_driver, tenant_id)
    entries: list[AuditEntry] = []
    for index in range(24):
        destination = UCR_WEST if index < 18 else ED
        entries += _case_entries(
            f"case-{index}",
            THU_BASE + timedelta(minutes=index),
            best=_best("over-capacity", 14, HOME),
            destination=destination,
        )
    await _write(factory, entries)
    result = await _run(factory)
    flows = {(f.best_fit, f.state, f.destination): f.count for f in result.flows}
    assert flows[("Hospital at home", "full", "UCR West")] == HiddenCount(18, False)
    assert flows[("Hospital at home", "full", "Emergency department")] == HiddenCount(None, True)


async def test_the_heat_grid_places_a_thursday_one_pm_case_and_names_the_busiest_cell(
    factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed_base(factory, neo4j_driver, tenant_id)
    entries: list[AuditEntry] = []
    for index in range(12):
        entries += _case_entries(
            f"case-{index}",
            THU_BASE + timedelta(minutes=index),
            best=_best("not-accepting", 0),
            destination=WARD_B,
        )
    for index in range(3):
        entries += _case_entries(
            f"mon-{index}",
            datetime(2026, 10, 19, 8, 0, tzinfo=UTC) + timedelta(minutes=index),
            best=_best("not-accepting", 0),
            destination=WARD_B,
        )
    await _write(factory, entries)
    result = await _run(factory)
    assert result.heat[(3, "12-18")] == HiddenCount(12, False)
    assert result.busiest == (3, "12-18")


async def test_a_case_with_urgency_today_is_outside_the_default_cohort(
    factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed_base(factory, neo4j_driver, tenant_id)
    entries = _case_entries(
        "case-today",
        THU_BASE,
        best=_best("not-accepting", 0),
        destination=WARD_B,
        urgency="today",
    )
    entries += _case_entries(
        "case-urgent",
        THU_BASE + timedelta(minutes=5),
        best=_best("accepting", 4),
        destination=UCR_WEST,
    )
    await _write(factory, entries)
    result = await _run(factory)
    assert result.referrals == HiddenCount(None, True)
    assert result.best_fit_unavailable == HiddenCount(None, True)


async def test_declines_by_service_are_shown_or_hidden_by_count(
    factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed_base(factory, neo4j_driver, tenant_id)
    entries = [_decline("case-d", WARD_A, THU_BASE + timedelta(minutes=i)) for i in range(14)]
    entries += [_decline("case-e", WARD_B, THU_BASE + timedelta(minutes=i)) for i in range(4)]
    await _write(factory, entries)
    result = await _run(factory)
    assert dict(result.declined_despite) == {
        "Ward A": HiddenCount(14, False),
        "Community hospital · Ward B": HiddenCount(None, True),
    }


async def test_an_exec_runs_it_and_one_audit_entry_is_added_and_an_advisor_is_refused(
    factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed_base(factory, neo4j_driver, tenant_id)
    before = await count_nodes(neo4j_driver, "AuditEvent")
    await _run(factory, EXEC)
    assert await count_nodes(neo4j_driver, "AuditEvent") == before + 1
    with pytest.raises(NotAllowed):
        await _run(factory, ADVISOR)
    assert await count_nodes(neo4j_driver, "AuditEvent") == before + 1


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """A private Neo4j with the superseded single-property keys dropped (DEC-159)."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    """Overrides the session driver for this module."""
    return two_tenant_driver


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def fresh_graph(neo4j_driver: AsyncDriver) -> None:
    await wipe(neo4j_driver)


async def test_tenant_a_sees_none_of_tenant_bs_decisions(
    two_tenant_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """Tenant B holds 12 unavailable best fits and a decline; tenant A's analysis counts none of
    them (DEC-130, planning is tenant-only)."""
    factory_b = tenant_uow_factory(two_tenant_driver, other_tenant_id)
    factory_a = tenant_uow_factory(two_tenant_driver, tenant_id)
    await ensure_audit_heads(two_tenant_driver, other_tenant_id)
    await ensure_audit_heads(two_tenant_driver, tenant_id)
    await _seed_services(factory_b)
    entries: list[AuditEntry] = []
    for index in range(12):
        entries += _case_entries(
            f"case-b-{index}",
            THU_BASE + timedelta(minutes=index),
            best=_best("not-accepting", 0),
            destination=WARD_B,
        )
    entries.append(_decline("case-b-d", WARD_A, THU_BASE))
    await _write(factory_b, entries)

    result = await _run(factory_a, EXEC)
    assert result.referrals == HiddenCount(None, True)
    assert result.declined_despite == ()
    assert "case-b" not in repr(result)
