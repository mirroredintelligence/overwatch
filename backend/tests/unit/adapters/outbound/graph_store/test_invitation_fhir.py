"""An invitation as a FHIR Task with code invite-reporter (U24): the resource, its refusals, and the
round trip through the pure mapper, which is what the resource store keeps. Sample values only."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fhir.resources.R4B.task import Task

from diucs.adapters.outbound.graph_store.invitation_fhir import (
    INVITE_REPORTER,
    TASK_CODE_SYSTEM,
    invitation_from_fhir,
    invitation_to_fhir,
    is_invitation,
)
from diucs.adapters.outbound.graph_store.mapper import from_graph, to_graph
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.registration import Invitation

CREATED = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
SENT = datetime(2026, 10, 29, 9, 5, 30, tzinfo=UTC)
EXPIRES = datetime(2026, 10, 31, 9, 5, 30, tzinfo=UTC)
INVITATION = Invitation(
    id="inv-1",
    service_id="svc-ucr-west",
    registration_id="reg-1",
    requester_role_id="role-lead-1",
    invitee_id="prac-invitee-1",
    role_label="Duty manager",
    created_at=CREATED,
    sent_at=SENT,
    expires_at=EXPIRES,
)


def test_the_task_has_the_invite_code_the_focus_the_requester_and_the_invitee() -> None:
    resource = invitation_to_fhir(INVITATION)

    assert resource["resourceType"] == "Task"
    assert resource["id"] == "inv-1"
    assert resource["status"] == "requested"
    assert resource["intent"] == "order"
    assert resource["code"] == {"coding": [{"system": TASK_CODE_SYSTEM, "code": INVITE_REPORTER}]}
    assert INVITE_REPORTER == "invite-reporter"
    assert resource["focus"] == {"reference": "HealthcareService/svc-ucr-west"}
    assert resource["requester"] == {"reference": "PractitionerRole/role-lead-1"}
    assert resource["owner"] == {"reference": "Practitioner/prac-invitee-1"}
    assert resource["partOf"] == [{"reference": "Task/reg-1"}]
    assert resource["description"] == "Duty manager"


def test_the_restriction_period_runs_from_the_send_to_forty_eight_hours_later() -> None:
    resource = invitation_to_fhir(INVITATION)

    assert resource["restriction"] == {
        "period": {"start": "2026-10-29T09:05:30Z", "end": "2026-10-31T09:05:30Z"}
    }
    assert resource["authoredOn"] == "2026-10-29T09:00:00Z"
    assert resource["lastModified"] == "2026-10-29T09:05:30Z"


def test_the_resource_is_a_valid_r4b_task() -> None:
    Task.model_validate(invitation_to_fhir(INVITATION))


def test_the_resource_holds_no_token_no_phone_number_and_no_hash() -> None:
    text = repr(invitation_to_fhir(INVITATION))
    assert "token" not in text.lower()
    assert "phone" not in text.lower()
    assert "hash" not in text.lower()


def test_an_invitation_round_trips_through_the_fhir_task() -> None:
    assert invitation_from_fhir(invitation_to_fhir(INVITATION)) == INVITATION


def test_an_invitation_round_trips_through_the_graph_mapper() -> None:
    resource = invitation_to_fhir(INVITATION)

    rebuilt = from_graph(to_graph(resource))

    assert invitation_from_fhir(rebuilt) == INVITATION


def test_the_task_is_recognised_by_its_code() -> None:
    assert is_invitation(invitation_to_fhir(INVITATION))
    other = invitation_to_fhir(INVITATION)
    other["code"] = {"coding": [{"system": TASK_CODE_SYSTEM, "code": "register-service"}]}
    assert not is_invitation(other)
    assert not is_invitation({"resourceType": "Task", "id": "x"})


@pytest.mark.parametrize("element", ["focus", "requester", "owner", "partOf", "restriction"])
def test_a_task_missing_a_required_element_is_refused(element: str) -> None:
    resource: dict[str, Any] = invitation_to_fhir(INVITATION)
    del resource[element]
    with pytest.raises(ValidationFailed):
        invitation_from_fhir(resource)


def test_a_task_that_is_not_an_invitation_is_refused() -> None:
    resource = invitation_to_fhir(INVITATION)
    resource["code"] = {"coding": [{"system": TASK_CODE_SYSTEM, "code": "register-service"}]}
    with pytest.raises(ValidationFailed):
        invitation_from_fhir(resource)


def test_a_reference_to_the_wrong_kind_of_resource_is_refused() -> None:
    resource = invitation_to_fhir(INVITATION)
    resource["owner"] = {"reference": "HealthcareService/svc-ucr-west"}
    with pytest.raises(ValidationFailed):
        invitation_from_fhir(resource)
