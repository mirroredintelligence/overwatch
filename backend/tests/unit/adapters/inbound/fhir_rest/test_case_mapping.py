"""The ServiceRequest of an advisor case, both ways (W7A-A1, A3, A4, A5, A8; R07 and DEC-397).

Pure: no store, no clock, no app. The route tests that go through the graph are in
tests/integration/adapters/inbound/fhir_rest/test_routes_cases_w7a.py.

Decisions under test: a planned case is stored and answered as planned, with `routine` as the FHIR
priority and the urgency extension carrying the real value; a referrer's scores are one complex
extension each; the reference, the open time, the close time and the outcome are answered.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.inbound.fhir_rest.case_mapping import (
    AGE_BAND_EXTENSION,
    CLOSED_AT_EXTENSION,
    DISTRICT_EXTENSION,
    OUTCOME_EXTENSION,
    REFERRER_EXTENSION,
    SCORE_CORRECTIONS_EXTENSION,
    SCORE_EXTENSION,
    SCORE_REASON_EXTENSION,
    URGENCY_EXTENSION,
    CaseDetails,
    case_to_fhir,
    parse_case_details,
)
from diucs.adapters.inbound.fhir_rest.mapping import validate_outbound
from diucs.domain.codes import (
    AgeBand,
    NeedCategory,
    Outcome,
    ReferrerType,
    Urgency,
    code_system_url,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
    ScoreCorrectionReason,
)

OPENED = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
CLOSED = datetime(2026, 10, 29, 9, 55, tzinfo=UTC)
NEED_SYSTEM = code_system_url("need-category")


def open_case(**changes: Any) -> Case:
    fields: dict[str, Any] = {
        "id": "case-1",
        "reference": "4821",
        "referrer_type": ReferrerType.GP,
        "age_band": AgeBand.A80_PLUS,
        "postcode": "DT4",
        "needs": (NeedCategory.FRAILTY,),
        "urgency": Urgency.TODAY,
        "scores": (),
        "opened_at": OPENED,
    }
    fields.update(changes)
    return Case(**fields)


def score_extension(method: str, key: str, value: object) -> dict[str, Any]:
    return {
        "url": SCORE_EXTENSION,
        "extension": [
            {"url": "method", "valueCode": method},
            {"url": "value", key: value},
        ],
    }


def body(**parts: Any) -> dict[str, Any]:
    return {"resourceType": "ServiceRequest", **parts}


# The details a body carries: a part left out is None (unchanged), never an empty value.


def test_an_empty_body_carries_nothing() -> None:
    details = parse_case_details(body())

    assert details == CaseDetails(None, None, None, None, None, None)
    assert details.is_empty


def test_a_chosen_district_is_read_from_its_extension_on_the_patient() -> None:
    details = parse_case_details(
        body(
            contained=[
                {
                    "resourceType": "Patient",
                    "id": "p",
                    "extension": [{"url": DISTRICT_EXTENSION, "valueCode": "BH1"}],
                }
            ]
        )
    )

    assert details.district == "BH1"
    assert details.postcode is None
    assert not details.is_empty


@pytest.mark.parametrize(
    "extension",
    [
        [{"url": DISTRICT_EXTENSION}],
        [{"url": DISTRICT_EXTENSION, "valueCode": ""}],
        [
            {"url": DISTRICT_EXTENSION, "valueCode": "BH1"},
            {"url": DISTRICT_EXTENSION, "valueCode": "DT1"},
        ],
    ],
)
def test_a_district_extension_that_is_empty_or_given_twice_is_refused(
    extension: list[dict[str, Any]],
) -> None:
    with pytest.raises(ValidationFailed):
        parse_case_details(
            body(contained=[{"resourceType": "Patient", "id": "p", "extension": extension}])
        )


def test_a_full_body_carries_every_detail() -> None:
    details = parse_case_details(
        body(
            priority="urgent",
            contained=[
                {
                    "resourceType": "Patient",
                    "id": "p",
                    "address": [{"postalCode": "DT4 8XX"}],
                    "extension": [{"url": AGE_BAND_EXTENSION, "valueCode": "65-79"}],
                }
            ],
            extension=[
                {"url": REFERRER_EXTENSION, "valueCode": "care-home"},
                score_extension("news2", "valueInteger", 5),
            ],
            reasonCode=[{"coding": [{"system": NEED_SYSTEM, "code": "frailty"}]}],
        )
    )

    assert details == CaseDetails(
        referrer_type=ReferrerType.CARE_HOME,
        age_band=AgeBand.A65_79,
        postcode="DT4 8XX",
        needs=(NeedCategory.FRAILTY,),
        urgency=Urgency.WITHIN_2_HRS,
        scores=(News2(5),),
    )
    assert not details.is_empty


@pytest.mark.parametrize(
    ("extension", "message_field"),
    [
        ({"url": REFERRER_EXTENSION, "valueCode": "neighbour"}, "referrer"),
        ({"url": AGE_BAND_EXTENSION, "valueCode": "teens"}, "age"),
    ],
)
def test_a_code_that_is_not_listed_is_a_400_that_does_not_echo_it(
    extension: dict[str, Any], message_field: str
) -> None:
    holder = (
        {"extension": [extension]}
        if extension["url"] == REFERRER_EXTENSION
        else {
            "contained": [{"resourceType": "Patient", "id": "p", "extension": [extension]}],
        }
    )

    with pytest.raises(ValidationFailed) as refused:
        parse_case_details(body(**holder))

    assert str(extension["valueCode"]) not in str(refused.value)
    assert message_field in refused.value.field


# Urgency (DEC-397, decided again in DEC-773): planned is kept as planned.


@pytest.mark.parametrize(
    ("priority", "extension", "urgency"),
    [
        ("urgent", None, Urgency.WITHIN_2_HRS),
        ("routine", None, Urgency.TODAY),
        ("urgent", "within-2-hrs", Urgency.WITHIN_2_HRS),
        ("routine", "today", Urgency.TODAY),
        ("routine", "planned", Urgency.PLANNED),
        (None, "planned", Urgency.PLANNED),
        (None, "within-2-hrs", Urgency.WITHIN_2_HRS),
    ],
)
def test_the_urgency_is_the_extension_or_else_the_priority(
    priority: str | None, extension: str | None, urgency: Urgency
) -> None:
    parts: dict[str, Any] = {}
    if priority is not None:
        parts["priority"] = priority
    if extension is not None:
        parts["extension"] = [{"url": URGENCY_EXTENSION, "valueCode": extension}]

    assert parse_case_details(body(**parts)).urgency is urgency


@pytest.mark.parametrize(
    ("priority", "extension"),
    [("urgent", "planned"), ("routine", "within-2-hrs"), ("asap", None), ("routine", "later")],
)
def test_an_urgency_that_disagrees_with_the_priority_or_is_unknown_is_refused(
    priority: str, extension: str | None
) -> None:
    parts: dict[str, Any] = {"priority": priority}
    if extension is not None:
        parts["extension"] = [{"url": URGENCY_EXTENSION, "valueCode": extension}]

    with pytest.raises(ValidationFailed):
        parse_case_details(body(**parts))


# Scores: one extension per score, the method and the value.


@pytest.mark.parametrize(
    ("extension", "score"),
    [
        (score_extension("news2", "valueInteger", 20), News2(20)),
        (score_extension("cfs", "valueInteger", 6), ClinicalFrailty(6)),
        (score_extension("ambulance-category", "valueInteger", 2), AmbulanceCategory(2)),
        (
            score_extension("manchester", "valueString", "very-urgent"),
            ManchesterTriage("very-urgent"),
        ),
        (score_extension("pathways-dx", "valueString", "DX123"), PathwaysDx("DX123")),
    ],
)
def test_every_kind_of_score_is_read(extension: dict[str, Any], score: object) -> None:
    assert parse_case_details(body(extension=[extension])).scores == (score,)


@pytest.mark.parametrize(
    "extension",
    [
        score_extension("news2", "valueString", "5"),
        score_extension("manchester", "valueInteger", 3),
        score_extension("news2", "valueInteger", 21),
        score_extension("glasgow", "valueInteger", 3),
        {"url": SCORE_EXTENSION, "extension": [{"url": "method", "valueCode": "news2"}]},
        {"url": SCORE_EXTENSION},
    ],
)
def test_a_score_that_is_malformed_is_refused(extension: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed) as refused:
        parse_case_details(body(extension=[extension]))

    assert refused.value.field in ("scores", "news2")
    assert "21" not in str(refused.value)


def test_a_score_given_twice_for_one_method_is_refused() -> None:
    extensions = [
        score_extension("news2", "valueInteger", 3),
        score_extension("news2", "valueInteger", 4),
    ]

    with pytest.raises(ValidationFailed) as refused:
        parse_case_details(body(extension=extensions))

    assert refused.value.field == "scores"


# What the case answers.


def test_an_open_case_answers_its_reference_open_time_and_details() -> None:
    resource = case_to_fhir(open_case(scores=(News2(3), PathwaysDx("DX123"))))

    assert resource["id"] == "case-1"
    assert resource["status"] == "active"
    assert resource["authoredOn"] == "2026-10-29T09:30:00Z"
    assert resource["identifier"][0]["value"] == "4821"
    assert resource["priority"] == "routine"
    assert resource["contained"][0]["address"] == [{"postalCode": "DT4"}]
    extensions = {
        item["url"]: item for item in resource["extension"] if item["url"] != SCORE_EXTENSION
    }
    assert extensions[REFERRER_EXTENSION]["valueCode"] == "gp"
    assert extensions[URGENCY_EXTENSION]["valueCode"] == "today"
    scores = [item for item in resource["extension"] if item["url"] == SCORE_EXTENSION]
    assert [item["extension"] for item in scores] == [
        [{"url": "method", "valueCode": "news2"}, {"url": "value", "valueInteger": 3}],
        [{"url": "method", "valueCode": "pathways-dx"}, {"url": "value", "valueString": "DX123"}],
    ]
    validate_outbound(resource)


def test_a_planned_case_answers_planned_with_a_routine_priority() -> None:
    resource = case_to_fhir(open_case(urgency=Urgency.PLANNED))

    assert resource["priority"] == "routine"
    urgency = [item for item in resource["extension"] if item["url"] == URGENCY_EXTENSION]
    assert urgency == [{"url": URGENCY_EXTENSION, "valueCode": "planned"}]


def test_an_empty_case_answers_no_referrer_and_no_details() -> None:
    resource = case_to_fhir(
        open_case(referrer_type=None, age_band=None, postcode=None, needs=(), urgency=None)
    )

    assert "extension" not in resource
    assert "priority" not in resource
    assert "reasonCode" not in resource
    assert resource["contained"] == [{"resourceType": "Patient", "id": "p"}]
    validate_outbound(resource)


def test_a_closed_case_answers_when_it_closed_and_the_outcome() -> None:
    closed = open_case(scores=(News2(3),)).close(Outcome.DECLINED, CLOSED)

    resource = case_to_fhir(closed)

    assert resource["status"] == "completed"
    extensions = {item["url"]: item for item in resource["extension"]}
    assert extensions[CLOSED_AT_EXTENSION]["valueDateTime"] == "2026-10-29T09:55:00Z"
    assert extensions[OUTCOME_EXTENSION]["valueCode"] == "declined"
    assert "reasonCode" not in resource
    assert "postalCode" not in str(resource)
    validate_outbound(resource)


def test_an_open_case_answers_no_close_time() -> None:
    urls = {item["url"] for item in case_to_fhir(open_case())["extension"]}

    assert CLOSED_AT_EXTENSION not in urls
    assert OUTCOME_EXTENSION not in urls


def test_what_a_case_answers_is_what_an_update_reads_back() -> None:
    case = open_case(urgency=Urgency.PLANNED, scores=(News2(3), ManchesterTriage("urgent")))

    details = parse_case_details(case_to_fhir(case))

    assert details == CaseDetails(
        referrer_type=ReferrerType.GP,
        age_band=AgeBand.A80_PLUS,
        postcode="DT4",
        needs=(NeedCategory.FRAILTY,),
        urgency=Urgency.PLANNED,
        scores=(News2(3), ManchesterTriage("urgent")),
    )


# Q7 (KI-815): the reason for a correction goes in, and the count of corrections comes out.


@pytest.mark.parametrize("reason", list(ScoreCorrectionReason))
def test_the_reason_for_a_correction_is_read_from_its_extension(
    reason: ScoreCorrectionReason,
) -> None:
    details = parse_case_details(
        body(
            extension=[
                score_extension("news2", "valueInteger", 5),
                {"url": SCORE_REASON_EXTENSION, "valueCode": reason.value},
            ]
        )
    )

    assert details.score_correction_reason is reason
    assert details.scores == (News2(5),)


def test_a_reason_alone_is_not_an_empty_body_so_the_use_case_can_refuse_it() -> None:
    details = parse_case_details(
        body(extension=[{"url": SCORE_REASON_EXTENSION, "valueCode": "typing-error"}])
    )

    assert not details.is_empty


def test_a_reason_that_is_not_listed_is_refused_without_echoing_it() -> None:
    with pytest.raises(ValidationFailed) as refused:
        parse_case_details(
            body(extension=[{"url": SCORE_REASON_EXTENSION, "valueCode": "my own words"}])
        )

    assert refused.value.field == "score-correction-reason"
    assert "my own words" not in str(refused.value)


def test_two_reasons_are_refused() -> None:
    with pytest.raises(ValidationFailed):
        parse_case_details(
            body(
                extension=[
                    {"url": SCORE_REASON_EXTENSION, "valueCode": "typing-error"},
                    {"url": SCORE_REASON_EXTENSION, "valueCode": "rescored"},
                ]
            )
        )


def test_a_corrected_case_answers_how_many_times_and_a_case_never_corrected_answers_none() -> None:
    corrected = case_to_fhir(open_case(scores=(News2(5),), score_corrections=2))
    plain = case_to_fhir(open_case(scores=(News2(5),)))

    assert {"url": SCORE_CORRECTIONS_EXTENSION, "valueInteger": 2} in corrected["extension"]
    assert all(item["url"] != SCORE_CORRECTIONS_EXTENSION for item in plain.get("extension", []))
