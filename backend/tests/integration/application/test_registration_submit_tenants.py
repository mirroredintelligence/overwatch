"""Two-tenant tests for registration persistence (U27, DEC-130 to DEC-132, DEC-142).

Tenant A and tenant B hold a submitted registration with the same registration and service ids and
the same ODS code, and both cover the district DT3. Persisting A's registration writes A's
resources only, reuses A's district Location and never B's, and a B registration id given to A's
unit of work reads as not found. Runs on contracted_container() (DEC-159, lesson L168).

NOT RUN in the build wave: the batch verification run proves it.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedGeocoder
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_terminology import FixedTerminology
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
from diucs.domain.codes import PractitionerRoleCode, RegistrationStatus, ScopeFlag, ServiceCategory
from diucs.domain.errors import NotFound
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Registration, ScopeEntry
from tests.support.neo4j import count_nodes, wipe_all
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
SERVICE_ID = "svc-ucr-west"
REGISTRATION_ID = "reg-ucr-west"
ROLE_ID = "role-applicant"
STEPS = {
    "organisation": OrganisationStep(
        name="Community Response Ltd",
        ods_code="RXX01",
        org_type="nhs-trust",
        contact_name="Sam Patel",
        contact_email="sam.patel@example.org",
    ),
    "location": LocationStep(fixed_site=False),
    "service": ServiceStep(
        service_name="UCR West",
        category="urgent-community-response",
        referral_methods="phone",
        spoa_phone="01305 123456",
        accepting_days="mon,tue",
        accepting_start="08:00",
        accepting_end="20:00",
        needs="frailty",
        age_min=18,
        no_age_limit=True,
        no_exclusions=True,
        owner_role="Clinical lead",
        owner_email="owner@example.org",
        review_by=date(2027, 1, 1),
        districts="DT3",
    ),
    "reporting": ReportingStep(
        measure="referrals-acceptable",
        usual_low=0,
        usual_high=8,
        cadence="every-2-hrs",
        channel="text",
        holder_name="Duty coordinator",
    ),
    "api": ApiStep(wanted=False),
}


async def _seed(factory: UnitOfWorkFactory) -> None:
    async with factory() as uow:
        await uow.scope.save_entry(
            ScopeEntry(
                service_id=SERVICE_ID,
                name="UCR West",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
                date=date(2026, 10, 29),
            )
        )
        await uow.people.save_practitioner(
            Practitioner(
                id="prac-applicant", active=True, display_name="Applicant", phone_hash=None
            )
        )
        await uow.people.save_role(
            PractitionerRole(
                id=ROLE_ID,
                practitioner_id="prac-applicant",
                service_id=SERVICE_ID,
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=None,
                period_start=NOW,
            )
        )
        await uow.registrations.add(
            Registration(
                id=REGISTRATION_ID,
                service_id=SERVICE_ID,
                status=RegistrationStatus.SUBMITTED,
                requester_role_id=ROLE_ID,
                owner_role_id=None,
                created_at=NOW,
                last_modified=NOW,
                submitted_at=NOW,
                draft={key: encode_step(step) for key, step in STEPS.items()},
            )
        )
        await uow.commit()


def _persist(factory: UnitOfWorkFactory) -> PersistRegistration:
    return PersistRegistration(
        factory,
        FixedGeocoder({}),
        FixedTerminology({}, {}),
        SequentialIds("gen"),
        FixedClock(NOW),
    )


@pytest_asyncio.fixture(loop_scope="session")
async def two_tenants(
    tenant_id: str, other_tenant_id: str
) -> AsyncIterator[tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory]]:
    async with contracted_container() as driver:
        await wipe_all(driver)
        await ensure_audit_heads(driver, tenant_id, other_tenant_id)
        factory_a = tenant_uow_factory(driver, tenant_id)
        factory_b = tenant_uow_factory(driver, other_tenant_id)
        await _seed(factory_a)
        await _seed(factory_b)
        yield driver, factory_a, factory_b


async def test_persisting_in_a_changes_a_only_and_b_keeps_its_own_registration_unwritten(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    driver, factory_a, factory_b = two_tenants

    result = await _persist(factory_a).execute(PersistRegistrationCommand(REGISTRATION_ID))

    assert result.persisted is True
    async with factory_a() as uow_a:
        a = await uow_a.registrations.get(REGISTRATION_ID)
    async with factory_b() as uow_b:
        b = await uow_b.registrations.get(REGISTRATION_ID)
    assert a is not None and lookups_of(a) is not None
    assert b is not None and lookups_of(b) is None
    assert await count_nodes(driver, "Organization") == 1


async def test_the_same_district_in_two_tenants_is_two_locations_and_each_reuses_its_own(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    driver, factory_a, factory_b = two_tenants

    await _persist(factory_a).execute(PersistRegistrationCommand(REGISTRATION_ID))
    await _persist(factory_b).execute(PersistRegistrationCommand(REGISTRATION_ID))

    assert await count_nodes(driver, "Location") == 2
    async with factory_a() as uow_a:
        found_a = await uow_a.registrations.district_locations(["DT3"])
    async with factory_b() as uow_b:
        found_b = await uow_b.registrations.district_locations(["DT3"])
    assert set(found_a) == set(found_b) == {"DT3"}


async def test_a_registration_of_another_tenant_reads_as_not_found(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    _, factory_a, factory_b = two_tenants
    async with factory_b() as uow:
        registration = await uow.registrations.get(REGISTRATION_ID)
        assert registration is not None
        await uow.registrations.add(replace(registration, id="reg-only-in-b"))
        await uow.commit()

    with pytest.raises(NotFound):
        await _persist(factory_a).execute(PersistRegistrationCommand("reg-only-in-b"))
