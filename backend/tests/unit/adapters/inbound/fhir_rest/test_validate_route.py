"""The $validate operation and the profile check on POST /fhir/Observation (R14).

The app is built on a container with no Neo4j: a refused body never reaches a use case, and
$validate reads nothing from the store, so these tests need no Docker. Sample values only.
"""

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.fhir_validator.validator import profile_url
from diucs.adapters.outbound.graph_store.capacity_repository import report_to_fhir
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.bootstrap.container import TEST_NOW
from diucs.domain.codes import Role
from diucs.adapters.outbound.fhir_validator.validator import ProfileValidator
from tests.unit.adapters.outbound.graph_store.test_capacity_repository import NUMBER_REPORT

CAPACITY = profile_url("DiucsCapacityReport")
REPORTER = {"authorization": "Bearer " + issue_test_token(Role.REPORTER, [], "sample-reporter")}


class _NoStoreContainer:
    """Everything the routes read except the validator: the clock and the ids. No unit of work."""

    def __init__(self) -> None:
        self.clock = FixedClock(TEST_NOW)
        self.ids = SequentialIds()
        self.uow_factory: Any = None
        self.validator = ProfileValidator()


@pytest.fixture
def app() -> Any:
    built = create_app(_NoStoreContainer())  # type: ignore[arg-type]
    built.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    return built


def _observation() -> dict[str, Any]:
    return json.loads(json.dumps(report_to_fhir(NUMBER_REPORT)))


def _issues(body: dict[str, Any]) -> list[dict[str, Any]]:
    assert body["resourceType"] == "OperationOutcome"
    return list(body["issue"])


async def test_a_valid_capacity_observation_validates_with_one_information_issue(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/fhir/Observation/$validate", params={"profile": CAPACITY},
            json=_observation(), headers=REPORTER,
        )
    assert response.status_code == 200
    [issue] = _issues(response.json())
    assert issue["severity"] == "information"
    assert issue["diagnostics"] == "Valid"


async def test_each_problem_comes_back_with_its_expression(app: Any) -> None:
    resource = _observation()
    resource["valueQuantity"]["value"] = 4.5
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/fhir/Observation/$validate", params={"profile": CAPACITY},
            json=resource, headers=REPORTER,
        )
    issues = _issues(response.json())
    assert [issue["expression"] for issue in issues] == [["Observation.valueQuantity.value"]]
    assert issues[0]["severity"] == "error"


async def test_validate_needs_a_token(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/fhir/Observation/$validate", params={"profile": CAPACITY}, json=_observation()
        )
    assert response.status_code == 401


async def test_a_patient_stub_with_a_name_is_refused_by_validate(app: Any) -> None:
    stub = {
        "resourceType": "Patient",
        "id": "stub-sample-1",
        "meta": {"tag": [{"code": "pseudonymised-case-stub"}]},
        "extension": [{"url": "https://diucs.example/Extension/age-band", "valueCode": "65-79"}],
        "name": [{"family": "Sample"}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/fhir/Patient/$validate",
            params={"profile": profile_url("DiucsPatientCaseStub")},
            json=stub,
            headers=REPORTER,
        )
    [issue] = _issues(response.json())
    assert issue["expression"] == ["Patient.name"]
    assert issue["diagnostics"] == "No patient names are stored"


async def test_the_capability_statement_lists_the_capacity_profile(app: Any) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/fhir/metadata")
    resources = response.json()["rest"][0]["resource"]
    observation = next(entry for entry in resources if entry["type"] == "Observation")
    assert CAPACITY in observation["supportedProfile"]


async def test_a_report_that_breaks_the_profile_is_refused_before_any_use_case(app: Any) -> None:
    resource = _observation()
    resource["valueQuantity"]["value"] = 4.5
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/fhir/Observation", json=resource, headers=REPORTER)
    assert response.status_code == 400
    [issue] = _issues(response.json())
    assert issue["expression"] == ["Observation.valueQuantity.value"]
