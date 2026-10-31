"""Integration tests for the coverage use cases and the service repository's coverage (DEC-1305),
against the real Neo4j the harness starts. Written in this build and NOT RUN where it was built (no
Docker on that machine): the batch run happens later.

A save writes the districts as coverage Locations of the service and the response target and days
as extensions on it, in the caller's tenant, and keeps the rest of the service. Another tenant's
service reads as not found. Values are synthetic.
"""

from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.coverage import (
    GetCoverageByWindow,
    GetServiceCoverage,
    SetServiceCoverage,
)
from overwatch.domain.codes import Cadence, Channel, Measure, Role, ServiceCategory
from overwatch.domain.errors import NotFound
from overwatch.domain.model.service import AvailableTime, ServiceProfile
from tests.integration.application.conftest import Seed
from tests.support.neo4j import read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


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
    )


def _lead(tenant: str) -> Actor:
    return Actor(Role.LEAD, "prac-lead", None, "web", frozenset(), tenant)


def _save(factory: UnitOfWorkFactory, ids: SequentialIds) -> SetServiceCoverage:
    return SetServiceCoverage(factory, FixedClock(NOW), ids)


async def _areas(driver: AsyncDriver, tenant: str, service_id: str) -> list[str]:
    async def read(tx: AsyncManagedTransaction) -> list[str]:
        rows = await tx.run(
            "MATCH (s:HealthcareService {id: $service, tenantId: $tenant})-[:COVERAGE_AREA]->"
            "(l:Location {tenantId: $tenant}) RETURN l.name AS name ORDER BY l.name",
            service=service_id,
            tenant=tenant,
        )
        return [str(row["name"]) async for row in rows]

    return await read_tx(driver, read)


async def test_a_save_is_read_back_and_the_districts_are_coverage_locations_of_the_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, seed_service: Seed
) -> None:
    await seed_service(_profile("svc-west", "UCR West"))
    lead = _lead(tenant_id)

    saved = await _save(uow_factory, SequentialIds()).execute(
        lead, "svc-west", ["DT4", "DT3"], 6, ["mon", "fri"]
    )
    read = await GetServiceCoverage(uow_factory).execute(lead, "svc-west")

    assert saved == read
    assert read.districts == ("DT3", "DT4")
    assert (read.response_hours, read.days) == (6, ("mon", "fri"))
    assert await _areas(neo4j_driver, tenant_id, "svc-west") == ["DT3", "DT4"]


async def test_a_second_save_keeps_the_location_of_a_district_kept_and_drops_the_rest(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, seed_service: Seed
) -> None:
    await seed_service(_profile("svc-west", "UCR West"))
    lead = _lead(tenant_id)
    ids = SequentialIds()
    await _save(uow_factory, ids).execute(lead, "svc-west", ["DT3", "DT4"], 2, ["mon"])

    async def location_ids(tx: AsyncManagedTransaction) -> dict[str, str]:
        rows = await tx.run(
            "MATCH (:HealthcareService {id: 'svc-west', tenantId: $tenant})-[:COVERAGE_AREA]->"
            "(l:Location {tenantId: $tenant}) RETURN l.name AS name, l.id AS id",
            tenant=tenant_id,
        )
        return {str(row["name"]): str(row["id"]) async for row in rows}

    before = await read_tx(neo4j_driver, location_ids)

    await _save(uow_factory, ids).execute(lead, "svc-west", ["DT4", "DT5"], 3, ["tue"])

    after = await read_tx(neo4j_driver, location_ids)
    assert set(after) == {"DT4", "DT5"}
    assert after["DT4"] == before["DT4"]


async def test_the_same_save_twice_gives_the_same_answer(
    uow_factory: UnitOfWorkFactory, tenant_id: str, seed_service: Seed
) -> None:
    await seed_service(_profile("svc-west", "UCR West"))
    lead = _lead(tenant_id)
    ids = SequentialIds()

    first = await _save(uow_factory, ids).execute(lead, "svc-west", ["DT3"], 2, ["mon"])
    second = await _save(uow_factory, ids).execute(lead, "svc-west", ["DT3"], 2, ["mon"])

    assert first == second


async def test_another_tenants_service_is_not_found_and_nothing_is_written(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    seed_service: Seed,
) -> None:
    await seed_service(_profile("svc-other", "Other"), tenant=other_tenant_id)
    lead = _lead(tenant_id)

    with pytest.raises(NotFound):
        await GetServiceCoverage(uow_factory).execute(lead, "svc-other")
    with pytest.raises(NotFound):
        await _save(uow_factory, SequentialIds()).execute(lead, "svc-other", ["DT3"], 2, ["mon"])

    assert await _areas(neo4j_driver, other_tenant_id, "svc-other") == []


async def test_the_options_of_one_tenant_never_name_another_tenants_services_or_districts(
    uow_factory: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
    seed_service: Seed,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    await seed_service(_profile("svc-west", "UCR West"))
    await seed_service(_profile("svc-other", "Other"), tenant=other_tenant_id)
    await _save(uow_factory_b, SequentialIds()).execute(
        _lead(other_tenant_id), "svc-other", ["ZZ9"], 2, ["mon"]
    )
    mine = _lead(tenant_id)
    await _save(uow_factory, SequentialIds()).execute(mine, "svc-west", ["DT3"], 2, ["mon"])

    view = await GetServiceCoverage(uow_factory).execute(mine, "svc-west")
    window = await GetCoverageByWindow(uow_factory, FixedClock(NOW)).execute(mine, "all")

    assert view.available == ("DT3",)
    assert view.others == ()
    assert [(item.district, item.services) for item in window.districts] == [("DT3", ("UCR West",))]
