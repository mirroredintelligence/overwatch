"""Pure tests for the capacity report mapping (P01).

CapacityReport <-> FHIR Observation. A report is a fact: the mapping must hold it exactly. All
values are synthetic.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from diucs.adapters.outbound.graph_store.capacity_repository import (
    report_from_fhir,
    report_to_fhir,
)
from diucs.domain.codes import BASE_URL, Measure, ReportSource, ReportType
from diucs.domain.model.capacity import CapacityReport

NUMBER_REPORT = CapacityReport(
    id="obs-ucr-west-0912",
    service_id="svc-ucr-west",
    value=5,
    measure=Measure.REFERRALS_ACCEPTABLE,
    effective_at=datetime(2026, 10, 25, 9, 12, tzinfo=UTC),
    source=ReportSource.LINK,
    report_type=ReportType.NUMBER,
)

CONFIRMED_REPORT = CapacityReport(
    id="obs-ucr-west-0930",
    service_id="svc-ucr-west",
    value=3,
    measure=Measure.REFERRALS_ACCEPTABLE,
    effective_at=datetime(2026, 10, 25, 9, 30, tzinfo=UTC),
    source=ReportSource.TEXT,
    report_type=ReportType.CONFIRMED,
    performer_role_id="pr-ucr-west-reporter",
    derived_from="obs-ucr-west-0912",
)


def test_a_number_report_round_trips_through_fhir() -> None:
    assert report_from_fhir(report_to_fhir(NUMBER_REPORT)) == NUMBER_REPORT


def test_a_confirmed_report_round_trips_with_its_performer_and_derived_from() -> None:
    assert report_from_fhir(report_to_fhir(CONFIRMED_REPORT)) == CONFIRMED_REPORT


def test_the_observation_names_the_service_the_measure_and_the_source() -> None:
    resource = report_to_fhir(NUMBER_REPORT)

    assert resource["resourceType"] == "Observation"
    assert resource["status"] == "final"
    assert resource["focus"] == {"reference": "HealthcareService/svc-ucr-west"}
    assert resource["code"]["coding"][0]["code"] == "referrals-acceptable"
    assert resource["method"]["coding"][0]["code"] == "link"
    assert resource["effectiveDateTime"] == "2026-10-25T09:12:00Z"
    assert resource["valueQuantity"] == {
        "value": 5,
        "unit": "{referral}",
        "system": "http://unitsofmeasure.org",
        "code": "{referral}",
    }
    report_type = {"url": f"{BASE_URL}StructureDefinition/reportType", "valueString": "number"}
    assert report_type in resource["extension"]


@pytest.mark.parametrize(
    ("measure", "ucum"),
    [
        (Measure.REFERRALS_ACCEPTABLE, "{referral}"),
        (Measure.FREE_BEDS, "{bed}"),
        (Measure.FREE_SLOTS, "{slot}"),
        (Measure.OCCUPIED_PATIENTS, "{patient}"),
        (Measure.PACKAGES_FREE, "{package}"),
    ],
)
def test_each_measure_has_its_ucum_unit(measure: Measure, ucum: str) -> None:
    report = replace(NUMBER_REPORT, measure=measure)

    assert report_to_fhir(report)["valueQuantity"]["unit"] == ucum


def test_a_report_time_with_a_fraction_round_trips_without_trailing_zeros() -> None:
    report = replace(
        NUMBER_REPORT, effective_at=datetime(2026, 10, 25, 9, 12, 0, 120000, tzinfo=UTC)
    )

    assert report_to_fhir(report)["effectiveDateTime"] == "2026-10-25T09:12:00.12Z"
    assert report_from_fhir(report_to_fhir(report)) == report
