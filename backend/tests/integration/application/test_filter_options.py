"""Integration tests for FilterOptions (U12), against the real Neo4j the harness starts. Written in
the build wave and NOT RUN there: the batch run happens in the verification stage.

Each test seeds committed units of work and reads back through a fresh one (DEC-004). The services
follow the "Advisor" artboard in docs/spec/ui-screens.md. Clock: Friday 23 October 2026 at 14:13
London (13:13 UTC). The case is 80+, district DT4 (only the district is stored, DEC-067), fall and
frailty, within 2 hrs. Every value is synthetic; the full postcode DT4 8XX must never reach storage
or an audit snapshot.
"""

import dataclasses
from datetime import UTC, date, datetime, timedelta

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedPostcodeLocator, FixedTravelTime
from diucs.application.actor import Actor
from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.filter_options import (
    FilterOptions,
    FilterOptionsCommand,
    FilterOptionsResult,
    Option,
)
from diucs.application.use_cases.query_board import QueryBoard
from diucs.domain.codes import (
    AgeBand,
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    ReferrerType,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
    Urgency,
)
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.case import Case
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, read_tx, write_tx
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 13, tzinfo=UTC)  # 14:13 BST
OPENED = datetime(2026, 10, 23, 13, 10, tzinfo=UTC)
ACTOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
REPORTER = dataclasses.replace(ACTOR, role=Role.REPORTER, practitioner_id=None)
FULL_POSTCODE = "DT4 8XX"
DISTRICT = "DT4"
DISTRICTS = frozenset({"DT1", "DT2", "DT3", "DT4"})
CASE_ID = "case-4821"
UCR_WEST = "svc-ucr-west"
UCR_EAST = "svc-ucr-east"
SDEC_2 = "svc-sdec-2"
HOME = "svc-hospital-at-home"
WARD_D = "svc-ward-d"

PATIENT_SITE = LatLon(lat=50.72, lon=-2.44)
WEST_SITE = LatLon(lat=50.73, lon=-2.45)


