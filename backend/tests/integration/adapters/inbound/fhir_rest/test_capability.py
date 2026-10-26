"""GET /fhir/metadata (R01): the CapabilityStatement and the resource registry."""

import pytest
from fastapi import FastAPI
from fhir.resources.R4B.capabilitystatement import CapabilityStatement
from httpx import AsyncClient

from diucs.adapters.inbound.fhir_rest import capability

FHIR_JSON = "application/fhir+json; fhirVersion=4.3"


@pytest.fixture
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability, "_RESOURCES", {})


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
