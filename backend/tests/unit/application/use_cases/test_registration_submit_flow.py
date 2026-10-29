"""PersistRegistration, and SubmitRegistration with it, against recording stand-ins for their ports
(U27): what is written, in which unit, and that a failure leaves nothing. The geocoder and the ODS
terminology are the specs' fixed-table fakes (external providers). What is really stored, read back
from Neo4j, is in tests/integration/application/test_registration_submit.py. Sample values only."""

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedGeocoder
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_terminology import FixedTerminology
from diucs.application.actor import Actor
from diucs.application.ports.outbound.geo import AddressCandidate, LatLon
from diucs.application.ports.outbound.lookups import TransientLookupError
from diucs.application.ports.outbound.terminology import OdsRecord
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    ServiceStep,
    SubmitRegistration,
    SubmitRegistrationCommand,
    encode_step,
)
from diucs.application.use_cases.registration_submit import (
    LOOKUPS_STEP,
    PersistRegistration,
    PersistRegistrationCommand,
    lookups_of,
)
from diucs.domain.codes import PractitionerRoleCode, RegistrationStatus, Role
from diucs.domain.errors import InvalidTransition, NotFound
from diucs.domain.events import RegistrationPersisted
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.registration import Registration
from tests.support.actors import ACTOR_TENANT
from tests.support.registration_rig import StubUnits

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
SERVICE_ID = "svc-ucr-west"
APPLICANT_ROLE = "role-applicant"
OWNER_EMAIL = "owner@example.org"
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
    owner_email=OWNER_EMAIL,
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
APPLICANT = Actor(
    role=Role.OWNER,
    practitioner_id="prac-applicant",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


def _draft(**steps: Any) -> dict[str, dict[str, Any]]:
    values: dict[str, Any] = {
        "organisation": ORG,
        "location": SITE,
        "service": SERVICE,
        "reporting": REPORTING,
        "api": ApiStep(wanted=False),
    }
    values.update(steps)
    keys = {
        "organisation": "organisation",
        "location": "location",
        "service": "service",
        "reporting": "reporting",
        "api": "api",
    }
    return {keys[name]: encode_step(step) for name, step in values.items()}


class World:
    def __init__(self, status: RegistrationStatus = RegistrationStatus.SUBMITTED) -> None:
        self.units = StubUnits()
        self.clock = FixedClock(NOW)
        self.ids = SequentialIds("id")
        self.units.registrations.held["reg-1"] = Registration(
            id="reg-1",
            service_id=SERVICE_ID,
            status=status,
            requester_role_id=APPLICANT_ROLE,
            owner_role_id=None,
            created_at=NOW,
            last_modified=NOW,
            draft=_draft(),
        )
        self.units.people.roles[APPLICANT_ROLE] = PractitionerRole(
            id=APPLICANT_ROLE,
            practitioner_id="prac-applicant",
            service_id=SERVICE_ID,
            code=PractitionerRoleCode.DUTY_MANAGER,
            active=True,
            channel=None,
            period_start=NOW,
        )
        self.units.contacts.phones[APPLICANT_ROLE] = "07700 900123"
        self.geocoder = FixedGeocoder({"DT4 8XX": [CANDIDATE]})
        self.terminology = FixedTerminology(
            {
                "RXX01": OdsRecord(
                    code="RXX01",
                    name="COMMUNITY RESPONSE LTD",
                    active=True,
                    org_type="PILOT-SAMPLE",
                    postcode="DT4 8XX",
                )
            },
            {},
        )
        self.persist = PersistRegistration(
            self.units, self.geocoder, self.terminology, self.ids, self.clock
        )

    def registration(self) -> Registration:
        return self.units.registrations.held["reg-1"]


COMMAND = PersistRegistrationCommand("reg-1")


async def test_persisting_writes_one_bundle_with_the_geocoded_position_and_commits_once() -> None:
    world = World()

    result = await world.persist.execute(COMMAND)

    assert result.persisted is True
    assert result.service_id == SERVICE_ID
    assert len(world.units.registrations.bundles) == 1
    bundle = world.units.registrations.bundles[0]
    assert [e["resource"]["resourceType"] for e in bundle["entry"]] == [
        "Organization",
        "Location",
        "HealthcareService",
        "Basic",
    ]
    location = bundle["entry"][1]["resource"]
    assert location["position"] == {"latitude": 50.6144, "longitude": -2.4547}
    assert world.units.commits == 1


async def test_the_lookup_result_is_kept_on_the_registration_for_the_review() -> None:
    world = World()

    await world.persist.execute(COMMAND)

    lookups = lookups_of(world.registration())
    assert lookups is not None
    assert lookups.ods_found is True
    assert lookups.ods_active is True
    assert lookups.ods_name == "COMMUNITY RESPONSE LTD"
    assert lookups.ods_type == "PILOT-SAMPLE"
    assert lookups.address_found is True
    assert lookups.address_district == "DT4"
    assert lookups.checked_at == NOW
    assert LOOKUPS_STEP in world.registration().draft
    assert world.registration().status is RegistrationStatus.SUBMITTED
    assert world.registration().last_modified == NOW


async def test_an_ods_code_that_is_not_found_does_not_stop_the_registration() -> None:
    world = World()
    world.terminology = FixedTerminology({}, {})
    world.persist = PersistRegistration(
        world.units, world.geocoder, world.terminology, world.ids, world.clock
    )

    result = await world.persist.execute(COMMAND)

    assert result.persisted is True
    lookups = lookups_of(world.registration())
    assert lookups is not None
    assert lookups.ods_found is False
    assert lookups.ods_name is None


async def test_an_inactive_ods_record_is_kept_as_inactive() -> None:
    world = World()
    world.terminology = FixedTerminology(
        {"RXX01": OdsRecord("RXX01", "OLD NAME", False, "PILOT-SAMPLE", None)}, {}
    )
    world.persist = PersistRegistration(
        world.units, world.geocoder, world.terminology, world.ids, world.clock
    )

    await world.persist.execute(COMMAND)

    lookups = lookups_of(world.registration())
    assert lookups is not None
    assert (lookups.ods_found, lookups.ods_active) == (True, False)


async def test_an_address_the_geocoder_does_not_know_leaves_the_site_without_a_position() -> None:
    world = World()
    world.geocoder = FixedGeocoder({})
    world.persist = PersistRegistration(
        world.units, world.geocoder, world.terminology, world.ids, world.clock
    )

    await world.persist.execute(COMMAND)

    location = world.units.registrations.bundles[0]["entry"][1]["resource"]
    assert "position" not in location
    lookups = lookups_of(world.registration())
    assert lookups is not None
    assert lookups.address_found is False
    assert lookups.address_district is None


async def test_the_criteria_owner_gets_a_practitioner_a_post_and_a_protected_email() -> None:
    world = World()

    await world.persist.execute(COMMAND)

    posts = [
        role
        for role in world.units.people.roles.values()
        if role.code is PractitionerRoleCode.CRITERIA_OWNER
    ]
    assert len(posts) == 1
    post = posts[0]
    assert post.service_id == SERVICE_ID
    assert world.units.contacts.emails == {post.id: OWNER_EMAIL}
    owner = world.units.people.practitioners[post.practitioner_id]
    assert owner.display_name == "Clinical lead, UCR"
    assert owner.phone_hash is None
    assert owner.email_domain == "example.org"
    basic = world.units.registrations.bundles[0]["entry"][3]["resource"]
    assert basic["author"] == {"reference": f"PractitionerRole/{post.id}"}


async def test_the_reporters_contact_is_not_touched_and_no_email_reaches_the_graph_records() -> (
    None
):
    world = World()

    await world.persist.execute(COMMAND)

    assert world.units.contacts.phones == {APPLICANT_ROLE: "07700 900123"}
    graph_side = repr(
        (
            world.units.audit.entries,
            [message.payload for message in world.units.outbox.messages],
            world.units.people.practitioners,
            world.units.registrations.bundles,
        )
    )
    assert OWNER_EMAIL not in graph_side
    assert "07700" not in graph_side


async def test_the_audit_entry_and_the_event_commit_with_the_bundle() -> None:
    world = World()

    await world.persist.execute(COMMAND)

    assert len(world.units.audit.entries) == 1
    entry = world.units.audit.entries[0]
    assert entry.use_case == "PersistRegistration"
    assert "reg-1" in entry.entity_ids
    assert SERVICE_ID in entry.entity_ids
    events = [m for m in world.units.outbox.messages if m.event_type == "RegistrationPersisted"]
    assert len(events) == 1
    assert events[0].topic == "registration.events"
    assert events[0].payload == RegistrationPersisted("reg-1", SERVICE_ID, NOW).to_payload()
    names = world.units.writes.names
    assert names.index("registrations.write_bundle") < names.index("registrations.save")


async def test_a_second_persist_writes_nothing() -> None:
    world = World()
    await world.persist.execute(COMMAND)
    writes = list(world.units.writes.names)

    second = await world.persist.execute(COMMAND)

    assert second.persisted is False
    assert world.units.writes.names == writes
    assert len(world.units.registrations.bundles) == 1


async def test_an_unknown_registration_is_not_found() -> None:
    world = World()

    with pytest.raises(NotFound):
        await world.persist.execute(PersistRegistrationCommand("reg-unknown"))


@pytest.mark.parametrize(
    "status",
    [RegistrationStatus.INVITED, RegistrationStatus.DRAFT, RegistrationStatus.NEEDS_CHANGES],
)
async def test_a_registration_that_is_not_submitted_is_not_persisted(
    status: RegistrationStatus,
) -> None:
    world = World(status)

    with pytest.raises(InvalidTransition):
        await world.persist.execute(COMMAND)

    assert world.units.writes.names == []


async def test_a_geocoder_that_cannot_answer_leaves_nothing_written() -> None:
    world = World()

    class Down:
        async def find_addresses(self, postcode: str) -> list[AddressCandidate]:
            raise TransientLookupError

    world.persist = PersistRegistration(
        world.units, Down(), world.terminology, world.ids, world.clock
    )

    with pytest.raises(TransientLookupError):
        await world.persist.execute(COMMAND)

    assert world.units.writes.names == []
    assert world.units.commits == 0


async def test_a_failure_in_the_write_commits_nothing() -> None:
    world = World()
    world.units.registrations.fail_write = RuntimeError("the last write failed")

    with pytest.raises(RuntimeError):
        await world.persist.execute(COMMAND)

    assert world.units.commits == 0
    assert world.units.audit.entries == []
    assert world.units.outbox.messages == []


async def test_a_visiting_service_reuses_the_district_location_that_exists() -> None:
    world = World()
    world.units.registrations.held["reg-1"] = replace(
        world.registration(),
        draft=_draft(
            location=LocationStep(fixed_site=False), service=replace(SERVICE, districts="DT3,DT4")
        ),
    )
    world.units.registrations.districts = {"DT3": "loc-existing-dt3"}

    await world.persist.execute(COMMAND)

    bundle = world.units.registrations.bundles[0]
    areas = [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Location"]
    assert [a["name"] for a in areas] == ["DT4"]
    service = next(
        e["resource"]
        for e in bundle["entry"]
        if e["resource"]["resourceType"] == "HealthcareService"
    )
    assert {"reference": "Location/loc-existing-dt3"} in service["coverageArea"]
    lookups = lookups_of(world.registration())
    assert lookups is not None
    assert lookups.address_found is False


# Submit calls persist


def _submit_world() -> World:
    world = World(RegistrationStatus.DRAFT)
    # The reporting contact is in the protected store, not the draft (DEC-243 item 2).
    return world


def _submit(world: World, *, persist: PersistRegistration | None) -> SubmitRegistration:
    return SubmitRegistration(world.units, world.ids, world.clock, persist=persist)


SUBMIT = SubmitRegistrationCommand("submit-1", APPLICANT, "reg-1")


async def test_a_submit_that_succeeds_persists_the_registration_after_it_commits() -> None:
    world = _submit_world()

    result = await _submit(world, persist=world.persist).execute(SUBMIT)

    assert result.status is RegistrationStatus.SUBMITTED
    assert result.errors == ()
    assert len(world.units.registrations.bundles) == 1
    assert world.units.commits == 2  # the submit, then the persist
    assert lookups_of(world.registration()) is not None
    assert world.registration().status is RegistrationStatus.SUBMITTED


async def test_a_submit_with_errors_persists_nothing() -> None:
    world = _submit_world()
    world.units.registrations.held["reg-1"] = replace(
        world.registration(), draft={"organisation": _draft()["organisation"]}
    )

    result = await _submit(world, persist=world.persist).execute(SUBMIT)

    assert result.errors
    assert world.units.registrations.bundles == []


async def test_a_lookup_that_cannot_answer_leaves_the_submit_standing_and_a_retry_heals_it() -> (
    None
):
    world = _submit_world()
    answers = {"down": True}

    class Flaky:
        async def find_addresses(self, postcode: str) -> list[AddressCandidate]:
            if answers["down"]:
                raise TransientLookupError
            return [CANDIDATE]

    persist = PersistRegistration(world.units, Flaky(), world.terminology, world.ids, world.clock)

    first = await _submit(world, persist=persist).execute(SUBMIT)

    assert first.status is RegistrationStatus.SUBMITTED
    assert world.units.registrations.bundles == []
    answers["down"] = False
    again = await _submit(world, persist=persist).execute(SUBMIT)
    assert again.replayed is True
    assert len(world.units.registrations.bundles) == 1


async def test_a_submit_without_a_persist_behaves_as_before() -> None:
    world = _submit_world()

    result = await _submit(world, persist=None).execute(SUBMIT)

    assert result.status is RegistrationStatus.SUBMITTED
    assert world.units.registrations.bundles == []
