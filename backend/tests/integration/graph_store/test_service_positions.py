"""Integration tests for Neo4jServicePositions (U12, Q-SVC-POSITIONS), against the real Neo4j the
harness starts. Written in the build wave and NOT RUN there: the batch run happens later.

The positions are read from the Location each service links to, inside the unit of work. A service
with no Location, and a Location without coordinates, is left out. Values are synthetic.
"""

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.application.ports.outbound.geo import LatLon
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _profile(service_id: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=f"Service {service_id}",
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


async def _seed(factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str) -> None:
    async with factory() as uow:
        await uow.services.save(_profile("svc-west"))
        await uow.services.save(_profile("svc-bare"))
        await uow.commit()

    async def locate(tx: AsyncManagedTransaction) -> None:
        # The resource store's shape for HealthcareService.location (see test_filter_options.py).
        await tx.run(
            "MATCH (s:HealthcareService {id: 'svc-west', tenantId: $tenant}) "
            "CREATE (l:Resource:Location {key: 'Location/loc-west', id: 'loc-west', "
            "tenantId: $tenant, positionLatitude: 50.73, positionLongitude: -2.45}) "
            "CREATE (s)-[:LOCATION {fhirPath: 'HealthcareService.location'}]->(l)",
            tenant=tenant,
        )

    await write_tx(driver, locate)


async def _positions(factory: UnitOfWorkFactory, ids: list[str]) -> dict[str, LatLon]:
    async with factory() as uow:
        return await uow.positions.get_many(ids)


async def test_a_service_with_a_location_gets_its_position_and_one_without_is_left_out(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    found = await _positions(uow_factory, ["svc-west", "svc-bare"])

    assert found == {"svc-west": LatLon(lat=50.73, lon=-2.45)}


async def test_an_empty_list_reads_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    assert await _positions(uow_factory, []) == {}


async def test_another_tenants_location_is_not_returned(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    async def count(tx: AsyncManagedTransaction) -> int:
        record = await (
            await tx.run(
                "MATCH (l:Location {tenantId: $tenant}) RETURN count(l) AS total",
                tenant=other_tenant_id,
            )
        ).single()
        return int(record["total"])

    assert await read_tx(neo4j_driver, count) == 0
    assert await _positions(uow_factory, ["svc-west"]) == {"svc-west": LatLon(lat=50.73, lon=-2.45)}


# KI-626: a visiting service has coverage areas and no site (DEC-1175). Its districts are the names
# of the Locations it covers.


async def _seed_visiting(driver: AsyncDriver, tenant: str) -> None:
    async def cover(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "MATCH (s:HealthcareService {id: 'svc-bare', tenantId: $tenant}) "
            "CREATE (a:Resource:Location {key: 'Location/area-dt3', id: 'area-dt3', "
            "tenantId: $tenant, name: 'DT3'}) "
            "CREATE (b:Resource:Location {key: 'Location/area-dt4', id: 'area-dt4', "
            "tenantId: $tenant, name: 'DT4'}) "
            "CREATE (s)-[:COVERAGE_AREA {fhirPath: 'HealthcareService.coverageArea'}]->(a) "
            "CREATE (s)-[:COVERAGE_AREA {fhirPath: 'HealthcareService.coverageArea'}]->(b)",
            tenant=tenant,
        )

    await write_tx(driver, cover)


async def test_a_visiting_service_gives_the_districts_it_covers_and_a_fixed_site_gives_none(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await _seed_visiting(neo4j_driver, tenant_id)

    async with uow_factory() as uow:
        found = await uow.positions.coverage_districts(["svc-west", "svc-bare"])

    assert found == {"svc-bare": ("DT3", "DT4")}


async def test_an_empty_list_has_no_coverage(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    async with uow_factory() as uow:
        assert await uow.positions.coverage_districts([]) == {}


async def test_another_tenants_coverage_is_not_returned(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await _seed_visiting(neo4j_driver, tenant_id)

    async with uow_factory_b() as uow:
        assert await uow.positions.coverage_districts(["svc-bare"]) == {}
