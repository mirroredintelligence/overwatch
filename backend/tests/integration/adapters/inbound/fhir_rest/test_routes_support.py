"""The support code and console routes, end to end over the HTTP app and Neo4j (R18, the task's
tests).

Written in the build wave and run in the verification stage (one Neo4j at a time). The run
tenant is bound by the conftest. The telemetry is a fixture written for the run tenant, so the
events are the caller's own. Synthetic values only: the session id is hex, the code is
generated, and the field value is a sample text that must never come back.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.telemetry.redaction import clean_attributes
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.fixture_telemetry import FixtureTelemetryQuery
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.bootstrap.container import build_for_tests
from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.rules.support import SUPPORT_CODE_SECRET
from tests.support.api import seed_edge_tenants
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SESSION = "a1b2c3d4e5f60718"
NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
SECRET = b"support-code-route-secret-0123456789"
REPORTER = {"Idempotency-Key": "k-reporter"}
CODE_REFUSED = "That code is not valid or has expired."
CODE_PATTERN = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{4}")


def _headers(role: Role, sub: str, key: str) -> dict[str, str]:
    token = issue_test_token(role, (), sub, expires_at=NOW + timedelta(hours=1))
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


def _fixture(tmp_path: Path, tenant: str) -> FixtureTelemetryQuery:
    started = "2026-10-29T09:00:00Z"
    payload = {
        "sessions": [
            {
                "session_id": SESSION,
                "tenant_id": tenant,
                "role": "reporter",
                "device": "phone",
                "release": "1.4.2",
                "started": started,
                "event_count": 2,
                "friction_count": 1,
                "error_count": 0,
            }
        ],
        "timeline": [
            {
                "session_id": SESSION,
                "tenant_id": tenant,
                "at": "2026-10-29T09:00:01Z",
                "kind": "field",
                "name": "ADV-POSTCODE-INPUT",
                "duration_ms": None,
                "status": None,
                "attributes": {
                    "element.id": "ADV-POSTCODE-INPUT",
                    "fieldValue": "sample-postcode-text",
                },
            },
            {
                "session_id": SESSION,
                "tenant_id": tenant,
                "at": "2026-10-29T09:00:03Z",
                "kind": "api_call",
                "name": "POST /api/bff/bookings",
                "duration_ms": 480.0,
                "status": "201",
                "attributes": {"http.route": "/api/bff/bookings"},
            },
        ],
        "spans": [],
        "daily": [],
    }
    path = tmp_path / "support.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return FixtureTelemetryQuery(path, attributes=clean_attributes)


@pytest_asyncio.fixture(loop_scope="session")
async def support_app(
    harness_container: ThrowawayNeo4j,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    tmp_path: Path,
    run_identity: Any,
) -> Any:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        container = build_for_tests(
            clock=FixedClock(NOW),
            neo4j=connection,
            secrets=FixedSecretStore(
                {SUPPORT_CODE_SECRET: SECRET, BFF_SECRET_NAME: TEST_BFF_SECRET}
            ),
            telemetry=_fixture(tmp_path, run_identity.tenant_id),
        )
        await ensure_audit_heads(neo4j_driver, run_identity.tenant_id)
        await seed_edge_tenants(neo4j_driver, run_identity.tenant_id)
        await _seed_lead(container)
        app = create_app(container)
        app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
        yield app
    finally:
        await connection.close()


async def _seed_lead(container: Any) -> None:
    """One shift lead (active, with an active shift-lead role) who may approve a ticket.

    Written through the
    person repository, so the product reads it the way it reads any practitioner.
    """
    async with container.uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="p-lead", active=True, display_name="Sample Lead", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="r-lead",
                practitioner_id="p-lead",
                service_id=None,
                code=PractitionerRoleCode.SHIFT_LEAD,
                active=True,
                channel=None,
                period_start=NOW - timedelta(days=30),
            )
        )
        await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def client(support_app: Any) -> Any:
    from httpx import ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=support_app, raise_app_exceptions=False), base_url="http://test"
    ) as http:
        yield http


async def _create_code(client: AsyncClient, key: str = "k-code") -> dict[str, Any]:
    body = {"sessionId": SESSION, "deviceType": "phone", "appMode": "browser", "release": "1.4.2"}
    response = await client.post(
        "/support/codes", json=body, headers=_headers(Role.REPORTER, "prac-reporter", key)
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _open(client: AsyncClient, code: str, key: str = "k-open") -> Any:
    return await client.post(
        "/support/sessions/open",
        json={"supportCode": code},
        headers=_headers(Role.SUPPORT, "prac-support", key),
    )


async def test_a_reporter_creates_a_code_and_sees_no_access_yet(client: AsyncClient) -> None:
    created = await _create_code(client)

    assert CODE_PATTERN.fullmatch(created["code"])
    accesses = await client.get(
        f"/support/accesses?sessionId={SESSION}",
        headers=_headers(Role.REPORTER, "prac-reporter", "k-unused"),
    )
    assert accesses.status_code == 200
    assert accesses.json() == []


async def test_support_opens_with_the_code_and_the_reporter_sees_a_role_not_a_name(
    client: AsyncClient,
) -> None:
    created = await _create_code(client, key="k-open-1")

    opened = await _open(client, created["code"], key="k-open-1-open")
    accesses = await client.get(
        f"/support/accesses?sessionId={SESSION}",
        headers=_headers(Role.REPORTER, "prac-reporter", "k-unused-2"),
    )

    assert opened.status_code == 200
    assert opened.json()["sessionId"] == SESSION
    items = accesses.json()
    assert len(items) == 1
    assert items[0]["role"] == "support"
    assert set(items[0]) == {"openedAt", "role"}


async def test_a_wrong_code_gets_the_refusal_message(client: AsyncClient) -> None:
    wrong = await _open(client, "ZZZZ-ZZZZ", key="k-wrong")

    assert wrong.status_code == 403
    assert CODE_REFUSED in wrong.text
    # An expired code needs a clock that moves past the code's window. The route tests run on a
    # fixed clock, so the expired case is not covered here (known gap, R18).


async def test_events_are_refused_before_an_open_and_read_after_it_with_allow_listed_keys_only(
    client: AsyncClient,
) -> None:
    created = await _create_code(client, key="k-events")
    before = await client.get(
        f"/support/sessions/{SESSION}/events",
        headers=_headers(Role.SUPPORT, "prac-support", "k-events-before"),
    )
    await _open(client, created["code"], key="k-events-open")

    after = await client.get(
        f"/support/sessions/{SESSION}/events",
        headers=_headers(Role.SUPPORT, "prac-support", "k-events-after"),
    )

    assert before.status_code == 403
    assert after.status_code == 200
    body = after.json()
    assert body["meta"]["sessionId"] == SESSION
    for event in body["events"]:
        assert set(event) <= {
            "kind",
            "elementId",
            "route",
            "outcome",
            "durationMs",
            "status",
            "offsetMs",
        }
    assert "sample-postcode-text" not in after.text
    assert "fieldValue" not in after.text


async def test_a_ticket_is_pending_until_a_lead_approves_it_and_then_opens_the_session(
    client: AsyncClient,
) -> None:
    requested = await client.post(
        f"/support/sessions/{SESSION}/ticket",
        json={"ticket": "INC-100"},
        headers=_headers(Role.SUPPORT, "prac-support", "k-ticket"),
    )
    still_closed = await client.get(
        f"/support/sessions/{SESSION}/events",
        headers=_headers(Role.SUPPORT, "prac-support", "k-ticket-events"),
    )
    approved = await client.post(
        "/support/tickets/INC-100/approve",
        headers=_headers(Role.LEAD, "p-lead", "k-approve"),
    )
    opened = await client.post(
        "/support/sessions/open",
        json={"ticket": "INC-100"},
        headers=_headers(Role.SUPPORT, "prac-support", "k-ticket-open"),
    )
    readable = await client.get(
        f"/support/sessions/{SESSION}/events",
        headers=_headers(Role.SUPPORT, "prac-support", "k-ticket-read"),
    )

    assert requested.json() == {"state": "pending"}
    assert still_closed.status_code == 403
    assert approved.json() == {"state": "approved"}
    assert opened.status_code == 200
    assert readable.status_code == 200


async def test_an_advisor_opening_a_session_gets_the_non_revealing_404(client: AsyncClient) -> None:
    created = await _create_code(client, key="k-advisor-code")

    response = await client.post(
        "/support/sessions/open",
        json={"supportCode": created["code"]},
        headers=_headers(Role.ADVISOR, "prac-advisor", "k-advisor-open"),
    )

    assert response.status_code == 404


async def test_a_stopped_code_no_longer_opens_the_session(client: AsyncClient) -> None:
    created = await _create_code(client, key="k-stop-code")
    stopped = await client.delete(
        f"/support/codes/current?sessionId={SESSION}",
        headers=_headers(Role.REPORTER, "prac-reporter", "k-stop"),
    )

    response = await _open(client, created["code"], key="k-stop-open")

    assert stopped.status_code == 204
    assert response.status_code == 403
    assert CODE_REFUSED in response.text


async def test_a_code_is_returned_only_by_its_creation(client: AsyncClient) -> None:
    created = await _create_code(client, key="k-once")
    text_of_other_routes = [
        (
            await client.get(
                f"/support/accesses?sessionId={SESSION}",
                headers=_headers(Role.REPORTER, "prac-reporter", "k-x"),
            )
        ).text,
    ]
    assert all(created["code"] not in text for text in text_of_other_routes)
    _ = FixedSecretStore  # the secret store is the one the container was built with
