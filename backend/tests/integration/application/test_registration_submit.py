"""Integration tests for registration persistence (U27), against the real Neo4j the harness starts.
A submitted registration is turned into draft FHIR resources and written in one transaction; each
assertion reads back through a fresh unit of work or the harness helpers. Values are the synthetic
samples of the prompt: there is no patient data, and no real phone number or email.

NOT RUN in the build wave (no Neo4j in the builder's environment, build-wave rules): the batch
verification run proves them.
"""

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.audit_neo4j.outbox import Neo4jOutbox
from diucs.adapters.outbound.graph_store.unit_of_work import DEFAULT_FACTORIES, neo4j_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedGeocoder
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_terminology import FixedTerminology
from diucs.application.ports.outbound.geo import AddressCandidate, LatLon
from diucs.application.ports.outbound.terminology import OdsRecord
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    ServiceStep,
    encode_step,
)
from diucs.application.use_cases.registration_submit import (
    PersistRegistration,
    PersistRegistrationCommand,
    lookups_of,
)
from diucs.domain.codes import (
    CriteriaStatus,
    PractitionerRoleCode,
    RegistrationStatus,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Registration, ScopeEntry
from tests.support.neo4j import count_nodes, read_tx, run_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
REPORTER_MOBILE = "07700 900123"
CANDIDATE = AddressCandidate(
    uprn="100012345678",
    line="1 Sample Road",
    town="Weymouth",
    postcode="DT4 8XX",
    position=LatLon(50.6144, -2.4547),
)
ORG = OrganisationStep(
    name="Community Response Ltd",
    ods_code="RXX01",
    org_type="nhs-trust",
    contact_name="Sam Patel",
    contact_email="sam.patel@example.org",
)
SITE = LocationStep(
    fixed_site=True,
    postcode="DT4 8XX",
    address="1 Sample Road, Weymouth",
    site_name="Sample Ward",
    site_type="ward",
    open_24h=True,
)
VISITING = LocationStep(fixed_site=False)
SERVICE = ServiceStep(
    service_name="UCR West",
    category="urgent-community-response",
    referral_methods="phone,e-referral",
    spoa_phone="01305 123456",
    accepting_days="mon,tue,wed,thu,fri",
    accepting_start="08:00",
    accepting_end="20:00",
    needs="frailty,wound-care",
    age_min=18,
    no_age_limit=True,
    no_exclusions=True,
    owner_role="Clinical lead, UCR",
    owner_email="owner@example.org",
    review_by=date(2027, 1, 1),
    districts="DT4",
)
REPORTING = ReportingStep(
    measure="referrals-acceptable",
    usual_low=0,
    usual_high=8,
    cadence="every-2-hrs",
    channel="text",
    holder_name="Duty coordinator",
)


def _draft(location: LocationStep, service: ServiceStep) -> dict[str, dict[str, Any]]:
    steps = {
        "organisation": ORG,
        "location": location,
        "service": service,
        "reporting": REPORTING,
        "api": ApiStep(wanted=False),
    }
    return {key: encode_step(step) for key, step in steps.items()}


async def _seed(
    uow_factory: UnitOfWorkFactory,
    number: int,
    location: LocationStep,
    service: ServiceStep,
    name: str,
) -> tuple[str, str]:
    """A scope entry (the inactive placeholder service), the applicant's post with the reporter's
    mobile in the protected store, and a submitted registration with its draft."""
    service_id = f"svc-{number}"
    registration_id = f"reg-{number}"
    role_id = f"role-applicant-{number}"
    async with uow_factory() as uow:
        await uow.scope.save_entry(
            ScopeEntry(
                service_id=service_id,
                name=name,
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
                date=date(2026, 10, 29),
            )
        )
        await uow.people.save_practitioner(
            Practitioner(
                id=f"prac-{number}", active=True, display_name="Applicant", phone_hash=None
            )
        )
        await uow.people.save_role(
            PractitionerRole(
                id=role_id,
                practitioner_id=f"prac-{number}",
                service_id=service_id,
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=None,
                period_start=NOW,
            )
        )
        await uow.contacts.put_phone(role_id, REPORTER_MOBILE)
        await uow.registrations.add(
            Registration(
                id=registration_id,
                service_id=service_id,
                status=RegistrationStatus.SUBMITTED,
                requester_role_id=role_id,
                owner_role_id=None,
                created_at=NOW,
                last_modified=NOW,
                submitted_at=NOW,
                draft=_draft(location, replace(service, service_name=name)),
            )
        )
        await uow.commit()
    return service_id, registration_id


def _persist(
    uow_factory: UnitOfWorkFactory, ids: SequentialIds | None = None
) -> PersistRegistration:
    return PersistRegistration(
        uow_factory,
        FixedGeocoder({"DT4 8XX": [CANDIDATE]}),
        FixedTerminology(
            {
                "RXX01": OdsRecord(
                    "RXX01", "COMMUNITY RESPONSE LTD", True, "PILOT-SAMPLE", "DT4 8XX"
                )
            },
            {},
        ),
        ids or SequentialIds("gen"),
        FixedClock(NOW),
    )


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: Any) -> list[dict[str, Any]]:
        return await (await tx.run(cypher, **params)).data()

    return await read_tx(driver, work)


