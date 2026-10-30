"""The use-case side of the R10 defects (W7B A3): a draft saves what is there, a call-back needs a
role only when it was confirmed, and "Other" counts places. Recording stand-ins, no store."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.registration_draft import (
    OrganisationStep,
    ReportingStep,
    SaveRegistrationStep,
    SaveRegistrationStepCommand,
    ServiceStep,
)
from diucs.application.use_cases.registration_submit import UNIT_LABELS
from diucs.application.use_cases.review_registration import _role_spoken_to
from diucs.domain.codes import Measure, PractitionerRoleCode, RegistrationStatus, Role, ScopeFlag
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.registration import CallBackResult, Registration, ScopeEntry
from tests.support.actors import ACTOR_TENANT
from tests.support.registration_rig import StubUnits

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
SERVICE_ID = "svc-ucr-west"
ROLE_ID = "role-applicant"
APPLICANT = Actor(
    Role.REPORTER, "prac-applicant", "device-1", "api", frozenset(), tenant_id=ACTOR_TENANT
)


@pytest.fixture(autouse=True)
def _bound_tenant() -> Iterator[None]:
    with bind_tenant(ACTOR_TENANT):
        yield


def _world() -> StubUnits:
    units = StubUnits()
    units.registrations.held["reg-1"] = Registration(
        id="reg-1",
        service_id=SERVICE_ID,
        status=RegistrationStatus.INVITED,
        requester_role_id=ROLE_ID,
        owner_role_id=None,
        created_at=NOW,
        last_modified=NOW,
    )
    units.people.roles[ROLE_ID] = PractitionerRole(
        id=ROLE_ID,
        practitioner_id="prac-applicant",
        service_id=SERVICE_ID,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=None,
        period_start=NOW,
    )
    from datetime import date

    units.scope.entries_by_service[SERVICE_ID] = ScopeEntry(
        SERVICE_ID, "UCR West", _category(), ScopeFlag.IN_PILOT, date(2026, 10, 1)
    )
    return units


def _category() -> Any:
    from diucs.domain.codes import ServiceCategory

    return ServiceCategory.URGENT_COMMUNITY_RESPONSE


def _save(units: StubUnits, step: Any, *, partial: bool = False) -> Any:
    use_case = SaveRegistrationStep(units, SequentialIds("id"), FixedClock(NOW))
    return use_case.execute(
        SaveRegistrationStepCommand(
            idempotency_key=f"key-{len(units.idempotency.stored)}",
            actor=APPLICANT,
            registration_id="reg-1",
            step=step,
            partial=partial,
        )
    )


async def test_a_draft_of_a_part_filled_step_is_saved_and_says_what_is_left() -> None:
    units = _world()
    step = OrganisationStep(name="Sample Team", ods_code="", org_type="", contact_name="")

    result = await _save(units, step, partial=True)

    assert result.status is RegistrationStatus.DRAFT
    assert {error.field for error in result.errors} >= {"ods_code", "org_type", "contact_name"}
    saved = units.registrations.held["reg-1"]
    assert saved.draft["organisation"] == {
        "name": "Sample Team",
        "ods_code": "",
        "org_type": "",
        "contact_name": "",
        "contact_email": "",
        "contact_phone": "",
    }


async def test_a_draft_of_the_service_step_takes_the_name_from_the_invitation() -> None:
    units = _world()
    step = ServiceStep(
        service_name="",
        category="",
        referral_methods="",
        spoa_phone="",
        accepting_days="",
        accepting_start="",
        accepting_end="",
        needs="",
        age_min=None,
    )

    result = await _save(units, step, partial=True)

    assert result.errors
    assert units.registrations.held["reg-1"].draft["service"]["service_name"] == "UCR West"


async def test_a_service_step_that_is_not_a_draft_still_needs_the_invitations_name() -> None:
    units = _world()
    step = ServiceStep(
        service_name="Another name",
        category="",
        referral_methods="",
        spoa_phone="",
        accepting_days="",
        accepting_start="",
        accepting_end="",
        needs="",
        age_min=None,
    )

    with pytest.raises(ValidationFailed):
        await _save(units, step)


async def test_a_draft_of_the_reporting_step_keeps_a_good_mobile_and_drops_a_bad_one() -> None:
    units = _world()
    good = ReportingStep(
        measure="",
        usual_low=None,
        usual_high=None,
        cadence="",
        channel="text",
        contact_mobile="07700 900123",
    )
    await _save(units, good, partial=True)
    assert units.contacts.phones[ROLE_ID] == "07700 900123"

    bad = replace(good, contact_mobile="0770")
    await _save(units, bad, partial=True)
    assert units.contacts.phones[ROLE_ID] == "07700 900123"
    assert "contact_mobile" not in units.registrations.held["reg-1"].draft["reporting"]


def test_the_role_spoken_to_is_needed_only_when_the_call_was_confirmed() -> None:
    with pytest.raises(ValidationFailed):
        _role_spoken_to(CallBackResult.CONFIRMED, "")
    assert _role_spoken_to(CallBackResult.NOT_CONFIRMED, "") == ""
    assert _role_spoken_to(CallBackResult.NO_ANSWER, "") == ""
    assert _role_spoken_to(CallBackResult.NOT_CONFIRMED, " Duty  manager ") == "Duty manager"


def test_other_counts_places() -> None:
    assert UNIT_LABELS[Measure.OTHER] == "places"
