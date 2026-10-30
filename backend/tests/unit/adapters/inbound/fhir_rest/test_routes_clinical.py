"""The clinical advice and safety-concern routes (R13) in-process and with no Neo4j.

Every refusal here is made before a unit of work or the cache is touched, against a container whose
unit-of-work factory fails the test if it is called. The stored results (the presence, the queue,
the take, the advice, the request, the safety concern and its reference) are in
tests/integration/adapters/inbound/fhir_rest/test_routes_clinical.py, written but not run in this
build. Sample values only.

`POST /fhir/Task` carries two Task codes, clinical-advice and safety-concern, so the key and the
Task's shape are checked for both here, and each code's own inputs are checked by name. A free text
of more than 280 characters is refused without being echoed back.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, default_token_tenant, issue_test_token
from diucs.domain.codes import Role, code_system_url
from tests.support.edge import active_tenants

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
KEY = {"Idempotency-Key": "clinical-route-key-0001"}
EDGE_REFUSED: frozenset[Role] = frozenset({Role.PLATFORM_OPERATOR})
CLINICAL = frozenset({Role.CLINICAL})
PRESENCE = "/clinical/presence"
AVAILABLE = "/clinical/available"
QUEUE = "/fhir/Task?code=clinical-advice&status=requested"
TASK = "/fhir/Task"
TAKE = "/fhir/Task/req-1/$take"
ADVISE = "/fhir/Task/req-1/$advise"
NOTE_LIMIT = 280


@dataclass(frozen=True)
class _RouteContainer:
    clock: FixedClock
    ids: SequentialIds
    uow_factory: Any
    secrets: FixedSecretStore
    tenants: Any


def _no_unit_of_work() -> Any:
    raise AssertionError("the route opened a unit of work before refusing")


@asynccontextmanager
async def _client() -> AsyncIterator[AsyncClient]:
    container = _RouteContainer(
        clock=FixedClock(NOW),
        ids=SequentialIds(),
        uow_factory=_no_unit_of_work,
        secrets=FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET}),
        tenants=active_tenants(default_token_tenant()),
    )
    app: FastAPI = create_app(container)  # type: ignore[arg-type]
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client


def _bearer(role: Role, sub: str = "clinical-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub)}"}


def _parameters(*parts: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, **value} for name, value in parts],
    }


def _input_url(name: str) -> str:
    return code_system_url(f"task-input/{name}")


def _clinical_task(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "resourceType": "Task",
        "code": {"coding": [{"code": "clinical-advice"}]},
        "focus": {"reference": "ServiceRequest/case-1"},
        "extension": [
            {"url": _input_url("urgency"), "valueCode": "now"},
            {"url": _input_url("why"), "valueCode": "borderline-criteria"},
        ],
    }
    body.update(overrides)
    return body


def _safety_task(text: str = "The board showed the wrong service.") -> dict[str, Any]:
    return {
        "resourceType": "Task",
        "code": {"coding": [{"code": "safety-concern"}]},
        "extension": [
            {"url": _input_url("category"), "valueCode": "wrong-service-shown"},
            {"url": _input_url("text"), "valueString": text},
        ],
    }


# ----------------------------------------------------------------- the role boundary of each route


async def _send(client: AsyncClient, method: str, path: str, body: Any, role: Role) -> Any:
    headers = _bearer(role)
    if body is None:
        return await client.request(
            method, path, content=b"", headers={**headers, "Content-Type": "application/json"}
        )
    return await client.request(method, path, json=body, headers=headers)


async def test_the_presence_route_is_for_the_clinical_advisor_only() -> None:
    async with _client() as client:
        for role in Role:
            response = await _send(client, "PUT", PRESENCE, {"presence": "busy"}, role)
            if role in CLINICAL:
                assert response.status_code != 404, role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_the_take_and_advise_routes_are_for_the_clinical_advisor_only() -> None:
    advise = _parameters(("advice", {"valueCode": "go-ahead"}))
    async with _client() as client:
        for method, path, body in (("POST", TAKE, None), ("POST", ADVISE, advise)):
            for role in Role:
                headers = {**KEY, **_bearer(role)}
                response = await client.request(
                    method,
                    path,
                    content=b"" if body is None else None,
                    json=body,
                    headers={**headers, "Content-Type": "application/json"},
                )
                if role in CLINICAL:
                    # The key is there: the route reaches its use case, which the test does not
                    # open. Anything but the route's refusal of an unknown path or a bad body.
                    assert response.status_code not in (404, 400), (path, role)
                elif role in EDGE_REFUSED:
                    assert response.status_code == 401, (path, role)
                else:
                    assert response.status_code == 404, (path, role)


async def test_the_available_count_is_for_advisors_clinicians_and_lead() -> None:
    permitted = {Role.ADVISOR, Role.CLINICAL, Role.LEAD}
    async with _client() as client:
        for role in Role:
            response = await client.get(AVAILABLE, headers=_bearer(role))
            if role in permitted:
                assert response.status_code != 404, role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_the_queue_is_for_the_clinical_advisor_only() -> None:
    async with _client() as client:
        for role in Role:
            response = await client.get(QUEUE, headers=_bearer(role))
            if role in CLINICAL:
                # Not the alert list's refusal of a code it does not take (400), and not a 404.
                assert response.status_code not in (400, 404), role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_any_signed_in_role_can_post_a_task_and_no_key_is_a_bad_request() -> None:
    async with _client() as client:
        for role in Role:
            response = await client.post(TASK, json=_safety_task(), headers=_bearer(role))
            if role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 400, role
                assert response.json()["issue"][0]["code"] == "required", role


# ----------------------------------------------------------------- refusals that need no store


async def test_a_presence_other_than_available_busy_or_away_is_refused() -> None:
    async with _client() as client:
        response = await client.put(
            PRESENCE, json={"presence": "asleep"}, headers=_bearer(Role.CLINICAL)
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["presence"]


async def test_the_queue_names_its_code_and_its_status() -> None:
    async with _client() as client:
        other_code = await client.get(
            "/fhir/Task?code=booking&status=requested", headers=_bearer(Role.CLINICAL)
        )
        other_status = await client.get(
            "/fhir/Task?code=clinical-advice&status=done", headers=_bearer(Role.CLINICAL)
        )
    assert other_code.status_code == 400
    assert other_code.json()["issue"][0]["expression"] == ["code"]
    assert other_status.status_code == 400
    assert other_status.json()["issue"][0]["expression"] == ["status"]


async def test_advice_with_a_note_over_280_characters_is_refused_and_not_echoed() -> None:
    too_long = "x" * (NOTE_LIMIT + 1)
    body = _parameters(("advice", {"valueCode": "go-ahead"}), ("note", {"valueString": too_long}))
    async with _client() as client:
        response = await client.post(ADVISE, json=body, headers={**KEY, **_bearer(Role.CLINICAL)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["note"]
    assert too_long not in response.text


async def test_advice_names_a_known_advice_choice() -> None:
    body = _parameters(("advice", {"valueCode": "discharge-them"}))
    async with _client() as client:
        response = await client.post(ADVISE, json=body, headers={**KEY, **_bearer(Role.CLINICAL)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["advice"]


async def test_a_clinical_request_names_a_known_urgency() -> None:
    task = _clinical_task(
        extension=[
            {"url": _input_url("urgency"), "valueCode": "whenever"},
            {"url": _input_url("why"), "valueCode": "other"},
        ]
    )
    async with _client() as client:
        response = await client.post(TASK, json=task, headers={**KEY, **_bearer(Role.ADVISOR)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["urgency"]


async def test_a_clinical_request_needs_its_case() -> None:
    task = _clinical_task()
    del task["focus"]
    async with _client() as client:
        response = await client.post(TASK, json=task, headers={**KEY, **_bearer(Role.ADVISOR)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["case"]


async def test_a_safety_concern_needs_its_text() -> None:
    task = _safety_task()
    task["extension"] = [e for e in task["extension"] if e["url"] != _input_url("text")]
    async with _client() as client:
        response = await client.post(TASK, json=task, headers={**KEY, **_bearer(Role.EXEC)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["text"]


async def test_a_safety_concern_text_over_280_characters_is_refused_and_not_echoed() -> None:
    too_long = "y" * (NOTE_LIMIT + 1)
    async with _client() as client:
        response = await client.post(
            TASK, json=_safety_task(text=too_long), headers={**KEY, **_bearer(Role.EXEC)}
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["text"]
    assert too_long not in response.text


async def test_a_safety_concern_names_a_known_category() -> None:
    task = _safety_task()
    task["extension"][0]["valueCode"] = "something-odd"
    async with _client() as client:
        response = await client.post(TASK, json=task, headers={**KEY, **_bearer(Role.EXEC)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["category"]


async def test_a_task_with_an_unknown_code_is_a_bad_request() -> None:
    task = {"resourceType": "Task", "code": {"coding": [{"code": "booking"}]}}
    async with _client() as client:
        response = await client.post(TASK, json=task, headers={**KEY, **_bearer(Role.ADVISOR)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["code"]
