"""The pure helpers of the booking Task routes (R09, R17): request bodies, reason codes and the
acknowledgement rule. No Neo4j, no app: the routes' integration tests cover the stored results.

Sample values only: case-1001, ucr-west, ucr-east. No patient data.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from fhir.resources.R4B.task import Task

from diucs.adapters.fhir_shared.booking_task import booking_to_fhir
from diucs.adapters.inbound.fhir_rest.auth import PROJECTIONS
from diucs.adapters.inbound.fhir_rest.routes_bookings import (
    BookingRequestBody,
    acknowledgement_path,
    cancel_reason_of,
    check_acknowledgement_body,
    decision_of,
    decline_reason_of,
    not_reached_reason_of,
    parameters_by_name,
    parse_booking_request,
    withdraw_reason_of,
)
from diucs.application.actor import Actor
from diucs.domain.codes import (
    BookingStatus,
    CancelReason,
    DeclineReason,
    NotReachedReason,
    Role,
    WithdrawReason,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.booking import Booking
from tests.support.actors import ACTOR_TENANT

BOOKING_TASK_CODE: dict[str, Any] = {
    "coding": [{"system": "https://diucs.example/CodeSystem/task-code", "code": "booking-request"}]
}


def _body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "resourceType": "Task",
        "code": BOOKING_TASK_CODE,
        "focus": {"reference": "ServiceRequest/case-1001"},
        "owner": {"reference": "HealthcareService/ucr-west"},
    }
    body.update(changes)
    return body


def _parameters(*parts: dict[str, Any]) -> dict[str, Any]:
    return {"resourceType": "Parameters", "parameter": list(parts)}


def _grouped(*parts: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return parameters_by_name(_parameters(*parts))


def _actor(role: Role, *services: str) -> Actor:
    return Actor(
        role=role,
        practitioner_id="prac-1",
        device_id=None,
        channel="api",
        service_ids=frozenset(services),
        tenant_id=ACTOR_TENANT,
    )


# -- POST /fhir/Task -------------------------------------------------------------------------------


def test_a_booking_request_names_its_case_and_its_service() -> None:
    assert parse_booking_request(_body()) == BookingRequestBody(
        case_id="case-1001", service_id="ucr-west"
    )


@pytest.mark.parametrize("body", [{"resourceType": "Patient"}, [], None])
def test_a_body_that_is_not_a_task_is_refused(body: Any) -> None:
    with pytest.raises(ValidationFailed):
        parse_booking_request(body)


@pytest.mark.parametrize("code", ["reporter-invite", "booking-cancel"])
def test_a_task_of_another_code_is_refused_as_a_booking_request(code: str) -> None:
    body = _body(code={"coding": [{"system": "x", "code": code}]})
    with pytest.raises(ValidationFailed):
        parse_booking_request(body)


def test_a_task_without_a_code_is_refused() -> None:
    body = _body()
    del body["code"]
    with pytest.raises(ValidationFailed):
        parse_booking_request(body)


@pytest.mark.parametrize(
    ("focus", "owner"),
    [
        ({"reference": "Patient/case-1001"}, {"reference": "HealthcareService/ucr-west"}),
        ({"reference": "ServiceRequest/case-1001"}, {"reference": "Practitioner/prac-1"}),
        ({"reference": "ServiceRequest/"}, {"reference": "HealthcareService/ucr-west"}),
        (None, {"reference": "HealthcareService/ucr-west"}),
        ({"reference": "ServiceRequest/case-1001"}, None),
    ],
)
def test_the_focus_and_owner_must_name_the_right_resources(
    focus: dict[str, str] | None, owner: dict[str, str] | None
) -> None:
    body = _body()
    body["focus"] = focus
    body["owner"] = owner
    with pytest.raises(ValidationFailed):
        parse_booking_request(body)


# -- parameters ------------------------------------------------------------------------------------


def test_parameters_are_grouped_by_name_and_a_repeated_name_keeps_every_part() -> None:
    grouped = _grouped(
        {"name": "reason", "valueCode": "full"}, {"name": "reason", "valueCode": "other"}
    )
    assert [part["valueCode"] for part in grouped["reason"]] == ["full", "other"]


def test_a_body_that_is_not_a_parameters_resource_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        parameters_by_name({"resourceType": "Task"})


# -- $respond --------------------------------------------------------------------------------------


@pytest.mark.parametrize("decision", ["confirm", "decline"])
def test_respond_takes_confirm_or_decline(decision: str) -> None:
    assert decision_of(_grouped({"name": "decision", "valueCode": decision})) == decision


@pytest.mark.parametrize("decision", ["maybe", "accept", ""])
def test_respond_refuses_any_other_decision(decision: str) -> None:
    with pytest.raises(ValidationFailed):
        decision_of(_grouped({"name": "decision", "valueCode": decision}))


def test_respond_needs_a_decision() -> None:
    with pytest.raises(ValidationFailed):
        decision_of(_grouped({"name": "reason", "valueCode": "full"}))


def test_a_decline_reason_is_optional_and_must_be_a_decline_reason() -> None:
    assert decline_reason_of(_grouped({"name": "decision", "valueCode": "decline"})) is None
    reason = decline_reason_of(_grouped({"name": "reason", "valueCode": "staffing-or-transport"}))
    assert reason is DeclineReason.STAFFING_OR_TRANSPORT
    with pytest.raises(ValidationFailed):
        decline_reason_of(_grouped({"name": "reason", "valueCode": "now-full"}))


# -- $cancel, $withdraw, $not-reached --------------------------------------------------------------


def test_cancel_needs_a_cancel_reason() -> None:
    assert cancel_reason_of(_grouped({"name": "reason", "valueCode": "caller-declined"})) is (
        CancelReason.CALLER_DECLINED
    )
    with pytest.raises(ValidationFailed):
        cancel_reason_of(_grouped())
    with pytest.raises(ValidationFailed):
        cancel_reason_of(_grouped({"name": "reason", "valueCode": "staffing"}))


def test_withdraw_needs_a_withdraw_reason_and_refuses_a_decline_reason() -> None:
    assert withdraw_reason_of(_grouped({"name": "reason", "valueCode": "staffing"})) is (
        WithdrawReason.STAFFING
    )
    with pytest.raises(ValidationFailed):
        withdraw_reason_of(_grouped({"name": "reason", "valueCode": "full"}))
    with pytest.raises(ValidationFailed):
        withdraw_reason_of(_grouped())


def test_not_reached_needs_a_not_reached_reason() -> None:
    assert not_reached_reason_of(_grouped({"name": "reason", "valueCode": "no-answer"})) is (
        NotReachedReason.NO_ANSWER
    )
    with pytest.raises(ValidationFailed):
        not_reached_reason_of(_grouped({"name": "reason", "valueCode": "now-full"}))


# -- $acknowledge (R17) ----------------------------------------------------------------------------


def test_an_acknowledgement_takes_no_body_or_an_empty_parameters_resource() -> None:
    check_acknowledgement_body(None)
    check_acknowledgement_body({"resourceType": "Parameters"})
    check_acknowledgement_body(_parameters())


def test_an_acknowledgement_refuses_an_empty_object_that_is_not_a_parameters_resource() -> None:
    with pytest.raises(ValidationFailed):
        check_acknowledgement_body({})


def test_an_acknowledgement_refuses_a_parameter_it_does_not_take() -> None:
    with pytest.raises(ValidationFailed):
        check_acknowledgement_body(_parameters({"name": "reason", "valueCode": "other"}))
    with pytest.raises(ValidationFailed):
        check_acknowledgement_body({"resourceType": "Task"})


def test_only_a_withdrawn_or_not_reached_booking_can_be_acknowledged() -> None:
    assert acknowledgement_path(BookingStatus.WITHDRAWN) == "withdrawn"
    assert acknowledgement_path(BookingStatus.NOT_REACHED) == "not-reached"
    for status in BookingStatus:
        if status not in (BookingStatus.WITHDRAWN, BookingStatus.NOT_REACHED):
            assert acknowledgement_path(status) is None, status


# -- the reporter's view of a booking Task (R02 projection, used by R09) --------------------------


def _booking() -> Booking:
    return Booking(
        id="bk-4821",
        reference="4821",
        service_id="ucr-west",
        case_id="case-1001",
        requester_id="advisor-1",
        status=BookingStatus.REQUESTED,
        requested_at=_at(14, 16),
        reply_by=_at(14, 26),
    )


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 29, hour, minute, tzinfo=UTC)


def test_a_reporter_of_the_owning_service_sees_no_focus_and_no_for() -> None:
    task = Task.model_validate(booking_to_fhir(_booking()))
    seen = PROJECTIONS.project(task, _actor(Role.REPORTER, "ucr-west"))
    assert seen.focus is None
    assert seen.for_fhir is None
    assert [tag.code for tag in seen.meta.security] == ["REDACTED"]


def test_an_advisor_sees_the_focus_of_a_booking_and_no_label() -> None:
    task = Task.model_validate(booking_to_fhir(_booking()))
    seen = PROJECTIONS.project(task, _actor(Role.ADVISOR))
    assert seen.focus is not None
    assert seen.focus.reference == "ServiceRequest/case-1001"
    assert seen.meta is None or not seen.meta.security
