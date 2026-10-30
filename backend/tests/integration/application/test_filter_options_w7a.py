"""FilterOptions with what the options list and the map read (W7A-A6), against real Neo4j.

The result now carries each option's category and place, the patient's point (the district's
centre), and the two map flags: the postcode is not found, or it is outside every service's area.
The services, criteria, reports and the position of UCR West are the ones of
test_filter_options.py. Two tenants: tenant B holds a service at another position, and tenant A's
options never show it.
"""

import dataclasses
from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedPostcodeLocator, FixedTravelTime
from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.filter_options import (
    FilterOptions,
    FilterOptionsCommand,
    FilterOptionsResult,
)
from diucs.application.use_cases.query_board import QueryBoard
from diucs.domain.codes import ServiceCategory
from tests.integration.application.test_filter_options import (
    ACTOR,
    CASE_ID,
    DISTRICT,
    NOW,
    PATIENT_SITE,
    UCR_EAST,
    UCR_WEST,
    WEST_SITE,
    _case,
    _criteria,
    _option,
    _profile,
    _report,
    _seed,
)
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

OUTSIDE = "DT9"
OUTSIDE_SITE = LatLon(lat=50.9, lon=-2.1)
B_SERVICE = "svc-b-clinic"


def _filter_with(factory: UnitOfWorkFactory, districts: dict[str, LatLon]) -> FilterOptions:
    clock = FixedClock(NOW)
    return FilterOptions(
        factory,
        clock,
        QueryBoard(factory, clock),
        FixedPostcodeLocator(postcodes={}, districts=districts),
        FixedTravelTime(
            TravelRange(10, 20, "fixed"), {(PATIENT_SITE, WEST_SITE): TravelRange(12, 18, "fixed")}
        ),
    )


async def _run(
    factory: UnitOfWorkFactory, districts: dict[str, LatLon], case_id: str = CASE_ID
) -> FilterOptionsResult:
    return await _filter_with(factory, districts).execute(
        FilterOptionsCommand("w7a-filter", ACTOR, case_id)
    )


async def test_an_option_carries_its_category_and_its_place(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    result = await _run(uow_factory, {DISTRICT: PATIENT_SITE})

    west = _option(result, UCR_WEST)
    east = _option(result, UCR_EAST)
    assert west.category is ServiceCategory.URGENT_COMMUNITY_RESPONSE
    assert west.position == WEST_SITE
    assert east.position is None


async def test_the_patients_point_is_the_district_centre(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    result = await _run(uow_factory, {DISTRICT: PATIENT_SITE})

    assert result.patient == PATIENT_SITE
    assert result.not_found is False
    assert result.out_of_area is False


async def test_a_district_the_locator_does_not_know_is_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    result = await _run(uow_factory, {})

    assert result.patient is None
    assert result.not_found is True
    assert all(option.travel is None for option in result.options)


async def test_a_district_no_service_covers_is_out_of_area(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.cases.add(
            dataclasses.replace(_case(case_id="case-outside", reference="4823"), postcode=OUTSIDE)
        )
        await uow.commit()

    result = await _run(
        uow_factory, {DISTRICT: PATIENT_SITE, OUTSIDE: OUTSIDE_SITE}, "case-outside"
    )

    assert result.patient == OUTSIDE_SITE
    assert result.not_found is False
    assert result.out_of_area is True
    assert result.options == ()


async def test_a_service_of_tenant_b_is_neither_an_option_nor_a_reason_to_be_in_area(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await ensure_audit_heads(neo4j_driver, other_tenant_id)
    b_profile = _profile(B_SERVICE, "Clinic B")
    async with uow_factory_b() as uow:
        await uow.services.save(b_profile)
        # Tenant B's criteria cover the district tenant A's case lives in, and only B's do.
        await uow.criteria.add(
            dataclasses.replace(_criteria(B_SERVICE), districts=frozenset({OUTSIDE}))
        )
        await uow.capacity.add(
            _report("obs-b", b_profile, 3, datetime(2026, 10, 23, 13, 6, tzinfo=UTC))
        )
        await uow.commit()
    async with uow_factory() as uow:
        await uow.cases.add(
            dataclasses.replace(_case(case_id="case-outside-a", reference="4824"), postcode=OUTSIDE)
        )
        await uow.commit()

    result = await _run(
        uow_factory, {DISTRICT: PATIENT_SITE, OUTSIDE: OUTSIDE_SITE}, "case-outside-a"
    )

    shown = {option.service_id for option in result.options} | {
        item.service_id for item in result.not_suitable
    }
    assert B_SERVICE not in shown
    assert result.out_of_area is True
