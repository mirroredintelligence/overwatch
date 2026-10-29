"""Pure tests of the service and report-request mappers of the FHIR API (R04). No Docker, no HTTP.

service_to_fhir turns a ServiceProfile into a valid R4B HealthcareService. search_bundle wraps
resources in a searchset Bundle. report_request_from_fhir turns the body of POST /fhir/Observation
into a ReportCapacityCommand, or refuses it with a ValidationFailed whose field is the FHIR element
and whose message is fixed plain words (never the value sent). validate_outbound refuses a resource
that is not valid R4B. Synthetic values only: no patient data.
"""

import copy
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.healthcareservice import HealthcareService

from diucs.adapters.inbound.fhir_rest.mapping import (
    API_SOURCES,
    ReportRequest,
    report_request_from_fhir,
    search_bundle,
    service_to_fhir,
    ucum_unit,
    validate_outbound,
)
from diucs.application.actor import Actor
from diucs.domain.codes import (
    BASE_URL,
    Cadence,
    Channel,
    Measure,
    ReportSource,
    Role,
    ServiceCategory,
    code_system_url,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.service import AvailableTime, ServiceProfile

KEY = "key-1"
REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-reporter-west",
    device_id=None,
    channel="api",
    service_ids=frozenset({"svc-ucr-west"}),
)
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead-1",
    device_id=None,
    channel="api",
    service_ids=frozenset(),
)
MEASURE_SYSTEM = code_system_url("capacity-measure")
SOURCE_SYSTEM = code_system_url("report-source")
CATEGORY_SYSTEM = code_system_url("service-category")

