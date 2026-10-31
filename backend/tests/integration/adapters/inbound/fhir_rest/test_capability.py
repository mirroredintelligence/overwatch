"""GET /fhir/metadata (R01): the CapabilityStatement and the resource registry."""

import pytest
from fastapi import FastAPI
from fhir.resources.R4B.capabilitystatement import CapabilityStatement
from httpx import AsyncClient

from diucs.adapters.inbound.fhir_rest import capability

FHIR_JSON = "application/fhir+json; fhirVersion=4.3"


@pytest.fixture
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """No type and no profile from an earlier app build: the profiles are process-wide too, and
    the validation routes advertise the served profiles (R14) when an app is built."""
    monkeypatch.setattr(capability, "_RESOURCES", {})
    monkeypatch.setattr(capability, "_PROFILES", {})
    monkeypatch.setattr(capability, "_ADDED_OPERATIONS", {})


async def test_metadata_is_a_capability_statement_for_fhir_4_3(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get("/fhir/metadata")

    assert response.status_code == 200
    assert response.headers["content-type"] == FHIR_JSON
    statement = CapabilityStatement.model_validate(response.json())
    assert statement.fhirVersion == "4.3.0"
    assert statement.status == "active"
    assert statement.kind == "instance"
    assert statement.format == ["application/fhir+json"]
    assert statement.rest[0].mode == "server"


async def test_a_registered_resource_appears_in_the_next_metadata(
    api_app: FastAPI, api_client: AsyncClient, empty_registry: None
) -> None:
    capability.register_resource("HealthcareService", ["read"], [])

    response = await api_client.get("/fhir/metadata")

    resources = response.json()["rest"][0]["resource"]
    assert resources == [
        {"type": "HealthcareService", "interaction": [{"code": "read"}]},
    ]


async def test_the_metadata_is_dated_from_the_container_clock(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get("/fhir/metadata")

    assert response.json()["date"] == "2026-10-23T13:12:00Z"


async def test_the_advisor_operations_are_listed_on_healthcare_service_and_the_summary_on_the_case(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get("/fhir/metadata")

    resources = {item["type"]: item for item in response.json()["rest"][0]["resource"]}
    service_ops = {op["name"] for op in resources["HealthcareService"]["operation"]}
    case_ops = {op["name"] for op in resources["ServiceRequest"]["operation"]}
    assert {"board", "confirm-capacity"} <= service_ops
    assert {"filter-options", "advisor-phoned", "declined"} <= service_ops
    assert {"close", "summary"} <= case_ops
