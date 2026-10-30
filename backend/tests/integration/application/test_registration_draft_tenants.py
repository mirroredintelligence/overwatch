"""Two-tenant tests for registration drafting and submission (U26, DEC-130 to DEC-132, DEC-142).

Tenant A and tenant B hold the same service id and the same ODS code. A's applicant saves and
submits A's registration; B's registration (a different id) must not change, and a B registration
id given to A's unit of work reads as not found. Registration, scope-list, person and service
statements are tenant-scoped (TEN-010, TEN-011), and so are the contact statements (TEN-014), so
every test here is an ordinary test. Runs on contracted_container() (DEC-159, lesson L168).
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    SaveRegistrationStep,
    SaveRegistrationStepCommand,
    ServiceStep,
    SubmitRegistration,
    SubmitRegistrationCommand,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Registration, ScopeEntry
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import wipe_all
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "ucr-west"
ODS = "RXX01"
INVITED_AT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
A_REGISTRATION = "reg-ucr-west"
B_REGISTRATION = "reg-ucr-west-b"
A_ROLE = "role-applicant-a"
B_ROLE = "role-applicant-b"
APPLICANT = Actor(
    role=Role.OWNER,
    practitioner_id="prac-applicant",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ORG = OrganisationStep(
    name="Community Response Ltd",
    ods_code=ODS,
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
SERVICE_STEP = ServiceStep(
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
    contact_mobile="07700 900123",
)
API = ApiStep(wanted=False)


async def _seed_tenant(
    factory: UnitOfWorkFactory, letter: str, registration_id: str, role_id: str
) -> None:
    async with factory() as uow:
        await uow.services.save(
            ServiceProfile(
                id=SERVICE,
                name="UCR West",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                measure=Measure.REFERRALS_ACCEPTABLE,
                unit_label="referrals",
                established_capacity=8,
                can_exceed_established=False,
                usual_range=(0, 8),
                cadence=Cadence.EVERY_2_HRS,
                available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
                channel=Channel.TEXT,
                limited_level_percent=80,
                active=False,
            )
        )
        await uow.people.save_practitioner(
            Practitioner(
                id="prac-applicant",
                active=True,
                display_name=f"Applicant {letter}",
                phone_hash=None,
            )
        )
        await uow.people.save_role(
            PractitionerRole(
                id=role_id,
                practitioner_id="prac-applicant",
                service_id=SERVICE,
                code=PractitionerRoleCode.COORDINATOR,
                active=True,
                channel=None,
                period_start=INVITED_AT,
            )
        )
        await uow.scope.save_entry(
            ScopeEntry(
                service_id=SERVICE,
                name="UCR West",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
                date=date(2026, 10, 1),
            )
        )
        await uow.registrations.add(
            Registration(
                id=registration_id,
                service_id=SERVICE,
                status=RegistrationStatus.INVITED,
                requester_role_id=role_id,
                owner_role_id=None,
                created_at=INVITED_AT,
                last_modified=INVITED_AT,
            )
        )
        await uow.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    return two_tenant_driver


@pytest_asyncio.fixture(loop_scope="session")
async def tenants(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    two_tenant_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> AsyncIterator[None]:
    await wipe_all(two_tenant_driver)
    await ensure_audit_heads(two_tenant_driver, tenant_id, other_tenant_id)
    await _seed_tenant(uow_factory_a, "a", A_REGISTRATION, A_ROLE)
    await _seed_tenant(uow_factory_b, "b", B_REGISTRATION, B_ROLE)
    yield
    await wipe_all(two_tenant_driver)


def _save(factory: UnitOfWorkFactory) -> SaveRegistrationStep:
    return SaveRegistrationStep(factory, SequentialIds(), FixedClock(NOW))


async def _status_and_draft(
    factory: UnitOfWorkFactory, registration_id: str
) -> tuple[RegistrationStatus, dict]:
    async with factory() as uow:
        found = await uow.registrations.get(registration_id)
    assert found is not None
    return found.status, dict(found.draft)


async def test_a_save_changes_tenant_a_registration_and_nothing_of_tenant_b(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: None,
) -> None:
    await _save(uow_factory_a).execute(
        SaveRegistrationStepCommand("a-org", APPLICANT, A_REGISTRATION, ORG)
    )
    assert (await _status_and_draft(uow_factory_a, A_REGISTRATION))[0] is RegistrationStatus.DRAFT
    status_b, draft_b = await _status_and_draft(uow_factory_b, B_REGISTRATION)
    assert status_b is RegistrationStatus.INVITED
    assert draft_b == {}


async def test_a_tenant_b_registration_id_given_to_tenant_a_is_not_found_and_changes_nothing(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: None,
) -> None:
    from diucs.domain.errors import NotFound

    with pytest.raises(NotFound):
        await _save(uow_factory_a).execute(
            SaveRegistrationStepCommand("a-steal", APPLICANT, B_REGISTRATION, ORG)
        )
    assert (await _status_and_draft(uow_factory_b, B_REGISTRATION))[0] is RegistrationStatus.INVITED


async def test_a_complete_submit_by_tenant_a_submits_only_tenant_a(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: None,
) -> None:
    save = _save(uow_factory_a)
    for number, step in enumerate((ORG, SITE, SERVICE_STEP, REPORTING, API)):
        await save.execute(
            SaveRegistrationStepCommand(f"a-step-{number}", APPLICANT, A_REGISTRATION, step)
        )
    result = await SubmitRegistration(uow_factory_a, SequentialIds(), FixedClock(NOW)).execute(
        SubmitRegistrationCommand("a-submit", APPLICANT, A_REGISTRATION)
    )
    assert result.status is RegistrationStatus.SUBMITTED
    assert (await _status_and_draft(uow_factory_a, A_REGISTRATION))[
        0
    ] is RegistrationStatus.SUBMITTED
    assert (await _status_and_draft(uow_factory_b, B_REGISTRATION))[0] is RegistrationStatus.INVITED


async def test_tenant_b_cannot_read_a_number_tenant_a_stored_for_its_role(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: None,
) -> None:
    await _save(uow_factory_a).execute(
        SaveRegistrationStepCommand("a-reporting", APPLICANT, A_REGISTRATION, REPORTING)
    )
    async with uow_factory_b() as uow:
        assert await uow.contacts.get_phone(A_ROLE) is None
