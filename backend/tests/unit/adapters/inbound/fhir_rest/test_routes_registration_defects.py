"""The R10 defects the front end found (W7B A3): a 24-hour service can be saved, a part-filled step
can be saved as a draft, a call-back needs a role only when someone confirmed it, and the reporter
can choose "Other" as the thing the service counts. Pure: no store is opened."""

from typing import Any

import pytest

from diucs.adapters.inbound.fhir_rest.routes_registration import (
    _issues,
    callback_command,
    parse_draft,
)
from diucs.application.actor import Actor
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    FieldError,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    validate_step,
)
from diucs.domain.codes import Measure, Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.registration import CallBackResult
from tests.support.actors import ACTOR_TENANT

LEAD = Actor(Role.LEAD, "prac-lead", None, "web", frozenset(), tenant_id=ACTOR_TENANT)


def _location(**values: Any) -> dict[str, Any]:
    return {"step": "location", "values": values}


def test_a_24_hour_location_is_read_as_open_24h() -> None:
    step, errors = parse_draft(
        _location(
            fixedSite=True,
            postcode="DT4 8XX",
            address="1 Sample Road, Weymouth",
            siteName="Sample Ward",
            siteType="ward",
            open24h=True,
        )
    )

    assert errors == []
    assert isinstance(step, LocationStep)
    assert step.open_24h is True
    assert validate_step(step) == []


def test_an_issue_on_open_24h_names_the_field_the_page_sends() -> None:
    response = _issues([FieldError("open_24h", "is wrong")])

    assert b'"open24h"' in response.body


def test_the_other_values_keep_their_camel_case_names() -> None:
    step, errors = parse_draft(
        _location(fixedSite=True, openingDays="mon,tue", openingStart="08:00", openingEnd="20:00")
    )

    assert errors == []
    assert isinstance(step, LocationStep)
    assert (step.opening_days, step.opening_start, step.opening_end) == (
        "mon,tue",
        "08:00",
        "20:00",
    )


def test_a_value_the_step_does_not_take_is_still_refused() -> None:
    with pytest.raises(ValidationFailed) as refusal:
        parse_draft(_location(fixedSite=True, tenant="other"))

    assert refusal.value.field == "values"


def test_a_part_filled_step_is_refused_when_it_is_not_a_draft() -> None:
    step, errors = parse_draft({"step": "organisation", "values": {"name": "Sample Team"}})

    assert step is None
    assert [error.field for error in errors] == ["ods_code", "org_type", "contact_name"]


def test_a_part_filled_step_is_built_when_it_is_a_draft() -> None:
    step, errors = parse_draft(
        {"step": "organisation", "values": {"name": "Sample Team"}}, partial=True
    )

    assert errors == []
    assert isinstance(step, OrganisationStep)
    assert step.name == "Sample Team"
    assert step.ods_code == ""
    # What is missing is reported by the step's own checks, so the page can say what is left.
    assert {error.field for error in validate_step(step)} >= {"ods_code", "org_type"}


def test_a_draft_still_needs_the_yes_or_no_answers_the_step_hangs_on() -> None:
    step, errors = parse_draft(
        {"step": "location", "values": {"postcode": "DT4 8XX"}}, partial=True
    )
    assert step is None
    assert [error.field for error in errors] == ["fixed_site"]

    step, errors = parse_draft({"step": "api", "values": {"name": "Feed"}}, partial=True)
    assert step is None
    assert [error.field for error in errors] == ["wanted"]


def test_a_draft_of_the_reporting_step_may_have_no_numbers_yet() -> None:
    step, errors = parse_draft({"step": "reporting", "values": {"measure": "other"}}, partial=True)

    assert errors == []
    assert isinstance(step, ReportingStep)
    assert step.usual_low is None and step.usual_high is None


def test_a_draft_api_step_is_an_api_step() -> None:
    step, _ = parse_draft({"step": "api", "values": {"wanted": False}}, partial=True)
    assert step == ApiStep(wanted=False)


def _parts(**overrides: dict[str, Any]) -> dict[str, Any]:
    parts: dict[str, dict[str, Any]] = {
        "numberCalled": {"valueString": "01305 123456"},
        "spokeToRole": {"valueString": "Duty manager"},
        "result": {"valueCode": "confirmed"},
    }
    parts.update(overrides)
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, **value} for name, value in parts.items()],
    }


def test_a_call_back_with_no_role_is_read_as_no_role() -> None:
    body = _parts(result={"valueCode": "no-answer"})
    del body["parameter"][1]

    command = callback_command(body, LEAD, "key-1", "reg-1")

    assert command.role_spoken_to == ""
    assert command.result is CallBackResult.NO_ANSWER


def test_a_call_back_that_names_a_role_keeps_it() -> None:
    command = callback_command(_parts(), LEAD, "key-1", "reg-1")

    assert command.role_spoken_to == "Duty manager"


def test_other_is_a_measure_the_reporting_step_takes() -> None:
    assert Measure("other") is Measure.OTHER
    step = ReportingStep(
        measure="other",
        usual_low=0,
        usual_high=4,
        cadence="every-2-hrs",
        channel="email",
        holder_name="Duty coordinator",
        contact_email="reports@example.org",
    )

    assert validate_step(step) == []
