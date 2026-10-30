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
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
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


# ---------------------------------------------------------------------------------------------
# W50 (W9H, DEC-1045, DEC-1046): the districts offered when the postcode is not found or out of
# area. They are the districts this tenant's services cover, that the locator can place, nearest
# first (or, with no place for the patient, those of the case's own postcode area first). Sent only
# when one of the two flags is, and never another tenant's.

NEAR_B_SITE = LatLon(lat=50.8, lon=-2.2)
FAR_SITE = LatLon(lat=51.2, lon=-1.8)
CASE_UNKNOWN = "case-unknown-district"


async def _add_case(
    factory: UnitOfWorkFactory, case_id: str, reference: str, district: str
) -> None:
    async with factory() as uow:
        await uow.cases.add(
            dataclasses.replace(_case(case_id=case_id, reference=reference), postcode=district)
        )
        await uow.commit()


async def test_out_of_area_offers_the_covered_districts_the_locator_knows_nearest_first(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await _add_case(uow_factory, "case-outside", "4823", OUTSIDE)

    # DT3 is covered but the locator has no place for it: it is left out, not offered as a dead end.
    result = await _run(
        uow_factory,
        {
            OUTSIDE: OUTSIDE_SITE,
            "DT1": FAR_SITE,
            "DT2": NEAR_B_SITE,
            DISTRICT: LatLon(lat=50.95, lon=-2.15),
        },
        "case-outside",
    )

    assert result.out_of_area is True
    assert result.districts == ("DT4", "DT2", "DT1")


async def test_a_district_the_locator_does_not_know_is_offered_the_districts_of_its_own_area_first(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await _add_case(uow_factory, CASE_UNKNOWN, "4825", "DT99")

    result = await _run(
        uow_factory,
        {"DT3": PATIENT_SITE, "DT1": WEST_SITE, DISTRICT: FAR_SITE},
        CASE_UNKNOWN,
    )

    assert result.not_found is True
    assert result.districts == ("DT1", "DT3", "DT4")


async def test_a_found_covered_district_is_offered_no_districts(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    result = await _run(uow_factory, {DISTRICT: PATIENT_SITE, "DT1": WEST_SITE})

    assert (result.not_found, result.out_of_area) == (False, False)
    assert result.districts == ()


async def test_a_suspended_services_districts_are_not_offered(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    only = _profile("svc-only-dt7", "Only DT7")
    async with uow_factory() as uow:
        await uow.services.save(only)
        await uow.criteria.add(
            dataclasses.replace(_criteria(only.id), districts=frozenset({"DT7"}))
        )
        await uow.capacity.add(
            _report("obs-dt7", only, 3, datetime(2026, 10, 23, 13, 6, tzinfo=UTC))
        )
        await uow.flags.set_service_flag(
            ServiceFlag(
                service_id=only.id,
                code=SERVICE_FLAG_SUSPENDED,
                active=True,
                reason="lead paused",
                actor_id="prac-lead-1",
                at=NOW,
            )
        )
        await uow.commit()
    await _add_case(uow_factory, CASE_UNKNOWN, "4825", "DT99")

    result = await _run(uow_factory, {"DT7": PATIENT_SITE, "DT1": WEST_SITE}, CASE_UNKNOWN)

    assert result.districts == ("DT1",)


async def test_the_districts_offered_are_this_tenants_and_never_tenant_bs(
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
        await uow.criteria.add(
            dataclasses.replace(_criteria(B_SERVICE), districts=frozenset({"BH1", "BH2", OUTSIDE}))
        )
        await uow.capacity.add(
            _report("obs-b", b_profile, 3, datetime(2026, 10, 23, 13, 6, tzinfo=UTC))
        )
        await uow.commit()
    await _add_case(uow_factory, "case-outside-a", "4824", OUTSIDE)

    # The locator knows B's districts too: only the bound tenant's criteria decide what is offered.
    result = await _run(
        uow_factory,
        {
            OUTSIDE: OUTSIDE_SITE,
            "BH1": OUTSIDE_SITE,
            "BH2": OUTSIDE_SITE,
            "DT1": NEAR_B_SITE,
            "DT2": FAR_SITE,
        },
        "case-outside-a",
    )

    assert result.out_of_area is True
    assert result.districts == ("DT1", "DT2")
    assert not {"BH1", "BH2"} & set(result.districts)
