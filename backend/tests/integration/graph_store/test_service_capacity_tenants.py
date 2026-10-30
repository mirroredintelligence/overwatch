"""Two tenants on the service, capacity, booking and case repositories (TEN-010, DEC-130 to 132).

Each test writes the same ids and keys for two tenants on a private contracted container (the
schema the platform has after TEN-032, DEC-159), so a statement that forgets its tenant predicate
reads or changes the other tenant's record. The shared harness schema keeps the superseded
single-property keys until TEN-032, so it cannot hold one service id for two tenants. A record of
another tenant reads as absent, never as an error. All values are synthetic."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.booking_repository import Neo4jBookingRepository
from diucs.adapters.outbound.graph_store.capacity_repository import Neo4jCapacityRepository
from diucs.adapters.outbound.graph_store.case_repository import Neo4jCaseRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import Neo4jServiceRepository
from diucs.domain.codes import Measure, ReportSource, ReportType
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile
from tests.integration.graph_store.test_booking_repository import BOOKING_4821
from tests.integration.graph_store.test_case_repository import OPEN_CASE
from tests.support.neo4j import read_tx, write_tx
from tests.support.tenancy import as_tenant
from tests.unit.adapters.outbound.graph_store.test_service_repository import UCR_WEST

pytestmark = pytest.mark.asyncio(loop_scope="session")

SINCE = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
REPORT = CapacityReport(
    id="obs-ucr-west-0715",
    service_id="svc-ucr-west",
    value=2,
    measure=Measure.REFERRALS_ACCEPTABLE,
    effective_at=datetime(2026, 10, 25, 7, 15, tzinfo=UTC),
    source=ReportSource.TEXT,
    report_type=ReportType.NUMBER,
)
# The other tenant's report for the same service id: a later time and another figure, so a read
# that leaks it is seen.
OTHER_REPORT = replace(
    REPORT,
    value=9,
    effective_at=datetime(2026, 10, 25, 9, 0, tzinfo=UTC),
)
OTHER_WARD = replace(UCR_WEST, name="Other ward")


@pytest_asyncio.fixture(loop_scope="session")
async def two(neo4j_driver: AsyncDriver, clean_graph: None) -> AsyncIterator[AsyncDriver]:
    yield neo4j_driver


Work = Callable[[AsyncManagedTransaction], Awaitable[Any]]


async def _write_as(driver: AsyncDriver, tenant: str, work: Work) -> None:
    with as_tenant(tenant):
        await write_tx(driver, work)


async def _read_as(driver: AsyncDriver, tenant: str, work: Work) -> Any:
    with as_tenant(tenant):
        return await read_tx(driver, work)


async def _save_service(driver: AsyncDriver, tenant: str, profile: ServiceProfile) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jServiceRepository(tx, ResourceStore(tx)).save(profile)

    await _write_as(driver, tenant, work)


async def test_another_tenants_active_services_are_not_listed(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _save_service(two, tenant_id, UCR_WEST)
    await _save_service(two, other_tenant_id, OTHER_WARD)

    async def listed(tx: AsyncManagedTransaction) -> list[str]:
        services = await Neo4jServiceRepository(tx, ResourceStore(tx)).list_active()
        return [service.name for service in services]

    assert await _read_as(two, tenant_id, listed) == [UCR_WEST.name]
    assert await _read_as(two, other_tenant_id, listed) == [OTHER_WARD.name]


async def test_another_tenants_reports_are_not_read_as_this_services(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _save_service(two, tenant_id, UCR_WEST)
    await _save_service(two, other_tenant_id, OTHER_WARD)

    async def add(report: CapacityReport) -> None:
        async def work(tx: AsyncManagedTransaction) -> None:
            await Neo4jCapacityRepository(tx, ResourceStore(tx)).add(report)

        await _write_as(two, tenant_id if report is REPORT else other_tenant_id, work)

    await add(REPORT)
    await add(OTHER_REPORT)

    async def reports(tx: AsyncManagedTransaction) -> list[int]:
        repo = Neo4jCapacityRepository(tx, ResourceStore(tx))
        found = await repo.reports_since(REPORT.service_id, SINCE)
        return [report.value for report in found]

    assert await _read_as(two, tenant_id, reports) == [REPORT.value]
    assert await _read_as(two, other_tenant_id, reports) == [OTHER_REPORT.value]


async def test_a_requested_booking_of_another_tenant_is_not_counted(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _save_service(two, tenant_id, UCR_WEST)
    await _save_service(two, other_tenant_id, OTHER_WARD)

    async def book(tx: AsyncManagedTransaction) -> None:
        await Neo4jBookingRepository(tx, ResourceStore(tx)).add(BOOKING_4821)

    await _write_as(two, tenant_id, book)
    await _write_as(two, other_tenant_id, book)

    async def pending(tx: AsyncManagedTransaction) -> int:
        return await Neo4jBookingRepository(tx, ResourceStore(tx)).pending_count(UCR_WEST.id)

    assert await _read_as(two, tenant_id, pending) == 1
    assert await _read_as(two, other_tenant_id, pending) == 1


async def test_a_booking_reference_held_by_another_tenant_is_not_found(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _save_service(two, tenant_id, UCR_WEST)

    async def book(tx: AsyncManagedTransaction) -> None:
        await Neo4jBookingRepository(tx, ResourceStore(tx)).add(BOOKING_4821)

    await _write_as(two, tenant_id, book)

    async def by_reference(tx: AsyncManagedTransaction) -> Any:
        return await Neo4jBookingRepository(tx, ResourceStore(tx)).get_by_reference("4821")

    assert await _read_as(two, tenant_id, by_reference) is not None
    assert await _read_as(two, other_tenant_id, by_reference) is None


async def test_a_case_reference_is_unique_only_within_its_tenant(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    async def add(tx: AsyncManagedTransaction) -> None:
        await Neo4jCaseRepository(tx, ResourceStore(tx)).add(OPEN_CASE)

    await _write_as(two, tenant_id, add)
    # The same case reference, and the same case id, in the other tenant: both are allowed.
    await _write_as(two, other_tenant_id, add)

    async def by_reference(tx: AsyncManagedTransaction) -> Any:
        found = await Neo4jCaseRepository(tx, ResourceStore(tx)).get_by_reference(
            OPEN_CASE.reference
        )
        return None if found is None else found.id

    assert await _read_as(two, tenant_id, by_reference) == OPEN_CASE.id
    assert await _read_as(two, other_tenant_id, by_reference) == OPEN_CASE.id


async def test_a_case_reference_held_by_another_tenant_is_not_found(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    async def add(tx: AsyncManagedTransaction) -> None:
        await Neo4jCaseRepository(tx, ResourceStore(tx)).add(OPEN_CASE)

    await _write_as(two, tenant_id, add)

    async def by_reference(tx: AsyncManagedTransaction) -> Any:
        return await Neo4jCaseRepository(tx, ResourceStore(tx)).get_by_reference(
            OPEN_CASE.reference
        )

    assert await _read_as(two, tenant_id, by_reference) is not None
    assert await _read_as(two, other_tenant_id, by_reference) is None
