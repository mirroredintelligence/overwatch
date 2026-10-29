"""Integration tests for registration drafting and submission (U26), against the real Neo4j the
harness starts. Each save and each submit is read back in a fresh unit of work. Values are the
synthetic sample values of the prompt: there is no patient data, and no real phone number or
email."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
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
    encode_step,
    read_draft,
)
from diucs.domain.codes import (
    Channel,
    PractitionerRoleCode,
    RegistrationStatus,
    Role,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Registration, ScopeEntry

Seed = Callable[..., Awaitable[None]]
pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "ucr-west"
REGISTRATION = "reg-ucr-west"
APPLICANT_ROLE = "role-applicant-west"
INVITED_AT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
APPLICANT = Actor(
    role=Role.OWNER,
    practitioner_id="prac-applicant",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
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


@pytest.fixture
def seed_registration(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> Callable[..., Awaitable[None]]:
    async def seed(
        status: RegistrationStatus = RegistrationStatus.INVITED, draft: dict | None = None
    ) -> None:
        from diucs.domain.codes import Cadence, Measure
        from diucs.domain.model.service import AvailableTime, ServiceProfile

        profile = ServiceProfile(
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
        await seed_service(profile)
        async with uow_factory() as uow:
            await uow.people.save_practitioner(
                Practitioner(
                    id="prac-applicant", active=True, display_name="Applicant", phone_hash=None
                )
            )
            await uow.people.save_role(
                PractitionerRole(
                    id=APPLICANT_ROLE,
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
                    id=REGISTRATION,
                    service_id=SERVICE,
                    status=status,
                    requester_role_id=APPLICANT_ROLE,
                    owner_role_id=None,
                    created_at=INVITED_AT,
                    last_modified=INVITED_AT,
                    draft=draft or {},
                )
            )
            await uow.commit()

    return seed


def _save(uow_factory: UnitOfWorkFactory, driver: AsyncDriver) -> SaveRegistrationStep:
    return SaveRegistrationStep(
        uow_factory, DriverIdempotencyStore(driver), SequentialIds(), FixedClock(NOW)
    )


def _command(step: object, key: str) -> SaveRegistrationStepCommand:
    return SaveRegistrationStepCommand(key, APPLICANT, REGISTRATION, step)  # type: ignore[arg-type]


async def _registration(uow_factory: UnitOfWorkFactory) -> Registration:
    async with uow_factory() as uow:
        found = await uow.registrations.get(REGISTRATION)
    assert found is not None
    return found


async def test_the_organisation_step_moves_the_invitation_to_draft_and_reads_back_equal(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    await seed_registration()
    result = await _save(uow_factory, neo4j_driver).execute(_command(ORG, "s1"))
    assert result.errors == ()
    assert result.status is RegistrationStatus.DRAFT
    stored = read_draft(await _registration(uow_factory))
    assert stored.organisation == ORG


async def test_a_service_with_no_category_and_a_short_phone_gives_two_screen_errors(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    await seed_registration()
    bad = replace(SERVICE_STEP, category="", spoa_phone="0123")
    result = await _save(uow_factory, neo4j_driver).execute(_command(bad, "s2"))
    assert [(e.field, e.message) for e in result.errors] == [
        ("category", "Choose a category"),
        ("spoa_phone", "Enter a full phone number, for example 01305 123456"),
    ]


async def test_changing_the_service_name_is_refused_and_nothing_is_saved(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    await seed_registration()
    renamed = replace(SERVICE_STEP, service_name="UCR East")
    with pytest.raises(ValidationFailed) as refused:
        await _save(uow_factory, neo4j_driver).execute(_command(renamed, "s3"))
    assert refused.value.field == "service_name"
    assert (await _registration(uow_factory)).status is RegistrationStatus.INVITED


async def test_a_visiting_service_without_districts_has_an_error_on_districts(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    await seed_registration()
    visiting = replace(SITE, fixed_site=False)
    await _save(uow_factory, neo4j_driver).execute(_command(visiting, "s4a"))
    no_districts = replace(SERVICE_STEP, districts="")
    result = await _save(uow_factory, neo4j_driver).execute(_command(no_districts, "s4b"))
    assert [e.field for e in result.errors] == ["districts"]


async def test_submit_with_the_reporting_step_missing_returns_errors_and_stays_draft(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    await seed_registration()
    for n, step in enumerate((ORG, SITE, SERVICE_STEP, API)):
        await _save(uow_factory, neo4j_driver).execute(_command(step, f"m{n}"))
    result = await SubmitRegistration(
        uow_factory, DriverIdempotencyStore(neo4j_driver), SequentialIds(), FixedClock(NOW)
    ).execute(SubmitRegistrationCommand("submit-1", APPLICANT, REGISTRATION))
    assert any(e.field == "reporting" for e in result.errors)
    assert result.status is RegistrationStatus.DRAFT
    assert (await _registration(uow_factory)).status is RegistrationStatus.DRAFT


async def test_a_complete_submit_is_submitted_with_an_outbox_message_and_one_audit_entry(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    await seed_registration()
    for n, step in enumerate((ORG, SITE, SERVICE_STEP, REPORTING, API)):
        await _save(uow_factory, neo4j_driver).execute(_command(step, f"c{n}"))
    result = await SubmitRegistration(
        uow_factory, DriverIdempotencyStore(neo4j_driver), SequentialIds(), FixedClock(NOW)
    ).execute(SubmitRegistrationCommand("submit-2", APPLICANT, REGISTRATION))
    assert result.status is RegistrationStatus.SUBMITTED
    stored = await _registration(uow_factory)
    assert stored.status is RegistrationStatus.SUBMITTED
    assert stored.submitted_at == NOW
    async with uow_factory() as uow:
        pending = await uow.outbox.pending()
        records = await uow.audit.records()
    assert [m.event_type for m in pending].count("RegistrationSubmitted") == 1
    assert len([r for r in records if r.entry.use_case == "SubmitRegistration"]) == 1


async def test_a_resubmit_from_needs_changes_works(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    complete = {
        "organisation": encode_step(ORG),
        "location": encode_step(SITE),
        "service": encode_step(SERVICE_STEP),
        "reporting": encode_step(REPORTING),
        "api": encode_step(API),
    }
    await seed_registration(status=RegistrationStatus.NEEDS_CHANGES, draft=complete)
    async with uow_factory() as uow:
        await uow.contacts.put_phone(APPLICANT_ROLE, REPORTING.contact_mobile)
        await uow.commit()
    submit = SubmitRegistration(
        uow_factory, DriverIdempotencyStore(neo4j_driver), SequentialIds(), FixedClock(NOW)
    )
    result = await submit.execute(SubmitRegistrationCommand("submit-3", APPLICANT, REGISTRATION))
    assert result.status is RegistrationStatus.SUBMITTED
    assert (await _registration(uow_factory)).status is RegistrationStatus.SUBMITTED


async def test_a_submit_from_in_review_is_refused_and_changes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    await seed_registration(status=RegistrationStatus.IN_REVIEW)
    submit = SubmitRegistration(
        uow_factory, DriverIdempotencyStore(neo4j_driver), SequentialIds(), FixedClock(NOW)
    )
    with pytest.raises(InvalidTransition):
        await submit.execute(SubmitRegistrationCommand("submit-4", APPLICANT, REGISTRATION))
    assert (await _registration(uow_factory)).status is RegistrationStatus.IN_REVIEW


async def test_the_reporting_mobile_is_kept_only_on_the_protected_contact_node(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_registration: Seed
) -> None:
    await seed_registration()
    await _save(uow_factory, neo4j_driver).execute(_command(REPORTING, "r1"))
    stored = await _registration(uow_factory)
    assert "07700 900123" not in repr(stored.draft)
    assert "contact_mobile" not in stored.draft.get("reporting", {})
    async with uow_factory() as uow:
        assert await uow.contacts.get_phone(APPLICANT_ROLE) == "07700 900123"