def _profile(
    service_id: str,
    name: str,
    *,
    measure: Measure = Measure.REFERRALS_ACCEPTABLE,
    established: int = 8,
    can_exceed: bool = False,
) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=measure,
        unit_label="referrals",
        established_capacity=established,
        can_exceed_established=can_exceed,
        usual_range=(0, established),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day_all_day(),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def _report(
    report_id: str,
    service: ServiceProfile,
    value: int,
    at: datetime,
) -> CapacityReport:
    return CapacityReport(
        id=report_id,
        service_id=service.id,
        value=value,
        measure=service.measure,
        effective_at=at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


def _criteria(service_id: str, accepts: frozenset[NeedCategory] | None = None) -> ServiceCriteria:
    return ServiceCriteria(
        id=f"crit-{service_id}-v1",
        service_id=service_id,
        version=1,
        status=CriteriaStatus.CURRENT,
        age_min=18,
        age_max=None,
        districts=DISTRICTS,
        accepts=accepts
        if accepts is not None
        else frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
        excludes=frozenset(),
        review_by=date(2026, 12, 31),
        owner_role_id="role-lead-west",
    )


def _case(
    urgency: Urgency | None = Urgency.WITHIN_2_HRS,
    case_id: str = CASE_ID,
    reference: str = "4821",
) -> Case:
    return Case(
        id=case_id,
        reference=reference,
        referrer_type=ReferrerType.AMBULANCE_CREW,
        age_band=AgeBand.A80_PLUS,
        postcode=DISTRICT,
        needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        urgency=urgency,
        scores=(),
        opened_at=OPENED,
    )


def _services() -> dict[str, ServiceProfile]:
    return {
        UCR_WEST.removeprefix("svc-"): _profile(UCR_WEST, "UCR West"),
        UCR_EAST.removeprefix("svc-"): _profile(UCR_EAST, "UCR East"),
        SDEC_2.removeprefix("svc-"): _profile(SDEC_2, "SDEC · Site 2"),
        HOME.removeprefix("svc-"): _profile(
            HOME,
            "Hospital at home",
            measure=Measure.OCCUPIED_PATIENTS,
            established=12,
            can_exceed=True,
        ),
    }


async def _seed(factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str) -> None:
    """Services with their criteria and reports, one case, and a position for UCR West."""
    await ensure_audit_heads(driver, tenant)
    services = _services()
    west, east, sdec, home = (
        services[key] for key in ("ucr-west", "ucr-east", "sdec-2", "hospital-at-home")
    )
    async with factory() as uow:
        for profile in services.values():
            await uow.services.save(profile)
            await uow.criteria.add(_criteria(profile.id))
        await uow.capacity.add(
            _report("obs-west", west, 4, datetime(2026, 10, 23, 13, 4, tzinfo=UTC))
        )
        await uow.capacity.add(
            _report("obs-east", east, 1, datetime(2026, 10, 23, 13, 5, tzinfo=UTC))
        )
        await uow.capacity.add(
            _report("obs-sdec", sdec, 0, datetime(2026, 10, 23, 12, 55, tzinfo=UTC))
        )
        await uow.capacity.add(
            _report("obs-home", home, 14, datetime(2026, 10, 23, 12, 58, tzinfo=UTC))
        )
        await uow.cases.add(_case())
        await uow.commit()

    async def locate(tx: AsyncManagedTransaction) -> None:
        # The shape the resource store writes for HealthcareService.location: the Location is its
        # own Resource with a key, and the reference carries its fhirPath (from_graph refuses a
        # reference without one).
        await tx.run(
            "MATCH (s:HealthcareService {id: $service, tenantId: $tenant}) "
            "CREATE (l:Resource:Location {key: 'Location/loc-west', id: 'loc-west', "
            "tenantId: $tenant, positionLatitude: $lat, positionLongitude: $lon}) "
            "CREATE (s)-[:LOCATION {fhirPath: 'HealthcareService.location'}]->(l)",
            service=UCR_WEST,
            tenant=tenant,
            lat=WEST_SITE.lat,
            lon=WEST_SITE.lon,
        )

    await write_tx(driver, locate)


def _filter(
    factory: UnitOfWorkFactory, travel: dict[tuple[LatLon, LatLon], TravelRange] | None = None
) -> FilterOptions:
    clock = FixedClock(NOW)
    return FilterOptions(
        factory,
        clock,
        QueryBoard(factory, clock),
        FixedPostcodeLocator(postcodes={}, districts={DISTRICT: PATIENT_SITE}),
        FixedTravelTime(TravelRange(10, 20, "fixed"), travel),
    )


async def _run(factory: UnitOfWorkFactory, case_id: str = CASE_ID) -> FilterOptionsResult:
    return await _filter(factory).execute(FilterOptionsCommand("filter-1", ACTOR, case_id))


def _option(result: FilterOptionsResult, service_id: str) -> Option:
    found = [option for option in result.options if option.service_id == service_id]
    assert len(found) == 1, f"{service_id} is not an option"
    return found[0]


async def test_ucr_west_is_an_option_that_covers_the_postcode(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    result = await _run(uow_factory)

    west = _option(result, UCR_WEST)
    assert west.status is Status.ACCEPTING
    assert west.effective_available == 4
    assert west.data_age == timedelta(minutes=9)
    assert west.fits[0] == "Covers this postcode"
    assert west.criteria_version == 1


async def test_a_service_that_does_not_take_a_case_need_is_not_suitable_as_outside_criteria(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.criteria.save(
            dataclasses.replace(_criteria(UCR_EAST), accepts=frozenset({NeedCategory.WOUND_CARE}))
        )
        await uow.commit()

    result = await _run(uow_factory)

    assert [item.reason for item in result.not_suitable if item.service_id == UCR_EAST] == [
        "outside criteria"
    ]


async def test_a_service_not_accepting_is_not_suitable_with_its_reason(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    result = await _run(uow_factory)

    reasons = {item.service_id: item.reason for item in result.not_suitable}
    assert reasons[SDEC_2] == "not accepting"
    assert SDEC_2 not in {option.service_id for option in result.options}


async def test_over_capacity_stays_an_option_with_its_warning(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    result = await _run(uow_factory)

    home = _option(result, HOME)
    assert home.status is Status.OVER_CAPACITY
    assert "Over capacity now. Phone to confirm before offering." in home.warnings


async def test_options_sort_by_travel_and_a_service_without_a_position_comes_last(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    ward_d = _profile(WARD_D, "Ward D")
    async with uow_factory() as uow:
        await uow.services.save(ward_d)
        await uow.criteria.add(_criteria(WARD_D))
        await uow.capacity.add(
            _report("obs-ward-d", ward_d, 2, datetime(2026, 10, 23, 13, 6, tzinfo=UTC))
        )
        await uow.commit()
    travel = {(PATIENT_SITE, WEST_SITE): TravelRange(12, 18, "fixed")}

    result = await _filter(uow_factory, travel).execute(
        FilterOptionsCommand("filter-2", ACTOR, CASE_ID)
    )

    order = [option.service_id for option in result.options]
    assert order.index(UCR_WEST) < order.index(WARD_D)
    assert result.options[-1].service_id == WARD_D
    assert result.options[-1].travel is None


async def test_a_case_without_urgency_is_refused_and_the_missing_field_is_named(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.cases.add(_case(urgency=None, case_id="case-no-urgency", reference="4822"))
        await uow.commit()

    with pytest.raises(ValidationFailed) as refused:
        await _run(uow_factory, "case-no-urgency")

    assert refused.value.field == "urgency"


async def test_an_age_band_partly_inside_the_service_limits_warns_the_age_overlap(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        case = await uow.cases.get(CASE_ID)
        assert case is not None
        await uow.cases.save(
            dataclasses.replace(case, age_band=AgeBand.A16_64, urgency=Urgency.TODAY)
        )
        await uow.commit()

    result = await _run(uow_factory)

    assert "Check age: band overlaps the service's age limits" in _option(result, UCR_WEST).warnings


async def test_a_suspended_service_is_never_offered(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.flags.set_service_flag(
            ServiceFlag(
                service_id=UCR_WEST,
                code=SERVICE_FLAG_SUSPENDED,
                active=True,
                reason="lead paused",
                actor_id="prac-lead-1",
                at=NOW,
            )
        )
        await uow.commit()

    result = await _run(uow_factory)

    assert UCR_WEST not in {option.service_id for option in result.options}
    assert {item.reason for item in result.not_suitable if item.service_id == UCR_WEST} == {
        "suspended. Phone to confirm."
    }


async def test_one_audit_record_lists_every_service_and_holds_no_postcode(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    before = await count_nodes(neo4j_driver, "AuditEvent")

    await _run(uow_factory)

    assert await count_nodes(neo4j_driver, "AuditEvent") == before + 1
    async with uow_factory() as uow:
        records = await uow.audit.records()
    entry = records[-1].entry
    assert entry.action == "R"
    assert entry.use_case == "FilterOptions"
    assert entry.snapshot is not None
    services = entry.snapshot["services"]
    assert {row["id"] for row in services} >= {UCR_WEST, UCR_EAST, SDEC_2, HOME}
    assert all(row["criteria_version"] == 1 for row in services)
    text = repr(entry.snapshot)
    assert FULL_POSTCODE not in text
    assert DISTRICT not in text


async def test_the_snapshot_keeps_how_far_over_a_service_was_and_why_one_was_not_suitable(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    """W9G (H-190): a clinician reads what the advisor saw. An over-capacity row holds how far
    over it was (the used count is not a figure), and a row that was not suitable holds a closed
    reason code, never a sentence with an age in it."""
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.criteria.save(
            dataclasses.replace(_criteria(UCR_EAST), accepts=frozenset({NeedCategory.WOUND_CARE}))
        )
        await uow.commit()

    await _run(uow_factory)

    async with uow_factory() as uow:
        records = await uow.audit.records()
    snapshot = records[-1].entry.snapshot
    assert snapshot is not None
    rows = {row["id"]: row for row in snapshot["services"]}
    assert rows[HOME]["over_by"] == 2
    assert rows[HOME]["shown_as"] == "option"
    assert rows[HOME].get("reason") is None
    assert rows[UCR_WEST]["over_by"] is None
    assert rows[SDEC_2]["shown_as"] == "not-suitable"
    assert rows[SDEC_2]["reason"] == "not-accepting"
    assert rows[UCR_EAST]["reason"] == "outside-criteria"


async def test_a_reporter_is_refused_and_nothing_is_audited(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    before = await count_nodes(neo4j_driver, "AuditEvent")

    with pytest.raises(NotAllowed):
        await _filter(uow_factory).execute(FilterOptionsCommand("filter-x", REPORTER, CASE_ID))

    async def audit_total(tx: AsyncManagedTransaction) -> int:
        record = await (
            await tx.run("MATCH (a:AuditEvent {tenantId: $tenant}) RETURN count(a) AS total")
        ).single()
        return int(record["total"])

    assert await count_nodes(neo4j_driver, "AuditEvent") == before
    assert await read_tx(neo4j_driver, audit_total) == before
