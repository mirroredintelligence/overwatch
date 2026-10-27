"""FHIR auth over HTTP (R02): 401 login, the role, scope and patient refusals, projection, and logs.

Runs through api_client on the harness Neo4j (DEC-004). The app's secret store holds a synthetic
secret. Each route below is test-only and added to api_app for the test. A refusal must be
byte-identical to a missing record's 404 (DEC-086 item 5). Synthetic values only: no token, secret
or patient text may appear in a response or a log line.
"""

import json
import logging
from datetime import timedelta
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fhir.resources.R4B.task import Task
from httpx import AsyncClient, Response

from diucs.adapters.inbound.fhir_rest.auth import (
    BFF_SECRET_NAME,
    PROJECTIONS,
    current_actor,
    ensure_can_act_for,
    ensure_patient_access,
    require_role,
)
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.actor import Actor
from diucs.domain.codes import Role
from diucs.domain.rules.bff_token import BffClaims, encode_bff_token
from tests.support.api import R01_TEST_NOW

FHIR_JSON = "application/fhir+json; fhirVersion=4.3"
OTHER_SECRET = b"another-synthetic-secret-for-route-tests-zyxwvutsrq"
REDACTED_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ObservationValue"
ONE_SECOND = R01_TEST_NOW + timedelta(seconds=1)


@pytest.fixture
def auth_app(api_app: FastAPI) -> FastAPI:
    """The API with the synthetic BFF secret and the test-only routes below."""
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})

    @api_app.get("/fhir/test/whoami")
    def whoami(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, Any]:
        return {
            "role": actor.role.value,
            "practitioner_id": actor.practitioner_id,
            "device_id": actor.device_id,
            "channel": actor.channel,
            "service_ids": sorted(actor.service_ids),
        }

    @api_app.get("/fhir/test/lead-only", dependencies=[Depends(require_role(Role.LEAD))])
    def lead_only() -> dict[str, str]:
        return {"status": "ok"}

    @api_app.get("/fhir/test/services/{service_id}")
    def service_scope(
        service_id: str, actor: Annotated[Actor, Depends(current_actor)]
    ) -> dict[str, str]:
        ensure_can_act_for(actor, service_id)
        return {"status": "ok"}

    @api_app.get("/fhir/test/patient")
    def patient(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, str]:
        ensure_patient_access(actor)
        return {"status": "ok"}

    @api_app.get("/fhir/test/booking-task")
    def booking_task(actor: Annotated[Actor, Depends(current_actor)]) -> JSONResponse:
        task = Task.model_validate(
            {
                "status": "requested",
                "intent": "order",
                "focus": {"reference": "ServiceRequest/req-1"},
                "for": {"reference": "Patient/pat-1"},
            }
        )
        projected = PROJECTIONS.project(task, actor)
        return JSONResponse(projected.model_dump(by_alias=True, exclude_none=True))

    return api_app


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login_body_is_right(response: Response) -> None:
    assert response.status_code == 401
    assert response.headers["content-type"] == FHIR_JSON
    assert response.headers["www-authenticate"] == "Bearer"
    body = response.json()
    assert body["resourceType"] == "OperationOutcome"
    assert [issue["code"] for issue in body["issue"]] == ["login"]


