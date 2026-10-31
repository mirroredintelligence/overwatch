"""FilterOptions after B6 (KI-350, KI-626, KI-627, KI-801, KI-202), against the real Neo4j.

The service phone is the work phone of the service's own profile; a visiting service (coverage
areas and no site) is a circle of the districts it covers and a fixed site is a pin, never both;
the travel estimate is awaited after the unit of work has closed; a routing cache that is down
does not fail the options list. Another tenant's phone is never offered. Synthetic values.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.travel_time.routing import RoutingTravelTime
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedPostcodeLocator, FixedTravelTime
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.geo import LatLon, TravelRange, TravelTime
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.filter_options import (
    FilterOptions,
    FilterOptionsCommand,
    FilterOptionsResult,
)
from diucs.application.use_cases.query_board import QueryBoard
from tests.integration.application.test_filter_options import (
    ACTOR,
    CASE_ID,
    DISTRICT,
    NOW,
    PATIENT_SITE,
    UCR_EAST,
    UCR_WEST,
    WEST_SITE,
    _seed,
)
from tests.support.neo4j import write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

PLACES = {
    DISTRICT: PATIENT_SITE,
    "DT3": LatLon(50.70, -2.50),
    "DT4": LatLon(50.74, -2.40),
}
ROUTED = TravelRange(35, 50, "Routing data, updated 2026-10-01")


def _filter(factory: Any, travel: TravelTime) -> FilterOptions:
    clock = FixedClock(NOW)
    return FilterOptions(
        factory,
        clock,
        QueryBoard(factory, clock),
        FixedPostcodeLocator(postcodes={}, districts=PLACES),
        travel,
    )


async def _run(factory: Any, travel: TravelTime | None = None) -> FilterOptionsResult:
    return await _filter(factory, travel or FixedTravelTime(ROUTED)).execute(
        FilterOptionsCommand("filter-b6", ACTOR, CASE_ID)
    )


async def _give_phone(factory: UnitOfWorkFactory, service_id: str, phone: str) -> None:
    async with factory() as uow:
        store = uow.services._store  # type: ignore[attr-defined]  # noqa: SLF001
        resource = await store.get("HealthcareService", service_id)
        body = {key: value for key, value in resource.items() if key != "meta"}
        body["telecom"] = [{"system": "phone", "value": phone, "use": "work"}]
        await store.put(body, str(resource["meta"]["versionId"]))
        await uow.commit()


async def _cover(driver: AsyncDriver, tenant: str, service_id: str, *districts: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        for order, district in enumerate(districts):
            await tx.run(
                "MATCH (s:HealthcareService {id: $service, tenantId: $tenant}) "
                "CREATE (a:Resource:Location {key: $key, id: $id, tenantId: $tenant, name: $name}) "
                "CREATE (s)-[:COVERAGE_AREA {fhirPath: 'HealthcareService.coverageArea', "
                "order: $order}]->(a)",
                service=service_id,
                tenant=tenant,
                key=f"Location/area-{service_id}-{district}",
                id=f"area-{service_id}-{district}",
                name=district,
                order=order,
            )

    await write_tx(driver, work)


def _option(result: FilterOptionsResult, service_id: str) -> Any:
    found = [option for option in result.options if option.service_id == service_id]
    assert len(found) == 1, f"{service_id} is not an option"
    return found[0]


async def test_a_service_with_a_work_phone_offers_it_and_one_without_offers_none(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await _give_phone(uow_factory, UCR_WEST, "01305 900100")

    result = await _run(uow_factory)

    assert _option(result, UCR_WEST).phone == "01305 900100"
    assert _option(result, UCR_EAST).phone is None


async def test_a_fixed_site_is_a_pin_and_has_no_circle(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    west = _option(await _run(uow_factory), UCR_WEST)

    assert west.position == WEST_SITE
    assert west.coverage is None


async def test_a_service_with_no_site_and_no_coverage_area_has_neither_pin_nor_circle(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    # A fixed site whose Location was never recorded is a gap in the data, not a visiting service:
    # drawing a circle for it would invent an area.
    await _seed(uow_factory, neo4j_driver, tenant_id)

    east = _option(await _run(uow_factory), UCR_EAST)

    assert east.position is None
    assert east.coverage is None


async def test_a_visiting_service_is_a_circle_of_the_districts_it_covers(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await _cover(neo4j_driver, tenant_id, UCR_EAST, "DT3", "DT4")

    east = _option(await _run(uow_factory), UCR_EAST)

    assert east.position is None
    assert east.travel is None
    assert east.legs == ()
    assert east.coverage is not None
    assert east.coverage.radius_km >= 1
    assert 50.70 < east.coverage.lat < 50.74


async def test_a_routed_option_carries_one_leg_by_road_with_the_engines_source(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    travel = FixedTravelTime(ROUTED, {(PATIENT_SITE, WEST_SITE): ROUTED})

    west = _option(await _run(uow_factory, travel), UCR_WEST)

    assert west.travel == ROUTED
    assert [leg.label for leg in west.legs] == ["Patient to UCR West, by road"]
    assert west.legs[0].source == "Routing data, updated 2026-10-01"


class _OpenUnits:
    """A unit-of-work factory that counts the units open at any moment."""

    def __init__(self, factory: UnitOfWorkFactory) -> None:
        self._factory = factory
        self.open = 0

    def __call__(self) -> Any:
        outer = self

        class _Counted:
            def __init__(self) -> None:
                self._inner = outer._factory()

            async def __aenter__(self) -> Any:
                outer.open += 1
                return await self._inner.__aenter__()

            async def __aexit__(self, *error: Any) -> Any:
                try:
                    return await self._inner.__aexit__(*error)
                finally:
                    outer.open -= 1

        return _Counted()


class _WatchingTravel:
    def __init__(self, units: _OpenUnits) -> None:
        self._units = units
        self.open_when_asked: list[int] = []

    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange:
        self.open_when_asked.append(self._units.open)
        return ROUTED


async def test_the_travel_estimate_is_awaited_after_the_unit_of_work_has_closed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    units = _OpenUnits(uow_factory)
    travel = _WatchingTravel(units)

    result = await _run(units, travel)

    assert travel.open_when_asked == [0]
    assert _option(result, UCR_WEST).travel == ROUTED


class _DownCache(InMemoryCache):
    async def get(self, key: str) -> str | None:
        raise ConnectionError("cache down")

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        raise ConnectionError("cache down")


class _NeverAsked:
    async def get_json(self, url: str, timeout: timedelta) -> tuple[int, object]:
        raise AssertionError("the engine is not asked while the cache is down")


async def test_a_routing_cache_that_is_down_does_not_fail_the_options_list(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    straight = FixedTravelTime(TravelRange(30, 55, "straight-line estimate"))
    travel = RoutingTravelTime(
        _NeverAsked(),
        "http://routing.test",
        "2026-10-01",
        _DownCache(FixedClock(datetime(2026, 10, 23, 13, 13, tzinfo=UTC))),
        straight,
    )

    result = await _run(uow_factory, travel)

    west = _option(result, UCR_WEST)
    assert west.travel == TravelRange(30, 55, "straight-line estimate")
    assert west.legs[0].label == "Patient to UCR West, in a straight line"


async def test_another_tenants_phone_is_never_offered(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    from tests.support.uow import ensure_audit_heads

    await ensure_audit_heads(neo4j_driver, other_tenant_id)
    from tests.integration.application.test_filter_options import _profile

    async with uow_factory_b() as uow:
        await uow.services.save(_profile("svc-b-only", "Org B Service"))
        await uow.commit()
    await _give_phone(uow_factory_b, "svc-b-only", "01305 900999")

    result = await _run(uow_factory)

    assert all(option.service_id != "svc-b-only" for option in result.options)
    assert all(option.phone != "01305 900999" for option in result.options)
