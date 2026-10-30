"""The board for two tenants on real Neo4j (TEN-039, DEC-130, DEC-132 item 4).

Tenant A is the run tenant; tenant B is the run's second tenant, with units of work of its own
(`uow_factory_b`). A holds UCR West, B holds Clinic B. Each tenant's board lists its own services
and no other, the cached board and the "board changed" message are per tenant, and the projector
rebuilds for the tenant whose scope it runs in. Until TEN-032 the two tenants cannot share a
concept on the shared test schema (lesson L169), so B's category, measure and source differ from
A's. Written in the build wave; run in the verification stage. Synthetic values only.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import wall_actor
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.board_projector import BOARD_CACHE_KEY, BoardProjector
from diucs.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from diucs.domain.codes import Measure, ReportSource, ReportType, ServiceCategory
from diucs.domain.model.capacity import CapacityReport
from tests.integration.application.test_query_board import WEST
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
CLINIC_B = replace(
    WEST,
    id="svc-b-clinic",
    name="Clinic B",
    category=ServiceCategory.SAME_DAY_EMERGENCY_CARE,
    measure=Measure.FREE_SLOTS,
    unit_label="slots",
)


def _report(service_id: str, value: int, measure: Measure, source: ReportSource) -> CapacityReport:
    return CapacityReport(
        id=f"obs-{service_id}",
        service_id=service_id,
        value=value,
        measure=measure,
        effective_at=datetime(2026, 10, 23, 13, 3, tzinfo=UTC),
        source=source,
        report_type=ReportType.NUMBER,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def two_boards(
    clean_graph: None, uow_factory_a: UnitOfWorkFactory, uow_factory_b: UnitOfWorkFactory
) -> None:
    async with uow_factory_a() as uow:
        await uow.services.save(WEST)
        await uow.capacity.add(_report(WEST.id, 4, WEST.measure, ReportSource.TEXT))
        await uow.commit()
    async with uow_factory_b() as uow:
        await uow.services.save(CLINIC_B)
        await uow.capacity.add(_report(CLINIC_B.id, 7, CLINIC_B.measure, ReportSource.EMAIL))
        await uow.commit()


def _projector(factory: UnitOfWorkFactory, cache: InMemoryCache) -> BoardProjector:
    clock = FixedClock(NOW)
    return BoardProjector(QueryBoard(factory, clock), cache, clock)


async def test_each_tenants_board_lists_its_own_services_and_no_other(
    two_boards: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    clock = FixedClock(NOW)
    with as_tenant(tenant_id):
        first = await QueryBoard(uow_factory_a, clock).execute(
            QueryBoardQuery(actor=wall_actor(tenant_id))
        )
    with as_tenant(other_tenant_id):
        second = await QueryBoard(uow_factory_b, clock).execute(
            QueryBoardQuery(actor=wall_actor(other_tenant_id))
        )

    assert [entry.service_id for entry in first.entries] == [WEST.id]
    assert [entry.service_id for entry in second.entries] == [CLINIC_B.id]
    assert first.entries[0].name == "UCR West"
    assert second.entries[0].name == "Clinic B"


async def test_one_cache_holds_one_board_for_each_tenant(
    two_boards: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    cache = InMemoryCache(FixedClock(NOW))

    with as_tenant(tenant_id):
        await _projector(uow_factory_a, cache).handle("CapacityReported", {"service_id": WEST.id})
    with as_tenant(other_tenant_id):
        await _projector(uow_factory_b, cache).handle(
            "CapacityReported", {"service_id": CLINIC_B.id}
        )

    with as_tenant(tenant_id):
        cached_a = json.loads(await cache.get(BOARD_CACHE_KEY) or "")
    with as_tenant(other_tenant_id):
        cached_b = json.loads(await cache.get(BOARD_CACHE_KEY) or "")
    assert [entry["service_id"] for entry in cached_a["entries"]] == [WEST.id]
    assert [entry["service_id"] for entry in cached_b["entries"]] == [CLINIC_B.id]


async def test_a_rebuild_for_one_tenant_announces_to_that_tenants_listeners_only(
    two_boards: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    cache = InMemoryCache(FixedClock(NOW))
    with as_tenant(tenant_id):
        listener_a = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    with as_tenant(other_tenant_id):
        listener_b = await cache.subscribe(BOARD_UPDATES_CHANNEL)

    with as_tenant(other_tenant_id):
        await _projector(uow_factory_b, cache).handle(
            "CapacityReported", {"service_id": CLINIC_B.id}
        )

    message = json.loads(await anext(listener_b))
    assert message["service_id"] == CLINIC_B.id
    with as_tenant(tenant_id):
        await _projector(uow_factory_a, cache).handle("CapacityReported", {"service_id": WEST.id})
    assert json.loads(await anext(listener_a))["service_id"] == WEST.id
    await listener_a.aclose()  # type: ignore[attr-defined]
    await listener_b.aclose()  # type: ignore[attr-defined]