async def test_a_request_with_no_authorization_header_is_a_login_error(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    response = await api_client.get("/fhir/test/whoami")

    login_body_is_right(response)


async def test_an_expired_token_is_a_login_error(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.REPORTER, ["svc-1"], "prac-1", expires_at=R01_TEST_NOW)

    response = await api_client.get("/fhir/test/whoami", headers=bearer(token))

    login_body_is_right(response)


async def test_a_token_one_second_before_its_expiry_is_accepted(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.REPORTER, ["svc-1"], "prac-1", expires_at=ONE_SECOND)

    response = await api_client.get("/fhir/test/whoami", headers=bearer(token))

    assert response.status_code == 200


async def test_a_token_with_a_wrong_signature_is_a_login_error(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    claims = BffClaims(
        sub="prac-1",
        role=Role.REPORTER,
        services=frozenset({"svc-1"}),
        expires_at=ONE_SECOND,
    )
    token = encode_bff_token(claims, OTHER_SECRET)

    response = await api_client.get("/fhir/test/whoami", headers=bearer(token))

    login_body_is_right(response)


async def test_a_basic_authorization_scheme_is_a_login_error(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.REPORTER, ["svc-1"], "prac-1")

    response = await api_client.get(
        "/fhir/test/whoami", headers={"Authorization": f"Basic {token}"}
    )

    login_body_is_right(response)


async def test_a_login_error_never_repeats_the_token(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.REPORTER, ["svc-1"], "prac-1", expires_at=R01_TEST_NOW)

    response = await api_client.get("/fhir/test/whoami", headers=bearer(token))

    assert token not in response.text


async def test_a_reporter_token_gives_its_practitioner_and_its_service(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.REPORTER, ["svc-1"], "prac-1")

    response = await api_client.get("/fhir/test/whoami", headers=bearer(token))

    assert response.status_code == 200
    assert response.json() == {
        "role": "reporter",
        "practitioner_id": "prac-1",
        "device_id": None,
        "channel": "api",
        "service_ids": ["svc-1"],
    }


async def test_a_wall_token_sets_the_device_and_not_the_practitioner(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.WALL, [], "dev-1")

    response = await api_client.get("/fhir/test/whoami", headers=bearer(token))

    assert response.json()["device_id"] == "dev-1"
    assert response.json()["practitioner_id"] is None


async def _refusal_bytes(api_client: AsyncClient) -> tuple[int, bytes]:
    missing = await api_client.get("/fhir/test/does-not-exist")
    return missing.status_code, missing.content


async def test_a_refused_role_gets_the_same_body_as_a_missing_record(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.ADVISOR, [], "prac-1")

    refused = await api_client.get("/fhir/test/lead-only", headers=bearer(token))
    missing_status, missing_body = await _refusal_bytes(api_client)

    assert refused.status_code == missing_status == 404
    assert refused.content == missing_body


async def test_a_listed_role_passes_require_role(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.LEAD, [], "prac-2")

    response = await api_client.get("/fhir/test/lead-only", headers=bearer(token))

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("role", "services", "service_id", "status"),
    [
        pytest.param(Role.REPORTER, ["svc-1"], "svc-1", 200, id="reporter-own-service"),
        pytest.param(Role.REPORTER, ["svc-1"], "svc-2", 404, id="reporter-other-service"),
        pytest.param(Role.LEAD, [], "svc-2", 200, id="lead-any-service"),
    ],
)
async def test_acting_for_a_service_is_scoped(
    auth_app: FastAPI,
    api_client: AsyncClient,
    role: Role,
    services: list[str],
    service_id: str,
    status: int,
) -> None:
    token = issue_test_token(role, services, "prac-1")

    response = await api_client.get(f"/fhir/test/services/{service_id}", headers=bearer(token))

    assert response.status_code == status
    if status == 404:
        _, missing_body = await _refusal_bytes(api_client)
        assert response.content == missing_body


@pytest.mark.parametrize(
    ("role", "status"),
    [
        pytest.param(Role.ADVISOR, 200, id="advisor"),
        pytest.param(Role.CLINICAL, 200, id="clinical"),
        pytest.param(Role.EXEC, 404, id="exec"),
        pytest.param(Role.WALL, 404, id="wall"),
        pytest.param(Role.REPORTER, 404, id="reporter"),
    ],
)
async def test_patient_level_access_is_for_advisor_and_clinical(
    auth_app: FastAPI, api_client: AsyncClient, role: Role, status: int
) -> None:
    token = issue_test_token(role, ["svc-1"], "prac-1")

    response = await api_client.get("/fhir/test/patient", headers=bearer(token))

    assert response.status_code == status


async def test_a_reporter_gets_a_booking_task_without_its_case_and_with_the_label(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.REPORTER, ["svc-1"], "prac-1")

    response = await api_client.get("/fhir/test/booking-task", headers=bearer(token))

    body = response.json()
    assert "focus" not in body
    assert "for" not in body
    assert body["meta"]["security"] == [{"system": REDACTED_SYSTEM, "code": "REDACTED"}]


async def test_an_advisor_gets_the_booking_task_unchanged_with_no_label(
    auth_app: FastAPI, api_client: AsyncClient
) -> None:
    token = issue_test_token(Role.ADVISOR, [], "prac-1")

    response = await api_client.get("/fhir/test/booking-task", headers=bearer(token))

    body = response.json()
    assert body["focus"] == {"reference": "ServiceRequest/req-1"}
    assert body["for"] == {"reference": "Patient/pat-1"}
    assert "meta" not in body


async def test_a_missing_secret_store_is_an_unexpected_error_not_a_pass(
    api_app: FastAPI, api_client: AsyncClient
) -> None:
    @api_app.get("/fhir/test/whoami")
    def whoami(actor: Annotated[Actor, Depends(current_actor)]) -> dict[str, str]:
        return {"role": actor.role.value}

    token = issue_test_token(Role.ADVISOR, [], "prac-1")

    response = await api_client.get("/fhir/test/whoami", headers=bearer(token))

    assert response.status_code == 500
    assert json.loads(response.text)["issue"][0]["code"] == "exception"
    assert token not in response.text

    # The same token succeeds once the store is set, so the 500 comes from the missing secret and
    # not from a stub or a broken token (a stub alone also returns 500).
    api_app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    recovered = await api_client.get("/fhir/test/whoami", headers=bearer(token))

    assert recovered.status_code == 200


async def test_no_token_text_reaches_the_log(
    auth_app: FastAPI, api_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    good = issue_test_token(Role.REPORTER, ["svc-1"], "prac-1")
    bad = issue_test_token(Role.REPORTER, ["svc-1"], "prac-1", expires_at=R01_TEST_NOW)

    await api_client.get("/fhir/test/whoami", headers=bearer(good))
    await api_client.get("/fhir/test/whoami", headers=bearer(bad))
    await api_client.get("/fhir/test/whoami", headers={"Authorization": "Bearer junk.junk.junk"})

    assert good not in caplog.text
    assert bad not in caplog.text
    assert "junk.junk.junk" not in caplog.text
