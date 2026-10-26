"""FHIR REST app skeleton (R01): health, OperationOutcome error bodies, media types, the 415 check.

Every request goes through api_client, on the throwaway Neo4j of the harness. Error texts are
checked for the synthetic postcode "DT4 8XX": no error body and no log line may carry it.
"""

import logging
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

from diucs.bootstrap.container import Container
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed

FHIR_JSON = "application/fhir+json; fhirVersion=4.3"
SAMPLE_POSTCODE = "DT4 8XX"


class Echo(BaseModel):
    postcode: str
    count: int


def add_route(app: FastAPI, path: str, handler: Callable[..., Any], methods: list[str]) -> None:
    app.add_api_route(path, handler, methods=methods)


def raising(error: Exception) -> Callable[[], None]:
    def handler() -> None:
        raise error

    return handler


async def test_health_returns_ok(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_a_not_found_error_is_an_operation_outcome(
    api_app: FastAPI, api_client: AsyncClient
) -> None:
    add_route(api_app, "/fhir/test/not-found", raising(NotFound()), ["GET"])

    response = await api_client.get("/fhir/test/not-found")

    assert response.status_code == 404
    assert response.headers["content-type"] == FHIR_JSON
    body = response.json()
    assert body["resourceType"] == "OperationOutcome"
    assert len(body["issue"]) == 1
    assert body["issue"][0]["severity"] == "error"
    assert body["issue"][0]["code"] == "not-found"
    assert body["issue"][0]["diagnostics"]


async def test_a_not_allowed_error_has_a_body_byte_identical_to_not_found(
    api_app: FastAPI, api_client: AsyncClient
) -> None:
    add_route(api_app, "/fhir/test/not-found", raising(NotFound()), ["GET"])
    add_route(api_app, "/fhir/test/not-allowed", raising(NotAllowed()), ["GET"])

    missing = await api_client.get("/fhir/test/not-found")
    forbidden = await api_client.get("/fhir/test/not-allowed")

    assert forbidden.status_code == 404
    assert forbidden.content == missing.content


async def test_a_validation_failure_is_400_invalid_with_the_field_in_expression(
    api_app: FastAPI, api_client: AsyncClient
) -> None:
    add_route(
        api_app,
        "/fhir/test/validation",
        raising(ValidationFailed("postcode", "Enter a full postcode")),
        ["GET"],
    )

    response = await api_client.get("/fhir/test/validation")

    assert response.status_code == 400
    issue = response.json()["issue"][0]
    assert issue["code"] == "invalid"
    assert issue["expression"] == ["postcode"]
    assert issue["diagnostics"] == "Enter a full postcode"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (InvalidTransition(), 409, "business-rule"),
        (Conflict(), 409, "conflict"),
    ],
)
async def test_state_errors_map_to_409(
    api_app: FastAPI,
    api_client: AsyncClient,
    error: Exception,
    status: int,
    code: str,
) -> None:
    add_route(api_app, "/fhir/test/state", raising(error), ["GET"])

    response = await api_client.get("/fhir/test/state")

    assert response.status_code == status
    assert response.json()["issue"][0]["code"] == code


async def test_an_unexpected_error_is_500_exception_without_its_message(
    api_app: FastAPI, api_client: AsyncClient
) -> None:
    add_route(api_app, "/fhir/test/boom", raising(RuntimeError(SAMPLE_POSTCODE)), ["GET"])

    response = await api_client.get("/fhir/test/boom")

    assert response.status_code == 500
    assert response.headers["content-type"] == FHIR_JSON
    issue = response.json()["issue"][0]
    assert issue["code"] == "exception"
    assert issue["diagnostics"] == "Internal error"
    assert "DT4" not in response.text


async def test_an_unexpected_error_is_logged_without_its_message_or_trace(
    api_app: FastAPI, api_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    add_route(api_app, "/fhir/test/boom", raising(RuntimeError(SAMPLE_POSTCODE)), ["GET"])
    caplog.set_level(logging.DEBUG)

    await api_client.get("/fhir/test/boom")

    assert "RuntimeError" in caplog.text
    assert "DT4" not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.parametrize("method", ["POST", "PUT"])
async def test_a_text_body_on_post_or_put_is_415(
    api_app: FastAPI, api_client: AsyncClient, method: str
) -> None:
    add_route(api_app, "/fhir/test/echo", lambda: {"ok": True}, ["POST", "PUT"])

    response = await api_client.request(
        method,
        "/fhir/test/echo",
        content=b"DT4 8XX",
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.headers["content-type"] == FHIR_JSON
    assert response.json()["issue"][0]["code"] == "not-supported"
    assert "DT4" not in response.text


@pytest.mark.parametrize(
    "content_type",
    [
        "application/fhir+json",
        "application/json",
        "application/fhir+json; fhirVersion=4.3",
    ],
)
async def test_fhir_and_json_bodies_on_post_are_accepted(
    api_app: FastAPI, api_client: AsyncClient, content_type: str
) -> None:
    add_route(api_app, "/fhir/test/echo", lambda: {"ok": True}, ["POST"])

    response = await api_client.post(
        "/fhir/test/echo", content=b"{}", headers={"Content-Type": content_type}
    )

    assert response.status_code == 200


async def test_a_request_body_that_fails_validation_is_400_without_its_values(
    api_app: FastAPI, api_client: AsyncClient
) -> None:
    def handler(body: Echo) -> dict[str, bool]:
        return {"ok": True}

    add_route(api_app, "/fhir/test/echo-model", handler, ["POST"])

    response = await api_client.post(
        "/fhir/test/echo-model",
        json={"postcode": SAMPLE_POSTCODE, "count": "many"},
    )

    assert response.status_code == 400
    issue = response.json()["issue"][0]
    assert issue["code"] == "invalid"
    assert issue["expression"] == ["count"]
    assert "DT4" not in response.text
    assert "many" not in response.text


async def test_an_unknown_path_under_fhir_is_an_operation_outcome(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get("/fhir/nowhere")

    assert response.status_code == 404
    assert response.headers["content-type"] == FHIR_JSON
    assert response.json()["issue"][0]["code"] == "not-found"


async def test_a_wrong_method_is_an_operation_outcome(api_client: AsyncClient) -> None:
    response = await api_client.post("/health", json={})

    assert response.status_code == 405
    assert response.json()["resourceType"] == "OperationOutcome"
    assert response.json()["issue"][0]["code"] == "not-supported"


async def test_the_app_is_built_on_the_container_it_was_given(
    api_app: FastAPI, test_container: Container
) -> None:
    assert api_app.state.container is test_container