WEST = ServiceProfile(
    id="svc-ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


def _resource() -> dict[str, Any]:
    return {
        "resourceType": "Observation",
        "status": "final",
        "code": {
            "coding": [{"system": MEASURE_SYSTEM, "code": "referrals-acceptable"}],
        },
        "focus": [{"reference": "HealthcareService/svc-ucr-west"}],
        "valueQuantity": {
            "value": 4,
            "unit": "referrals",
            "system": "http://unitsofmeasure.org",
            "code": "{referral}",
        },
        "method": {"coding": [{"system": SOURCE_SYSTEM, "code": "app"}]},
        "effectiveDateTime": "2026-10-23T10:00:00Z",
    }


def _without(*path: str) -> dict[str, Any]:
    resource = _resource()
    target: Any = resource
    for name in path[:-1]:
        target = target[name]
    del target[path[-1]]
    return resource


def _with(value: Any, *path: str) -> dict[str, Any]:
    resource = _resource()
    target: Any = resource
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    return resource


def _extensions(resource: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in resource["extension"]:
        name = item["url"].rsplit("/", 1)[-1]
        assert item["url"] == f"{BASE_URL}StructureDefinition/{name}"
        (value,) = (v for k, v in item.items() if k != "url")
        result[name] = value
    return result


# service_to_fhir


def test_a_service_is_a_valid_r4b_healthcare_service() -> None:
    resource = service_to_fhir(WEST)

    HealthcareService.model_validate(resource)
    assert resource["resourceType"] == "HealthcareService"
    assert resource["id"] == "svc-ucr-west"
    assert resource["name"] == "UCR West"
    assert resource["active"] is True


def test_the_category_is_a_list_of_one_concept_from_the_service_category_system() -> None:
    resource = service_to_fhir(WEST)

    assert resource["category"] == [
        {
            "coding": [
                {
                    "system": CATEGORY_SYSTEM,
                    "code": "urgent-community-response",
                    "display": resource["category"][0]["coding"][0]["display"],
                }
            ]
        }
    ]
    assert resource["category"][0]["coding"][0]["display"]


def test_the_profile_values_are_extensions_with_their_registered_urls() -> None:
    assert _extensions(service_to_fhir(WEST)) == {
        "establishedCapacity": 8,
        "canExceedEstablished": False,
        "usualRangeMin": 0,
        "usualRangeMax": 8,
        "reportCadence": "every-2-hrs",
        "limitedLevelPercent": 80,
        "measure": "referrals-acceptable",
        "unitLabel": "referrals",
        "channel": "text",
    }


def test_a_timed_window_has_day_codes_and_times_and_an_all_day_window_has_no_times() -> None:
    timed = service_to_fhir(WEST)["availableTime"]
    all_day = service_to_fhir(_all_day_profile())["availableTime"]

    assert timed == [
        {
            "daysOfWeek": ["mon", "tue", "wed", "thu", "fri"],
            "allDay": False,
            "availableStartTime": "08:00:00",
            "availableEndTime": "20:00:00",
        }
    ]
    assert all_day == [
        {"daysOfWeek": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "allDay": True}
    ]


def _all_day_profile() -> ServiceProfile:
    return ServiceProfile(
        id="svc-ward-a",
        name="Ward A",
        category=ServiceCategory.INPATIENT_BEDS,
        measure=Measure.FREE_BEDS,
        unit_label="beds",
        established_capacity=20,
        can_exceed_established=False,
        usual_range=(0, 20),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day_all_day(),),
        channel=Channel.TEXT,
    )


def test_a_comment_is_carried_only_when_there_is_one_and_an_inactive_service_says_so() -> None:
    plain = service_to_fhir(WEST)
    profile = _all_day_profile()
    commented = service_to_fhir(
        ServiceProfile(
            id=profile.id,
            name=profile.name,
            category=profile.category,
            measure=profile.measure,
            unit_label=profile.unit_label,
            established_capacity=profile.established_capacity,
            can_exceed_established=profile.can_exceed_established,
            usual_range=profile.usual_range,
            cadence=profile.cadence,
            available_times=profile.available_times,
            channel=profile.channel,
            active=False,
            comment="Back at 16:00",
        )
    )

    assert "comment" not in plain
    assert commented["comment"] == "Back at 16:00"
    assert commented["active"] is False
    HealthcareService.model_validate(commented)


# search_bundle


def test_a_search_bundle_lists_the_resources_as_matches_with_a_total() -> None:
    first = service_to_fhir(WEST)
    second = service_to_fhir(_all_day_profile())

    bundle = search_bundle(
        [first, second],
        total=5,
        self_url="/fhir/HealthcareService?_count=2",
        next_url="/fhir/HealthcareService?_count=2&_offset=2",
    )

    Bundle.model_validate(bundle)
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "searchset"
    assert bundle["total"] == 5
    assert bundle["entry"] == [
        {"resource": first, "search": {"mode": "match"}},
        {"resource": second, "search": {"mode": "match"}},
    ]
    assert bundle["link"] == [
        {"relation": "self", "url": "/fhir/HealthcareService?_count=2"},
        {"relation": "next", "url": "/fhir/HealthcareService?_count=2&_offset=2"},
    ]


def test_an_empty_search_bundle_has_no_entry_and_no_next_link() -> None:
    bundle = search_bundle([], total=0, self_url="/fhir/Observation?focus=HealthcareService/x")

    Bundle.model_validate(bundle)
    assert "entry" not in bundle
    assert bundle["total"] == 0
    assert bundle["link"] == [
        {"relation": "self", "url": "/fhir/Observation?focus=HealthcareService/x"}
    ]


# ucum_unit


@pytest.mark.parametrize(
    ("measure", "unit"),
    [
        (Measure.REFERRALS_ACCEPTABLE, "{referral}"),
        (Measure.FREE_BEDS, "{bed}"),
        (Measure.FREE_SLOTS, "{slot}"),
        (Measure.OCCUPIED_PATIENTS, "{patient}"),
        (Measure.PACKAGES_FREE, "{package}"),
    ],
)
def test_each_measure_has_its_ucum_annotation(measure: Measure, unit: str) -> None:
    assert ucum_unit(measure) == unit


# report_request_from_fhir: the good case


def test_a_reporter_report_becomes_a_command_with_the_claims_to_check_against_the_service() -> None:
    request = report_request_from_fhir(_resource(), REPORTER, KEY)

    assert isinstance(request, ReportRequest)
    assert request.measure is Measure.REFERRALS_ACCEPTABLE
    assert request.unit == "{referral}"
    command = request.command
    assert command.idempotency_key == KEY
    assert command.actor is REPORTER
    assert command.service_id == "svc-ucr-west"
    assert command.value == 4
    assert command.source is ReportSource.APP
    assert command.effective_at == datetime(2026, 10, 23, 10, 0, tzinfo=UTC)
    assert command.performer_role_id is None
    assert command.replaced_value is None
    assert command.flag is None


def test_the_api_carries_app_and_advisor_phoned_reports_only() -> None:
    assert sorted(API_SOURCES) == sorted([ReportSource.APP, ReportSource.ADVISOR_PHONED])


def test_a_lead_report_names_advisor_phoned() -> None:
    resource = _with({"coding": [{"system": SOURCE_SYSTEM, "code": "advisor-phoned"}]}, "method")

    request = report_request_from_fhir(resource, LEAD, KEY)

    assert request.command.source is ReportSource.ADVISOR_PHONED
    assert request.command.actor is LEAD


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-23T10:00:00Z", datetime(2026, 10, 23, 10, 0, tzinfo=UTC)),
        ("2026-10-23T10:00:00+01:00", datetime(2026, 10, 23, 9, 0, tzinfo=UTC)),
        ("2026-10-23T10:00:00.250Z", datetime(2026, 10, 23, 10, 0, 0, 250000, tzinfo=UTC)),
        ("2026-10-23T10:00:00-05:30", datetime(2026, 10, 23, 15, 30, tzinfo=UTC)),
    ],
)
def test_the_effective_time_is_read_as_an_instant_in_utc(text: str, expected: datetime) -> None:
    request = report_request_from_fhir(_with(text, "effectiveDateTime"), REPORTER, KEY)

    assert request.command.effective_at == expected
    assert request.command.effective_at is not None
    assert request.command.effective_at.utcoffset() == timedelta(0)


