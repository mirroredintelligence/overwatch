"""Pure tests of the board and report mappers of the FHIR API (R05). No Docker, no HTTP.

board_to_parameters turns a Board into a FHIR R4B Parameters resource: one `entry` parameter per
service whose parts are the BoardEntry fields in camelCase, plus `pressure`, `allLimitedOrWorse`
and `generatedAt`. A null field is left out. report_to_fhir turns a stored capacity report into the
Observation the confirm operation returns.
"""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.parameters import Parameters

from diucs.adapters.inbound.fhir_rest.mapping import board_to_parameters, report_to_fhir
from diucs.application.use_cases.query_board import Board, BoardEntry
from diucs.domain.codes import Measure, ReportSource, ReportType, ServiceCategory, Status
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.rules.pressure import Pressure

GENERATED_AT = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
WEST_REPORTED_AT = datetime(2026, 10, 23, 13, 3, tzinfo=UTC)
WEST_NEXT_DUE = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
FRAILTY_WAS_DUE = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)

WEST = BoardEntry(
    service_id="svc-ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    status=Status.ACCEPTING,
    effective_available=4,
    over_by=None,
    used=4,
    established=8,
    pending=1,
    unit_label="referrals",
    comment="Back at 16:00",
    reported_at=WEST_REPORTED_AT,
    next_due_at=WEST_NEXT_DUE,
    was_due_at=None,
)
WARD_A = BoardEntry(
    service_id="svc-ward-a",
    name="Ward A",
    category=ServiceCategory.INPATIENT_BEDS,
    status=Status.OVER_CAPACITY,
    effective_available=None,
    over_by=2,
    used=14,
    established=12,
    pending=0,
    unit_label="beds",
    comment="",
    reported_at=None,
    next_due_at=None,
    was_due_at=FRAILTY_WAS_DUE,
)
BOARD = Board(
    entries=(WEST, WARD_A),
    pressure=Pressure.WATCH,
    all_limited_or_worse=False,
    generated_at=GENERATED_AT,
)


def _parameters(board: Board = BOARD) -> dict[str, Any]:
    return board_to_parameters(board)