@pytest.fixture(autouse=True)
async def _graph(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    await ensure_audit_head(neo4j_driver)


async def test_a_fixed_site_registration_is_written_as_drafts_with_its_links_and_lookups(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    service_id, registration_id = await _seed(uow_factory, 1, SITE, SERVICE, "UCR West")

    result = await _persist(uow_factory).execute(PersistRegistrationCommand(registration_id))

    assert result.persisted is True
    async with uow_factory() as uow:
        profile = await uow.services.get(service_id)
        registration = await uow.registrations.get(registration_id)
    assert profile is not None
    assert profile.active is False
    assert profile.name == "UCR West"
    assert profile.established_capacity == 8
    assert registration is not None
    assert registration.status is RegistrationStatus.SUBMITTED
    lookups = lookups_of(registration)
    assert lookups is not None
    assert (lookups.ods_found, lookups.address_found) == (True, True)
    criteria = await _rows(
        neo4j_driver,
        "MATCH (c:ServiceCriteria)-[:SUBJECT]->(:HealthcareService {id: $id}) "
        "RETURN c.version AS version, c.status AS status",
        id=service_id,
    )
    assert criteria == [{"version": 1, "status": CriteriaStatus.PENDING_APPROVAL.value}]
    provided = await _rows(
        neo4j_driver,
        "MATCH (:HealthcareService {id: $id, active: false})-[:PROVIDED_BY]->"
        "(o:Organization {active: false}) RETURN o.odsCode AS ods",
        id=service_id,
    )
    assert provided == [{"ods": "RXX01"}]
    located = await _rows(
        neo4j_driver,
        "MATCH (:HealthcareService {id: $id})-[:LOCATION]->(l:Location {status: 'inactive'}) "
        "RETURN l.positionLatitude AS lat, l.ext_geocodeSource AS source",
        id=service_id,
    )
    assert located == [{"lat": 50.6144, "source": "os-places"}]


async def test_the_reporters_mobile_is_found_only_on_the_protected_contact_node(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    _, registration_id = await _seed(uow_factory, 1, SITE, SERVICE, "UCR West")

    await _persist(uow_factory).execute(PersistRegistrationCommand(registration_id))

    async def read_nodes(tx: Any) -> list[dict[str, Any]]:
        return await (await run_nodes(tx, "labels(n) AS labels, properties(n) AS p")).data()

    nodes = await read_tx(neo4j_driver, read_nodes)
    holding = {
        tuple(row["labels"])
        for row in nodes
        for value in row["p"].values()
        if isinstance(value, str) and ("07700 900123" in value or "07700900123" in value)
    }
    assert holding == {("ProtectedContact",)}


async def test_a_visiting_service_gets_district_locations_and_a_second_one_reuses_them(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    _, first = await _seed(
        uow_factory, 1, VISITING, replace(SERVICE, districts="DT3,DT4"), "UCR West"
    )
    _, second = await _seed(uow_factory, 2, VISITING, replace(SERVICE, districts="DT3"), "UCR East")

    # One id generator for both: a fresh one would hand out the first one's ids a second time.
    ids = SequentialIds("gen")
    await _persist(uow_factory, ids).execute(PersistRegistrationCommand(first))
    assert await count_nodes(neo4j_driver, "Location") == 2
    await _persist(uow_factory, ids).execute(PersistRegistrationCommand(second))

    assert await count_nodes(neo4j_driver, "Location") == 2
    areas = await _rows(
        neo4j_driver,
        "MATCH (s:HealthcareService {id: 'svc-2'})-[:COVERAGE_AREA]->(l:Location) "
        "RETURN l.name AS name",
    )
    assert areas == [{"name": "DT3"}]
    positioned = await _rows(
        neo4j_driver, "MATCH (l:Location) WHERE l.positionLatitude IS NOT NULL RETURN l.id AS id"
    )
    assert positioned == []


async def test_a_failure_on_the_last_write_leaves_nothing_of_the_bundle_the_audit_or_the_outbox(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    service_id, registration_id = await _seed(uow_factory, 1, SITE, SERVICE, "UCR West")
    audits_before = await count_nodes(neo4j_driver, "AuditEvent")
    outbox_before = await count_nodes(neo4j_driver, "OutboxMessage")

    class FailingOutbox:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        async def add(self, message: Any) -> None:
            raise RuntimeError("the last write failed")

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    failing = neo4j_uow_factory(
        neo4j_driver,
        factories={**DEFAULT_FACTORIES, "outbox": lambda tx, store: FailingOutbox(Neo4jOutbox(tx))},
    )

    with pytest.raises(RuntimeError):
        await _persist(failing).execute(PersistRegistrationCommand(registration_id))

    assert await count_nodes(neo4j_driver, "Organization") == 0
    assert await count_nodes(neo4j_driver, "Location") == 0
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == audits_before
    assert await count_nodes(neo4j_driver, "OutboxMessage") == outbox_before
    async with uow_factory() as uow:
        entry = await uow.scope.get_entry(service_id)
        registration = await uow.registrations.get(registration_id)
    assert entry is not None  # the placeholder service is as it was: a name and a category only
    assert registration is not None
    assert lookups_of(registration) is None


async def test_persisting_twice_writes_the_resources_once(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    _, registration_id = await _seed(uow_factory, 1, SITE, SERVICE, "UCR West")
    persist = _persist(uow_factory)

    first = await persist.execute(PersistRegistrationCommand(registration_id))
    second = await persist.execute(PersistRegistrationCommand(registration_id))

    assert (first.persisted, second.persisted) == (True, False)
    assert await count_nodes(neo4j_driver, "Organization") == 1
    assert await count_nodes(neo4j_driver, "ServiceCriteria") == 1
