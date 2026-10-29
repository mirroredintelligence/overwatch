"""Unit tests for the profile validator (R14). Sample values only.

The validator is pure Python: fhir.resources.R4B parses the structure and one rule function per
profile checks the profile. Each issue names an element path and a fixed message, never a value.
"""

import json
from pathlib import Path
from typing import Any

from fhir.resources.R4B.structuredefinition import StructureDefinition

from diucs.adapters.outbound.fhir_validator.validator import (
    PROFILE_NAMES,
    ProfileValidator,
    profile_url,
)
from diucs.adapters.outbound.graph_store.capacity_repository import report_to_fhir
from tests.unit.adapters.outbound.graph_store.test_capacity_repository import NUMBER_REPORT

PROFILES_DIR = Path(__file__).resolve().parents[5] / "profiles"
EXPECTED_PROFILES = {
    "DiucsPatientCaseStub",
    "DiucsCapacityReport",
    "DiucsServiceCriteria",
    "DiucsBookingRequest",
    "DiucsHealthcareService",
}
CAPACITY = profile_url("DiucsCapacityReport")


def _capacity_observation() -> dict[str, Any]:
    """The report as FHIR R4B needs it. report_to_fhir writes focus as one object, but R4B
    Observation.focus is a list, so the fixture sets the list form (known issue R14-1)."""
    resource = json.loads(json.dumps(report_to_fhir(NUMBER_REPORT)))
    resource["focus"] = [resource["focus"]]
    return resource


def _paths(issues: list[Any]) -> list[str]:
    return [issue.path for issue in issues]


async def test_a_valid_capacity_observation_has_no_issues() -> None:
    issues = await ProfileValidator().validate(_capacity_observation(), CAPACITY)
    assert issues == []


async def test_a_figure_that_is_not_a_whole_number_is_refused_at_its_element() -> None:
    resource = _capacity_observation()
    resource["valueQuantity"]["value"] = 4.5
    issues = await ProfileValidator().validate(resource, CAPACITY)
    assert "Observation.valueQuantity.value" in _paths(issues)
    assert all(issue.severity == "error" for issue in issues)


async def test_a_patient_stub_with_a_name_is_refused_with_the_rule_in_words() -> None:
    stub = {
        "resourceType": "Patient",
        "id": "stub-sample-1",
        "meta": {"tag": [{"code": "pseudonymised-case-stub"}]},
        "extension": [
            {"url": "https://diucs.example/Extension/age-band", "valueCode": "65-79"},
        ],
        "name": [{"family": "Sample"}],
    }
    issues = await ProfileValidator().validate(stub, profile_url("DiucsPatientCaseStub"))
    refused = [issue for issue in issues if issue.path == "Patient.name"]
    assert [issue.message for issue in refused] == ["No patient names are stored"]


async def test_a_wrong_type_for_status_is_a_structural_issue() -> None:
    resource = _capacity_observation()
    resource["status"] = 12
    issues = await ProfileValidator().validate(resource, CAPACITY)
    assert any(issue.path.startswith("Observation.status") for issue in issues)


async def test_a_resource_of_another_type_is_refused_for_the_profile() -> None:
    issues = await ProfileValidator().validate(
        _capacity_observation(), profile_url("DiucsHealthcareService")
    )
    assert issues != []


async def test_an_unknown_profile_is_an_issue_not_a_pass() -> None:
    issues = await ProfileValidator().validate(
        _capacity_observation(), f"{profile_url('NotAProfile')}"
    )
    assert issues != []


def test_every_profile_file_parses_and_has_a_rule_and_every_rule_has_a_file() -> None:
    names = {path.stem for path in PROFILES_DIR.glob("*.json")}
    assert names == EXPECTED_PROFILES
    for path in PROFILES_DIR.glob("*.json"):
        definition = StructureDefinition.model_validate(json.loads(path.read_text("utf-8")))
        assert definition.url == profile_url(path.stem)
    assert set(PROFILE_NAMES) == EXPECTED_PROFILES
