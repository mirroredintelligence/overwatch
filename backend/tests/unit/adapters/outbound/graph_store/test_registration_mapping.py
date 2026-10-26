"""Pure mapping for registrations: Task code register-service, the draft rows and the checks (P13).

The registration round trip goes through the FHIR Task and the draft rows, as the repository
stores them. Draft values are kept as typed values (DEC-001: no JSON, no maps on a node). Sample
values are synthetic; the organisation is the sample from the prompt.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.registration_repository import (
    draft_from_rows,
    draft_to_rows,
    registration_from_fhir,
    registration_to_fhir,
)
from diucs.domain.codes import BASE_URL, RegistrationStatus, ScopeFlag, code_system_url
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.registration import Registration
from diucs.domain.rules.registration import ApprovalChecks

CREATED = datetime(2026, 10, 25, 12, 50, tzinfo=UTC)
CHANGED = datetime(2026, 10, 25, 13, 5, 30, tzinfo=UTC)
DRAFT = {"organisation": {"name": "Dorset HealthCare", "ods": "RDY"}}

APPLICANT_DRAFT = Registration(
    id="reg-ucr-east-1",
    service_id="svc-ucr-east",
    status=RegistrationStatus.DRAFT,
    requester_role_id="role-applicant-1",
    owner_role_id=None,
    created_at=CREATED,
    last_modified=CREATED,
    draft=DRAFT,
    checks=ApprovalChecks(True, False, None, False),
)


def _round_trip(registration: Registration) -> Registration:
    resource = registration_to_fhir(registration)
    rows = draft_to_rows(registration.draft)
    return registration_from_fhir(resource, draft_from_rows(rows))


def test_a_registration_with_a_draft_and_checks_round_trips_through_fhir() -> None:
    assert _round_trip(APPLICANT_DRAFT) == APPLICANT_DRAFT


@pytest.mark.parametrize(
    ("status", "task_status"),
    [
        (RegistrationStatus.INVITED, "draft"),
        (RegistrationStatus.DRAFT, "draft"),
        (RegistrationStatus.SUBMITTED, "requested"),
        (RegistrationStatus.IN_REVIEW, "requested"),
        (RegistrationStatus.NEEDS_CHANGES, "requested"),
        (RegistrationStatus.APPROVED, "accepted"),
        (RegistrationStatus.LIVE, "in-progress"),
        (RegistrationStatus.REVERIFY, "in-progress"),
        (RegistrationStatus.PAUSED, "on-hold"),
        (RegistrationStatus.NOT_APPROVED, "rejected"),
    ],
)
def test_the_task_status_follows_the_registration_state(
    status: RegistrationStatus, task_status: str
) -> None:
    registration = Registration(
        id="reg-1",
        service_id="svc-ucr-east",
        status=status,
        requester_role_id=None,
        owner_role_id=None,
        created_at=CREATED,
        last_modified=CREATED,
    )
    resource = registration_to_fhir(registration)
    assert resource["status"] == task_status
    assert resource["businessStatus"]["coding"][0]["code"] == status.value
    assert resource["businessStatus"]["coding"][0]["system"] == code_system_url(
        "registration-status"
    )


def test_the_task_is_coded_register_service() -> None:
    resource = registration_to_fhir(APPLICANT_DRAFT)
    assert resource["resourceType"] == "Task"
    assert resource["code"] == {
        "coding": [{"system": code_system_url("task-code"), "code": "register-service"}]
    }


def test_the_four_checks_are_extensions_and_the_scope_is_left_out_until_decided() -> None:
    resource = registration_to_fhir(APPLICANT_DRAFT)
    extensions = {item["url"]: item for item in resource["extension"]}
    assert extensions[f"{BASE_URL}StructureDefinition/checkAutomatic"] == {
        "url": f"{BASE_URL}StructureDefinition/checkAutomatic",
        "valueBoolean": True,
    }
    assert f"{BASE_URL}StructureDefinition/checkScope" not in extensions


def test_a_decided_scope_is_kept_as_its_flag() -> None:
    decided = replace(APPLICANT_DRAFT, checks=ApprovalChecks(True, True, ScopeFlag.IN_PILOT, True))
    assert _round_trip(decided) == decided


def test_a_note_is_kept_as_the_task_description() -> None:
    noted = replace(APPLICANT_DRAFT, note="Call-back booked for Monday")
    assert registration_to_fhir(noted)["description"] == "Call-back booked for Monday"
    assert _round_trip(noted) == noted


def test_a_submission_time_is_the_execution_period_start() -> None:
    submitted = replace(APPLICANT_DRAFT, status=RegistrationStatus.SUBMITTED, submitted_at=CHANGED)
    resource = registration_to_fhir(submitted)
    assert resource["executionPeriod"] == {"start": "2026-10-25T13:05:30Z"}
    assert _round_trip(submitted) == submitted


def test_draft_rows_keep_the_type_of_each_value() -> None:
    draft: dict[str, dict[str, Any]] = {"reporting": {"n": 3, "flag": True, "text": "x"}}
    restored = draft_from_rows(draft_to_rows(draft))
    assert restored == draft
    assert type(restored["reporting"]["n"]) is int
    assert type(restored["reporting"]["flag"]) is bool


def test_an_empty_draft_has_no_rows_and_reads_back_empty() -> None:
    assert draft_to_rows({}) == []
    assert draft_from_rows([]) == {}


def test_two_rows_for_one_step_and_field_are_refused() -> None:
    # Fail closed: a second value for one field would make the draft ambiguous.
    rows = [
        {"step": "organisation", "field": "ods", "value": "RDY"},
        {"step": "organisation", "field": "ods", "value": "RDX"},
    ]
    with pytest.raises(ValidationFailed):
        draft_from_rows(rows)


def _task_literal() -> dict[str, Any]:
    """A registration Task written out by hand, so a guard test does not depend on the mapper."""
    return {
        "resourceType": "Task",
        "id": "reg-ucr-east-1",
        "status": "requested",
        "businessStatus": {
            "coding": [{"system": code_system_url("registration-status"), "code": "submitted"}]
        },
        "code": {"coding": [{"system": code_system_url("task-code"), "code": "register-service"}]},
        "intent": "order",
        "authoredOn": "2026-10-25T12:50:00Z",
        "lastModified": "2026-10-25T12:50:00Z",
        "focus": {"reference": "HealthcareService/svc-ucr-east"},
        "extension": [],
    }


def test_a_task_with_another_code_is_not_read_as_a_registration() -> None:
    resource = _task_literal()
    resource["code"] = {"coding": [{"system": code_system_url("task-code"), "code": "book"}]}
    with pytest.raises(ValidationFailed):
        registration_from_fhir(resource, {})


def test_a_booking_status_is_not_a_registration_status() -> None:
    # The booking code system and the registration code system never mix (lesson L3).
    resource = _task_literal()
    resource["businessStatus"] = {
        "coding": [{"system": code_system_url("booking-business-status"), "code": "requested"}]
    }
    with pytest.raises(ValidationFailed):
        registration_from_fhir(resource, {})


def test_the_extension_base_url_is_the_one_in_the_registry() -> None:
    urls = {item["url"] for item in registration_to_fhir(APPLICANT_DRAFT)["extension"]}
    assert all(url.startswith(f"{BASE_URL}StructureDefinition/check") for url in urls)
