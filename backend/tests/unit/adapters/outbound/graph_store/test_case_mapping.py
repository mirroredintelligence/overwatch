"""Pure tests for the case mapping between Case and its FHIR resources (P21).

No Neo4j: these run without Docker. Values are synthetic. The sample postcode is the one the specs
use (district DT4); no name, NHS number or free text appears anywhere in this file.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.case_repository import case_from_fhir, case_to_fhir
from diucs.domain.codes import AgeBand, NeedCategory, Outcome, ReferrerType, Urgency
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import ClinicalFrailty, ManchesterTriage, News2, PathwaysDx

OPENED = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)
CLOSED = datetime(2026, 10, 25, 13, 40, tzinfo=UTC)

OPEN_CASE = Case(
    id="case-1",
    reference="4821",
    referrer_type=ReferrerType.AMBULANCE_CREW,
    age_band=AgeBand.A80_PLUS,
    postcode="DT4",
    needs=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
    urgency=Urgency.WITHIN_2_HRS,
    scores=(News2(2), ClinicalFrailty(6)),
    opened_at=OPENED,
)

SCORED_CASE = Case(
    id="case-2",
    reference="4822",
    referrer_type=ReferrerType.GP,
    age_band=AgeBand.A65_79,
    postcode="DT4",
    needs=(NeedCategory.WOUND_CARE,),
    urgency=Urgency.TODAY,
    scores=(ManchesterTriage("urgent"), PathwaysDx("PD12")),
    opened_at=OPENED,
)


def test_an_open_case_is_urgent_with_one_reason_code_per_need() -> None:
    _, request, _ = case_to_fhir(OPEN_CASE)

    assert request["priority"] == "urgent"
    assert request["status"] == "active"
    assert request["intent"] == "plan"
    codes = [entry["coding"][0]["code"] for entry in request["reasonCode"]]
    assert codes == ["fall-no-injury", "frailty"]


def test_the_patient_stub_holds_the_postcode_and_no_identity_element() -> None:
    patient, _, _ = case_to_fhir(OPEN_CASE)

    assert patient["id"] == "pt-case-1"
    assert patient["active"] is True
    assert patient["address"] == [{"postalCode": "DT4"}]
    assert patient["meta"]["tag"][0]["code"] == "pseudonymised-case-stub"
    assert patient["meta"]["security"][0]["code"] == "R"


@pytest.mark.parametrize("element", ["name", "identifier", "birthDate", "telecom"])
def test_a_patient_stub_carrying_an_identity_element_is_refused(element: str) -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    patient[element] = [{"text": "sample"}]

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


@pytest.mark.parametrize(
    ("urgency", "priority"),
    [(Urgency.WITHIN_2_HRS, "urgent"), (Urgency.TODAY, "routine"), (Urgency.PLANNED, "routine")],
)
def test_priority_follows_urgency(urgency: Urgency, priority: str) -> None:
    _, request, _ = case_to_fhir(replace(OPEN_CASE, urgency=urgency))

    assert request["priority"] == priority


@pytest.mark.parametrize("case", [OPEN_CASE, SCORED_CASE])
def test_a_case_round_trips_through_its_fhir_resources(case: Case) -> None:
    assert case_from_fhir(*case_to_fhir(case)) == case


def test_a_closed_case_has_no_postcode_and_no_reason_codes_but_keeps_outcome_and_scores() -> None:
    closed = OPEN_CASE.close(
        Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id="svc-ucr-west"
    )
    patient, request, scores = case_to_fhir(closed)

    assert "address" not in patient
    assert "reasonCode" not in request
    assert request["status"] == "completed"
    assert request["performer"] == [{"reference": "HealthcareService/svc-ucr-west"}]
    assert len(scores) == 2
    assert case_from_fhir(patient, request, scores) == closed


def test_scores_are_observations_with_their_acuity_code_and_recorded_value() -> None:
    _, _, open_scores = case_to_fhir(OPEN_CASE)
    _, _, scored = case_to_fhir(SCORED_CASE)

    assert [score["id"] for score in scored] == ["sc-case-2-1", "sc-case-2-2"]
    for score in scored:
        assert score["status"] == "final"
        assert score["subject"] == {"reference": "Patient/pt-case-2"}
    assert scored[0]["code"]["coding"][0]["code"] == "manchester"
    assert scored[0]["valueCodeableConcept"]["coding"][0]["code"] == "urgent"
    assert scored[1]["code"]["coding"][0]["code"] == "pathways-dx"
    assert scored[1]["valueCodeableConcept"]["coding"][0]["code"] == "PD12"
    assert open_scores[0]["valueInteger"] == 2
    assert open_scores[1]["valueInteger"] == 6


def test_an_observation_whose_code_is_not_an_acuity_method_is_refused() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    scores[0]["code"] = {
        "coding": [{"system": "https://diucs.example/CodeSystem/other", "code": "x"}]
    }

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_score_is_never_recorded_with_a_value_that_is_out_of_range() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    scores[0]["valueInteger"] = 21

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_the_reference_is_the_case_identifier_value() -> None:
    _, request, _ = case_to_fhir(OPEN_CASE)
    identifiers: list[dict[str, Any]] = request["identifier"]

    assert identifiers == [{"system": "https://diucs.example/case-reference", "value": "4821"}]


def test_a_stub_for_another_case_is_refused() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    patient["id"] = "pt-case-9"

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_request_with_two_case_references_is_refused() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    request["identifier"].append({"system": "https://diucs.example/case-reference", "value": "9"})

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_stub_with_two_postcodes_is_refused() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    patient["address"].append({"postalCode": "DT4"})

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_destination_that_is_not_a_service_is_refused() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    request["performer"] = [{"reference": "Practitioner/prac-advisor-1"}]

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_closed_time_without_a_zone_is_refused() -> None:
    closed = OPEN_CASE.close(Outcome.DECLINED, CLOSED)
    patient, request, scores = case_to_fhir(closed)
    closed_at = next(e for e in request["extension"] if e["url"].endswith("/closedAt"))
    closed_at["valueDateTime"] = "2026-10-25T13:40:00"

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_manchester_score_coded_in_another_system_is_refused() -> None:
    patient, request, scores = case_to_fhir(SCORED_CASE)
    scores[0]["valueCodeableConcept"]["coding"][0]["system"] = "https://diucs.example/other"

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


OUTCOME_URL = "https://diucs.example/StructureDefinition/outcome"


def test_a_full_postcode_is_refused_and_the_value_is_not_echoed() -> None:
    with pytest.raises(ValidationFailed) as error:
        case_to_fhir(replace(OPEN_CASE, postcode="DT4 8XX"))

    assert "8XX" not in str(error.value)


@pytest.mark.parametrize("postcode", ["DT4 8", "1234", "dt4"])
def test_a_postcode_that_is_not_a_district_is_refused(postcode: str) -> None:
    with pytest.raises(ValidationFailed):
        case_to_fhir(replace(OPEN_CASE, postcode=postcode))


@pytest.mark.parametrize("reference", ["0482", "48210", "4821A", "943 476 5919", "9434765919"])
def test_a_reference_outside_the_four_digit_format_is_refused(reference: str) -> None:
    with pytest.raises(ValidationFailed):
        case_to_fhir(replace(OPEN_CASE, reference=reference))


@pytest.mark.parametrize("which", ["patient", "request", "score"])
def test_an_element_the_mapping_cannot_represent_is_refused_not_dropped(which: str) -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    target = {"patient": patient, "request": request, "score": scores[0]}[which]
    target["unrepresented"] = {"text": "sample"}

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


@pytest.mark.parametrize(
    ("urgency", "wrong_priority"),
    [(Urgency.WITHIN_2_HRS, "routine"), (Urgency.TODAY, "urgent"), (Urgency.PLANNED, "urgent")],
)
def test_a_priority_that_does_not_match_the_urgency_is_refused(
    urgency: Urgency, wrong_priority: str
) -> None:
    patient, request, scores = case_to_fhir(replace(OPEN_CASE, urgency=urgency))
    request["priority"] = wrong_priority

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_priority_without_an_urgency_is_refused() -> None:
    patient, request, scores = case_to_fhir(replace(OPEN_CASE, urgency=None))
    request["priority"] = "urgent"

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_an_open_case_whose_status_is_completed_is_refused() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    request["status"] = "completed"

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_closed_case_whose_status_is_active_is_refused() -> None:
    closed = OPEN_CASE.close(Outcome.DECLINED, CLOSED)
    patient, request, scores = case_to_fhir(closed)
    request["status"] = "active"

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_an_outcome_without_a_close_time_is_refused() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    request["extension"].append({"url": OUTCOME_URL, "valueString": "declined"})

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_need_coded_in_another_system_is_refused() -> None:
    patient, request, scores = case_to_fhir(OPEN_CASE)
    request["reasonCode"][0]["coding"][0]["system"] = "https://diucs.example/CodeSystem/other"

    with pytest.raises(ValidationFailed):
        case_from_fhir(patient, request, scores)


def test_a_case_with_no_scores_has_no_supporting_info_element() -> None:
    # The resource store refuses an empty list, so the element is left out, not written empty.
    unscored = replace(OPEN_CASE, scores=())

    patient, request, scores = case_to_fhir(unscored)

    assert "supportingInfo" not in request
    assert scores == []
    assert case_from_fhir(patient, request, scores) == unscored


def test_a_case_with_scores_lists_one_supporting_reference_per_score_in_order() -> None:
    _, request, scores = case_to_fhir(OPEN_CASE)

    assert request["supportingInfo"] == [
        {"reference": "Observation/sc-case-1-1"},
        {"reference": "Observation/sc-case-1-2"},
    ]
    assert [resource["id"] for resource in scores] == ["sc-case-1-1", "sc-case-1-2"]
