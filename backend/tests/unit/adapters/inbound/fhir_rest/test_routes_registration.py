"""The registration and scope-list routes (R10) in-process and with no Neo4j.

Every case here is refused before a unit of work is opened: a missing Idempotency-Key, a role the
route does not take, a body that fails its own checks. The app runs on a container whose
unit-of-work factory fails the test if it is ever called. The stored results (the scope list, the
invitation, the review, the approval) are in tests/integration/adapters/inbound/fhir_rest/
test_routes_registration.py, which is written but not run in this build.

Each permitted role is checked with a request that has no key, so the answer is the route's own
400, which an unknown path cannot give: a missing route answers 404 too, and a refused role also
gets 404. Sample values only: the names and numbers are the prompt's examples.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.routes_registration import refusal_outcome
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, default_token_tenant, issue_test_token
from diucs.application.use_cases.invite_reporter import MOBILE_MESSAGE, NOT_IN_PILOT_MESSAGE
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.rules.registration import ApprovalChecks, missing_for_approval
from tests.support.edge import active_tenants

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
SCOPE_LIST = "/fhir/List/scope-list"
SCOPE_ENTRY = "/fhir/List/scope-list/$entry"
INVITE = "/fhir/Task/$invite-reporter"
DRAFT = "/fhir/Task/reg-1/$draft"
SUBMIT = "/fhir/Task/reg-1/$submit"
CALLBACK = "/fhir/Task/reg-1/$callback"
SCOPE_DECISION = "/fhir/Task/reg-1/$scope-decision"
APPROVE = "/fhir/Task/reg-1/$approve"
SEND_BACK = "/fhir/Task/reg-1/$send-back"
NOT_APPROVE = "/fhir/Task/reg-1/$not-approve"
SET_LIVE = "/fhir/Task/reg-1/$set-live"
EDGE_REFUSED: frozenset[Role] = frozenset({Role.PLATFORM_OPERATOR})
"""A role the token edge refuses on every FHIR route: the platform operator runs tenant lifecycle
only and has no data access (DEC-134), so its token is a 401 before any route is reached."""
KEY = {"Idempotency-Key": "reg-route-key-0001"}
NOTE_LIMIT = 280
EXAMPLE_MOBILE = "07700 900123"


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


def _bearer(role: Role, sub: str = "lead-1") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_test_token(role, [], sub)}"}


def _parameters(*parts: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, **value} for name, value in parts],
    }


def _entry_body(**overrides: dict[str, Any]) -> dict[str, Any]:
    parts: dict[str, dict[str, Any]] = {
        "service": {"valueString": "Sample Community Team"},
        "category": {"valueCode": "urgent-community-response"},
        "flag": {"valueCode": "in-pilot"},
        "reason": {"valueString": ""},
    }
    parts.update(overrides)
    return _parameters(*((name, value) for name, value in parts.items()))


def _invite_body(**overrides: dict[str, Any]) -> dict[str, Any]:
    parts: dict[str, dict[str, Any]] = {
        "service": {"valueString": "svc-1"},
        "role": {"valueString": "Duty manager"},
        "mobile": {"valueString": EXAMPLE_MOBILE},
        "suggestedChannel": {"valueCode": "text"},
    }
    parts.update(overrides)
    return _parameters(*((name, value) for name, value in parts.items()))


def _organisation_draft(**values: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "name": "Sample Community Team",
        "odsCode": "X00001",
        "orgType": "NHS trust",
        "contactName": "Sample Contact",
        "contactEmail": "sample.contact@example.org",
        "contactPhone": EXAMPLE_MOBILE,
    }
    fields.update(values)
    return {"step": "organisation", "values": fields}


def _decision_parts(**overrides: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parts: dict[str, dict[str, Any]] = {
        "onDorsetPathway": {"valueCode": "yes"},
        "takesSpoaReferrals": {"valueCode": "yes"},
        "canReport": {"valueCode": "yes"},
        "categoryOnPilotList": {"valueCode": "yes"},
        "flag": {"valueCode": "in-pilot"},
        "reason": {"valueString": ""},
    }
    parts.update(overrides)
    return parts


async def _send(
    client: AsyncClient, method: str, path: str, body: Any, headers: dict[str, str]
) -> Any:
    """One request. A request with no body still declares a JSON body type: the body-type check
    of the app refuses a POST or PUT with no media type before any route runs (415)."""
    if body is None:
        return await client.request(
            method, path, content=b"", headers={**headers, "Content-Type": "application/json"}
        )
    return await client.request(method, path, json=body, headers=headers)


# ----------------------------------------------------------------- the role boundary of each route

# Route, method, body, the roles that may reach it. Every other role is refused with the same 404
# a missing record gets (DEC-086 item 5).
_KEYED_ROUTES: list[tuple[str, str, dict[str, Any] | None, frozenset[Role]]] = [
    ("POST", SCOPE_ENTRY, _entry_body(), frozenset({Role.LEAD})),
    ("POST", INVITE, _invite_body(), frozenset({Role.LEAD})),
    ("PUT", DRAFT, _organisation_draft(), frozenset({Role.REPORTER})),
    ("POST", SUBMIT, None, frozenset({Role.REPORTER})),
    (
        "POST",
        CALLBACK,
        _parameters(
            ("numberCalled", {"valueString": EXAMPLE_MOBILE}),
            ("spokeToRole", {"valueString": "Duty manager"}),
            ("result", {"valueCode": "confirmed"}),
        ),
        frozenset({Role.LEAD}),
    ),
    (
        "POST",
        SCOPE_DECISION,
        _parameters(*_decision_parts().items()),
        frozenset({Role.LEAD}),
    ),
    ("POST", APPROVE, None, frozenset({Role.LEAD})),
    (
        "POST",
        SEND_BACK,
        _parameters(("note", {"valueString": "Please add the call-back number."})),
        frozenset({Role.LEAD}),
    ),
    (
        "POST",
        NOT_APPROVE,
        _parameters(("note", {"valueString": "Not for the pilot."})),
        frozenset({Role.LEAD}),
    ),
    ("POST", SET_LIVE, None, frozenset({Role.LEAD})),
]


@pytest.mark.parametrize(("method", "path", "body", "permitted"), _KEYED_ROUTES)
async def test_each_keyed_route_takes_its_roles_and_refuses_the_rest(
    method: str, path: str, body: dict[str, Any] | None, permitted: frozenset[Role]
) -> None:
    async with _client() as client:
        for role in Role:
            response = await _send(client, method, path, body, _bearer(role))
            if role in permitted:
                # No key: the route's own refusal, before any store is touched.
                assert response.status_code == 400, role
                assert response.json()["issue"][0]["code"] == "required", role
            elif role in EDGE_REFUSED:
                assert response.status_code == 401, role
            else:
                assert response.status_code == 404, role


async def test_the_scope_list_is_for_the_lead_only() -> None:
    async with _client() as client:
        lead = await client.get(SCOPE_LIST, headers=_bearer(Role.LEAD))
        refused = {
            role: (await client.get(SCOPE_LIST, headers=_bearer(role))).status_code
            for role in Role
            if role is not Role.LEAD
        }
    # The lead reaches the list, so the route answers something other than an unknown path: the
    # shared store is not opened in this test, so the answer is the failure of the empty store.
    assert lead.status_code != 404
    for role, status in refused.items():
        assert status == (401 if role in EDGE_REFUSED else 404), role


# ---------------------------------------------------------------- refusals that need no store


async def test_a_post_without_an_idempotency_key_is_a_bad_request() -> None:
    async with _client() as client:
        response = await client.post(INVITE, json=_invite_body(), headers=_bearer(Role.LEAD))
    assert response.status_code == 400
    assert response.json()["issue"][0]["code"] == "required"


async def test_a_scope_entry_flag_must_be_a_scope_flag() -> None:
    async with _client() as client:
        response = await client.post(
            SCOPE_ENTRY,
            json=_entry_body(flag={"valueCode": "maybe"}),
            headers={**KEY, **_bearer(Role.LEAD)},
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["flag"]


async def test_a_scope_entry_needs_a_category() -> None:
    body = _parameters(
        ("service", {"valueString": "Sample Community Team"}),
        ("flag", {"valueCode": "in-pilot"}),
    )
    async with _client() as client:
        response = await client.post(SCOPE_ENTRY, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["category"]


async def test_an_invitation_names_a_known_channel() -> None:
    async with _client() as client:
        response = await client.post(
            INVITE,
            json=_invite_body(suggestedChannel={"valueCode": "fax"}),
            headers={**KEY, **_bearer(Role.LEAD)},
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["suggestedChannel"]


async def test_a_bad_mobile_is_refused_with_the_example_and_without_the_number() -> None:
    typed = "07700 900 999x"
    async with _client() as client:
        response = await client.post(
            INVITE,
            json=_invite_body(mobile={"valueString": typed}),
            headers={**KEY, **_bearer(Role.LEAD)},
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["diagnostics"] == MOBILE_MESSAGE
    assert typed not in response.text


async def test_a_draft_organisation_without_an_ods_code_fails_on_that_field() -> None:
    draft = _organisation_draft()
    del draft["values"]["odsCode"]
    async with _client() as client:
        response = await client.put(DRAFT, json=draft, headers={**KEY, **_bearer(Role.REPORTER)})
    assert response.status_code == 400
    issues = response.json()["issue"]
    assert [issue["expression"] for issue in issues] == [["odsCode"]]


async def test_a_send_back_note_over_280_characters_is_refused() -> None:
    too_long = "x" * (NOTE_LIMIT + 1)
    body = _parameters(("note", {"valueString": too_long}))
    async with _client() as client:
        response = await client.post(SEND_BACK, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["note"]
    assert too_long not in response.text


async def test_a_scope_decision_needs_all_four_answers() -> None:
    parts = _decision_parts()
    del parts["canReport"]
    async with _client() as client:
        response = await client.post(
            SCOPE_DECISION,
            json=_parameters(*parts.items()),
            headers={**KEY, **_bearer(Role.LEAD)},
        )
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["canReport"]


async def test_a_call_back_result_must_be_a_known_result() -> None:
    body = _parameters(
        ("numberCalled", {"valueString": EXAMPLE_MOBILE}),
        ("spokeToRole", {"valueString": "Duty manager"}),
        ("result", {"valueCode": "probably"}),
    )
    async with _client() as client:
        response = await client.post(CALLBACK, json=body, headers={**KEY, **_bearer(Role.LEAD)})
    assert response.status_code == 400
    assert response.json()["issue"][0]["expression"] == ["result"]


# ------------------------------------------------------------- the two business-rule conflicts


def test_an_approval_missing_its_checks_is_a_business_rule_conflict_with_the_missing_names() -> (
    None
):
    checks = ApprovalChecks(
        automatic_ok=True, callback_confirmed=False, scope=None, criteria_approved=False
    )
    missing = missing_for_approval(checks)
    error = NotAllowed("Approve is unavailable until: " + "; ".join(missing))

    response = refusal_outcome(error)

    assert response is not None
    assert response.status_code == 409
    text = response.body.decode()
    assert "business-rule" in text
    assert "Call-back done" in text


def test_a_role_refusal_of_approval_stays_a_not_found() -> None:
    # Only the approval-blocked message is a 409: any other NotAllowed is the role's 404.
    assert refusal_outcome(NotAllowed("only the shift lead may review a registration")) is None


def test_an_invitation_for_a_service_not_in_pilot_is_a_business_rule_conflict() -> None:
    response = refusal_outcome(NotAllowed(NOT_IN_PILOT_MESSAGE))

    assert response is not None
    assert response.status_code == 409
    assert "business-rule" in response.body.decode()
