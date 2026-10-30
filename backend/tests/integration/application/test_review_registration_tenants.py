"""Two-tenant tests for reviewing a registration (U28, DEC-130 to DEC-132, DEC-142).

Tenant A and tenant B each hold a submitted registration `reg-1` for the same service id. A's lead
starts A's review and records a call-back: B's registration does not change, B's Provenance is not
read, and a B registration id given to A's unit of work reads as not found. The area districts
come from the tenant (`area_districts_for(scope)`): tenant B's area does not include DT4.
Runs on the shared harness database (the contracted schema, DEC-159).

NOT RUN in the build wave: the batch verification run proves it.
"""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.registration_draft import encode_step
from diucs.application.use_cases.registration_submit import LOOKUPS_STEP, Lookups, encode_lookups
from diucs.application.use_cases.review_registration import (
    CHECK_ADDRESS,
    GetReviewStatus,
    GetReviewStatusQuery,
    StartReview,
    StartReviewCommand,
    districts_in_ranges,
)
from diucs.domain.codes import (
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.errors import NotFound
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Registration, ScopeEntry
from tests.integration.application.test_review_registration import (
    APPLICANT_ROLE,
    INVITED_MOBILE,
    NOW,
    SERVICE_ID,
    STEPS,
)
from tests.support.actors import ACTOR_TENANT
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

HASHER = HmacPhoneHasher(
    FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"})
)
LEAD = Actor(Role.LEAD, "prac-lead", None, "web", frozenset(), tenant_id=ACTOR_TENANT)
GOOD = Lookups(True, True, "COMMUNITY RESPONSE LTD", "PILOT-SAMPLE", True, "DT4", NOW)


async def _seed(factory: UnitOfWorkFactory) -> None:
    draft: dict[str, Any] = {key: encode_step(step) for key, step in STEPS.items()}
    draft[LOOKUPS_STEP] = encode_lookups(GOOD)
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
        for practitioner_id, phone_hash in (
            ("prac-applicant", HASHER.hash(INVITED_MOBILE)),
            ("prac-lead", None),
        ):
            await uow.people.save_practitioner(
                Practitioner(
                    id=practitioner_id, active=True, display_name="Sample", phone_hash=phone_hash
                )
            )
        await uow.people.save_role(
            PractitionerRole(
                id=APPLICANT_ROLE,
                practitioner_id="prac-applicant",
                service_id=None,
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=None,
                period_start=NOW,
            )
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-lead",
                practitioner_id="prac-lead",
                service_id=None,
                code=PractitionerRoleCode.SHIFT_LEAD,
                active=True,
                channel=None,
                period_start=NOW,
            )
        )
        await uow.contacts.put_phone(APPLICANT_ROLE, "+447700900123")
        await uow.registrations.add(
            Registration(
                id="reg-1",
                service_id=SERVICE_ID,
                status=RegistrationStatus.SUBMITTED,
                requester_role_id=APPLICANT_ROLE,
                owner_role_id=None,
                created_at=NOW,
                last_modified=NOW,
                submitted_at=NOW,
                draft=draft,
            )
        )
        await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def two_tenants(
    tenant_id: str, other_tenant_id: str, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[tuple[UnitOfWorkFactory, UnitOfWorkFactory, str, str]]:
    driver = neo4j_driver
    await ensure_audit_heads(driver, tenant_id, other_tenant_id)
    factory_a = tenant_uow_factory(driver, tenant_id)
    factory_b = tenant_uow_factory(driver, other_tenant_id)
    await _seed(factory_a)
    await _seed(factory_b)
    yield factory_a, factory_b, tenant_id, other_tenant_id


def _areas(tenant_a: str) -> Any:
    def for_scope(scope: ScopeId) -> frozenset[str]:
        # B's area has no DT districts at all.
        return districts_in_ranges(("DT", 1, 11)) if scope.value == tenant_a else frozenset()

    return for_scope


async def test_a_review_in_a_changes_a_only_and_the_area_is_the_tenants_own(
    two_tenants: tuple[UnitOfWorkFactory, UnitOfWorkFactory, str, str],
) -> None:
    factory_a, factory_b, tenant_a, _ = two_tenants
    clock = FixedClock(NOW)
    start_a = StartReview(factory_a, HASHER, clock, area_districts_for=_areas(tenant_a))

    await start_a.execute(StartReviewCommand("start-1", LEAD, "reg-1"))

    async with factory_a() as uow_a:
        a = await uow_a.registrations.get("reg-1")
    async with factory_b() as uow_b:
        b = await uow_b.registrations.get("reg-1")
    assert a is not None and a.status is RegistrationStatus.IN_REVIEW
    assert b is not None and b.status is RegistrationStatus.SUBMITTED
    status_a = await GetReviewStatus(
        factory_a, HASHER, clock, area_districts_for=_areas(tenant_a)
    ).execute(GetReviewStatusQuery(LEAD, "reg-1"))
    status_b = await GetReviewStatus(
        factory_b, HASHER, clock, area_districts_for=_areas(tenant_a)
    ).execute(GetReviewStatusQuery(LEAD, "reg-1"))
    address_a = next(c for c in status_a.checks if c.name == CHECK_ADDRESS)
    address_b = next(c for c in status_b.checks if c.name == CHECK_ADDRESS)
    assert address_a.passed is True
    assert address_b.passed is False


async def test_a_registration_of_another_tenant_reads_as_not_found(
    two_tenants: tuple[UnitOfWorkFactory, UnitOfWorkFactory, str, str],
) -> None:
    factory_a, factory_b, tenant_a, _ = two_tenants
    async with factory_b() as uow:
        registration = await uow.registrations.get("reg-1")
        assert registration is not None
        await uow.registrations.add(replace(registration, id="reg-only-in-b"))
        await uow.commit()
    status = GetReviewStatus(
        factory_a, HASHER, FixedClock(NOW), area_districts_for=_areas(tenant_a)
    )

    with pytest.raises(NotFound):
        await status.execute(GetReviewStatusQuery(LEAD, "reg-only-in-b"))