def test_a_unit_text_and_extra_coding_text_are_allowed_and_not_used() -> None:
    resource = _resource()
    resource["valueQuantity"]["unit"] = "anything"
    resource["code"]["text"] = "Referrals"
    resource["code"]["coding"][0]["display"] = "Referrals acceptable"
    resource["id"] = "ignored"
    resource["meta"] = {"profile": ["https://diucs.example/StructureDefinition/capacity-report"]}

    request = report_request_from_fhir(resource, REPORTER, KEY)

    assert request.command.value == 4


def test_a_value_is_passed_to_the_use_case_whatever_its_size_so_the_rule_stays_there() -> None:
    assert report_request_from_fhir(_with(0, "valueQuantity", "value"), REPORTER, KEY)
    assert report_request_from_fhir(_with(1000, "valueQuantity", "value"), REPORTER, KEY)
    assert report_request_from_fhir(_with(-1, "valueQuantity", "value"), REPORTER, KEY)


# report_request_from_fhir: every refusal names the element and says it in fixed words

REFUSED: list[tuple[str, Any, str]] = [
    ("not an object", [], "Observation"),
    ("a string body", "x", "Observation"),
    ("no resource type", _without("resourceType"), "Observation.resourceType"),
    ("other resource type", _with("Patient", "resourceType"), "Observation.resourceType"),
    ("no status", _without("status"), "Observation.status"),
    ("preliminary", _with("preliminary", "status"), "Observation.status"),
    ("no code", _without("code"), "Observation.code"),
    ("code not an object", _with("x", "code"), "Observation.code"),
    ("no coding", _with({"coding": []}, "code"), "Observation.code"),
    ("coding not a list", _with({"coding": {}}, "code"), "Observation.code"),
    (
        "two codings",
        _with(
            {
                "coding": [
                    {"system": MEASURE_SYSTEM, "code": "referrals-acceptable"},
                    {"system": MEASURE_SYSTEM, "code": "free-beds"},
                ]
            },
            "code",
        ),
        "Observation.code",
    ),
    (
        "coding not an object",
        _with({"coding": ["referrals-acceptable"]}, "code"),
        "Observation.code",
    ),
    (
        "other code system",
        _with({"coding": [{"system": SOURCE_SYSTEM, "code": "app"}]}, "code"),
        "Observation.code",
    ),
    (
        "unknown measure",
        _with({"coding": [{"system": MEASURE_SYSTEM, "code": "free-chairs"}]}, "code"),
        "Observation.code",
    ),
    (
        "code not text",
        _with({"coding": [{"system": MEASURE_SYSTEM, "code": 4}]}, "code"),
        "Observation.code",
    ),
    ("no focus", _without("focus"), "Observation.focus"),
    (
        "focus not a list",
        _with({"reference": "HealthcareService/svc-ucr-west"}, "focus"),
        "Observation.focus",
    ),
    ("empty focus", _with([], "focus"), "Observation.focus"),
    (
        "two focus",
        _with(
            [{"reference": "HealthcareService/a"}, {"reference": "HealthcareService/b"}], "focus"
        ),
        "Observation.focus",
    ),
    ("focus not an object", _with(["HealthcareService/a"], "focus"), "Observation.focus"),
    ("focus no reference", _with([{"display": "x"}], "focus"), "Observation.focus"),
    ("focus reference not text", _with([{"reference": 5}], "focus"), "Observation.focus"),
    ("focus other type", _with([{"reference": "Patient/abc"}], "focus"), "Observation.focus"),
    ("focus bare id", _with([{"reference": "svc-ucr-west"}], "focus"), "Observation.focus"),
    ("focus empty id", _with([{"reference": "HealthcareService/"}], "focus"), "Observation.focus"),
    (
        "focus id with a slash",
        _with([{"reference": "HealthcareService/a/b"}], "focus"),
        "Observation.focus",
    ),
    (
        "focus id too long",
        _with([{"reference": "HealthcareService/" + "a" * 65}], "focus"),
        "Observation.focus",
    ),
    (
        "focus id with a space",
        _with([{"reference": "HealthcareService/a b"}], "focus"),
        "Observation.focus",
    ),
    ("no quantity", _without("valueQuantity"), "Observation.valueQuantity"),
    ("quantity not an object", _with(4, "valueQuantity"), "Observation.valueQuantity"),
    (
        "comparator",
        _with("<", "valueQuantity", "comparator"),
        "Observation.valueQuantity",
    ),
    ("no value", _without("valueQuantity", "value"), "Observation.valueQuantity.value"),
    ("decimal value", _with(4.5, "valueQuantity", "value"), "Observation.valueQuantity.value"),
    ("whole decimal", _with(4.0, "valueQuantity", "value"), "Observation.valueQuantity.value"),
    ("text value", _with("4", "valueQuantity", "value"), "Observation.valueQuantity.value"),
    ("true value", _with(True, "valueQuantity", "value"), "Observation.valueQuantity.value"),
    ("null value", _with(None, "valueQuantity", "value"), "Observation.valueQuantity.value"),
    ("no unit system", _without("valueQuantity", "system"), "Observation.valueQuantity.system"),
    (
        "other unit system",
        _with("http://example.org/units", "valueQuantity", "system"),
        "Observation.valueQuantity.system",
    ),
    ("no unit code", _without("valueQuantity", "code"), "Observation.valueQuantity.code"),
    ("unit code not text", _with(4, "valueQuantity", "code"), "Observation.valueQuantity.code"),
    ("no method", _without("method"), "Observation.method"),
    ("method not an object", _with("app", "method"), "Observation.method"),
    (
        "method other system",
        _with({"coding": [{"system": MEASURE_SYSTEM, "code": "app"}]}, "method"),
        "Observation.method",
    ),
    (
        "unknown method",
        _with({"coding": [{"system": SOURCE_SYSTEM, "code": "carrier-pigeon"}]}, "method"),
        "Observation.method",
    ),
    (
        "text is not for the api",
        _with({"coding": [{"system": SOURCE_SYSTEM, "code": "text"}]}, "method"),
        "Observation.method",
    ),
    (
        "link is not for the api",
        _with({"coding": [{"system": SOURCE_SYSTEM, "code": "link"}]}, "method"),
        "Observation.method",
    ),
    (
        "email is not for the api",
        _with({"coding": [{"system": SOURCE_SYSTEM, "code": "email"}]}, "method"),
        "Observation.method",
    ),
    (
        "feed is not for the api",
        _with({"coding": [{"system": SOURCE_SYSTEM, "code": "feed"}]}, "method"),
        "Observation.method",
    ),
    ("no effective time", _without("effectiveDateTime"), "Observation.effectiveDateTime"),
    ("date only", _with("2026-10-23", "effectiveDateTime"), "Observation.effectiveDateTime"),
    (
        "no zone",
        _with("2026-10-23T10:00:00", "effectiveDateTime"),
        "Observation.effectiveDateTime",
    ),
    (
        "no seconds",
        _with("2026-10-23T10:00Z", "effectiveDateTime"),
        "Observation.effectiveDateTime",
    ),
    (
        "month 13",
        _with("2026-13-23T10:00:00Z", "effectiveDateTime"),
        "Observation.effectiveDateTime",
    ),
    ("number", _with(1760000000, "effectiveDateTime"), "Observation.effectiveDateTime"),
    ("derived from", _with([{"reference": "Observation/x"}], "derivedFrom"), "Observation"),
    ("a performer", _with([{"reference": "PractitionerRole/x"}], "performer"), "Observation"),
    (
        "a report type",
        _with([{"url": "https://diucs.example/StructureDefinition/reportType"}], "extension"),
        "Observation",
    ),
    ("a component", _with([], "component"), "Observation"),
]