def _named(parameters: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [item for item in parameters["parameter"] if item["name"] == name]


def _parts(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {part["name"]: part for part in entry["part"]}


def test_two_services_become_two_entry_parameters_and_three_top_level_parameters() -> None:
    parameters = _parameters()

    assert parameters["resourceType"] == "Parameters"
    assert [item["name"] for item in parameters["parameter"]] == [
        "entry",
        "entry",
        "pressure",
        "allLimitedOrWorse",
        "generatedAt",
    ]
    assert _named(parameters, "pressure") == [{"name": "pressure", "valueCode": "watch"}]
    assert _named(parameters, "allLimitedOrWorse") == [
        {"name": "allLimitedOrWorse", "valueBoolean": False}
    ]
    assert _named(parameters, "generatedAt") == [
        {"name": "generatedAt", "valueDateTime": "2026-10-23T13:12:00Z"}
    ]


def test_the_result_parses_as_an_r4b_parameters_resource() -> None:
    parsed = Parameters.model_validate(_parameters())

    assert parsed.parameter is not None
    assert len(parsed.parameter) == 5


def test_an_entry_has_camel_case_parts_of_the_right_fhir_types() -> None:
    west = _parts(_named(_parameters(), "entry")[0])

    assert west["serviceId"] == {"name": "serviceId", "valueString": "svc-ucr-west"}
    assert west["name"] == {"name": "name", "valueString": "UCR West"}
    assert west["category"] == {"name": "category", "valueCode": "urgent-community-response"}
    assert west["status"] == {"name": "status", "valueCode": "accepting"}
    assert west["effectiveAvailable"] == {"name": "effectiveAvailable", "valueInteger": 4}
    assert west["used"] == {"name": "used", "valueInteger": 4}
    assert west["established"] == {"name": "established", "valueInteger": 8}
    assert west["pending"] == {"name": "pending", "valueInteger": 1}
    assert west["unitLabel"] == {"name": "unitLabel", "valueString": "referrals"}
    assert west["comment"] == {"name": "comment", "valueString": "Back at 16:00"}
    assert west["reportedAt"] == {"name": "reportedAt", "valueDateTime": "2026-10-23T13:03:00Z"}
    assert west["nextDueAt"] == {"name": "nextDueAt", "valueDateTime": "2026-10-23T15:00:00Z"}


def test_the_parts_are_in_board_entry_field_order() -> None:
    west = _named(_parameters(), "entry")[0]

    assert [part["name"] for part in west["part"]] == [
        "serviceId",
        "name",
        "category",
        "status",
        "effectiveAvailable",
        "used",
        "established",
        "pending",
        "unitLabel",
        "comment",
        "reportedAt",
        "nextDueAt",
    ]


def test_a_null_over_by_is_omitted_and_a_present_one_is_an_integer() -> None:
    west, ward = (_parts(entry) for entry in _named(_parameters(), "entry"))

    assert "overBy" not in west
    assert ward["overBy"] == {"name": "overBy", "valueInteger": 2}


def test_every_null_field_is_omitted() -> None:
    ward = _parts(_named(_parameters(), "entry")[1])

    for name in ("effectiveAvailable", "reportedAt", "nextDueAt"):
        assert name not in ward
    assert ward["wasDueAt"] == {"name": "wasDueAt", "valueDateTime": "2026-10-23T11:00:00Z"}


def test_an_empty_comment_is_omitted_because_fhir_has_no_empty_string() -> None:
    ward = _parts(_named(_parameters(), "entry")[1])

    assert "comment" not in ward


def test_a_zero_is_kept_not_treated_as_null() -> None:
    zero = replace(WEST, effective_available=0, pending=0, used=0, over_by=0)

    parts = _parts(_named(_parameters(replace(BOARD, entries=(zero,))), "entry")[0])

    assert parts["effectiveAvailable"]["valueInteger"] == 0
    assert parts["pending"]["valueInteger"] == 0
    assert parts["used"]["valueInteger"] == 0
    assert parts["overBy"]["valueInteger"] == 0


def test_every_board_entry_field_is_a_part_so_a_new_field_must_be_mapped() -> None:
    camel = {
        "service_id": "serviceId",
        "name": "name",
        "category": "category",
        "status": "status",
        "effective_available": "effectiveAvailable",
        "over_by": "overBy",
        "used": "used",
        "established": "established",
        "pending": "pending",
        "unit_label": "unitLabel",
        "comment": "comment",
        "reported_at": "reportedAt",
        "next_due_at": "nextDueAt",
        "was_due_at": "wasDueAt",
    }
    assert {field.name for field in fields(BoardEntry)} == set(camel)
    full = replace(
        WEST,
        over_by=1,
        was_due_at=FRAILTY_WAS_DUE,
    )

    parts = _parts(_named(_parameters(replace(BOARD, entries=(full,))), "entry")[0])

    assert set(parts) == set(camel.values())


def test_an_empty_board_has_only_the_top_level_parameters() -> None:
    parameters = _parameters(replace(BOARD, entries=(), pressure=Pressure.NORMAL))

    assert [item["name"] for item in parameters["parameter"]] == [
        "pressure",
        "allLimitedOrWorse",
        "generatedAt",
    ]
    Parameters.model_validate(parameters)


def test_a_time_with_microseconds_is_written_in_full_with_a_z_suffix() -> None:
    precise = replace(GENERATED_AT, microsecond=250000)

    parameters = _parameters(replace(BOARD, generated_at=precise))

    assert _named(parameters, "generatedAt")[0]["valueDateTime"] == "2026-10-23T13:12:00.250000Z"


def test_a_time_in_another_zone_is_written_in_utc() -> None:
    bst = replace(GENERATED_AT, tzinfo=timezone(timedelta(hours=1)))  # 13:12 at +01:00

    parameters = _parameters(replace(BOARD, generated_at=bst))

    assert _named(parameters, "generatedAt")[0]["valueDateTime"] == "2026-10-23T12:12:00Z"


@pytest.mark.parametrize("word", ["postcode", "patient", "servicerequest"])
def test_the_parameters_hold_no_patient_word(word: str) -> None:
    assert word not in repr(_parameters()).lower()


# report_to_fhir: the Observation the confirm operation returns


CONFIRMED = CapacityReport(
    id="obs-confirm-1",
    service_id="svc-ucr-west",
    value=4,
    measure=Measure.REFERRALS_ACCEPTABLE,
    effective_at=GENERATED_AT,
    source=ReportSource.APP,
    report_type=ReportType.CONFIRMED,
    derived_from="obs-west-1403",
)


def test_a_confirmation_is_an_r4b_observation_derived_from_the_report_it_confirms() -> None:
    resource = report_to_fhir(CONFIRMED)

    observation = Observation.model_validate(resource)
    assert observation.id == "obs-confirm-1"
    assert observation.status == "final"
    assert resource["focus"] == [{"reference": "HealthcareService/svc-ucr-west"}]
    assert resource["derivedFrom"] == [{"reference": "Observation/obs-west-1403"}]
    assert resource["valueQuantity"]["value"] == 4
    assert resource["valueQuantity"]["code"] == "{referral}"
    assert resource["effectiveDateTime"] == "2026-10-23T13:12:00Z"
    assert [entry["valueString"] for entry in resource["extension"]] == ["confirmed"]


def test_a_number_report_has_no_derived_from_and_names_its_source() -> None:
    number = replace(
        CONFIRMED, id="obs-west-1403", report_type=ReportType.NUMBER, derived_from=None
    )

    resource = report_to_fhir(number)

    Observation.model_validate(resource)
    assert "derivedFrom" not in resource
    assert resource["method"]["coding"][0]["code"] == "app"
    assert resource["extension"][0]["valueString"] == "number"