@pytest.mark.parametrize(("label", "resource", "field"), REFUSED, ids=[r[0] for r in REFUSED])
def test_a_report_the_api_cannot_take_is_refused_naming_the_element(
    label: str, resource: Any, field: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        report_request_from_fhir(copy.deepcopy(resource), REPORTER, KEY)

    assert refused.value.field == field
    # The message is fixed words: it never carries what was sent.
    assert "4.5" not in refused.value.message
    assert "carrier-pigeon" not in refused.value.message
    assert refused.value.message


def test_a_refusal_never_echoes_the_value_sent() -> None:
    secret = "zz-not-a-code-zz"
    resource = _with({"coding": [{"system": MEASURE_SYSTEM, "code": secret}]}, "code")

    with pytest.raises(ValidationFailed) as refused:
        report_request_from_fhir(resource, REPORTER, KEY)

    assert secret not in str(refused.value)
    assert secret not in refused.value.message
    assert secret not in refused.value.field


# validate_outbound


def test_a_valid_resource_comes_back_unchanged() -> None:
    resource = service_to_fhir(WEST)

    assert validate_outbound(resource) is resource


def test_a_resource_that_is_not_valid_r4b_is_a_programming_error_with_no_content_in_it() -> None:
    bad: dict[str, Any] = {"resourceType": "Observation", "status": "final", "marker": "zz-secret"}

    with pytest.raises(RuntimeError) as refused:
        validate_outbound(bad)

    assert "zz-secret" not in str(refused.value)
    assert refused.value.__cause__ is None
    assert refused.value.__suppress_context__ is True
