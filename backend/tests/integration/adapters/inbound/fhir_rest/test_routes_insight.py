"""`POST /telemetry/ui` and `GET /support/insight/{tab}` (W9F) against real Neo4j through the API
client. Two tenants: each counts its own browsers and reads its own numbers. A group under ten
sessions never leaves the route. Sample values only: a session id is hex, an element id a code.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET
from diucs.bootstrap.container import build_for_tests
from diucs.domain.codes import Role
from diucs.domain.rules.browser_insight import MARKER_SECRET
from tests.support.api import R01_TEST_NOW, seed_edge_tenants, token_headers
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.tenancy import RunIdentity
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")


def session_id(index: int) -> str:
    return f"{index:016x}"


def ui(name: str, session: str, **attributes: Any) -> dict[str, Any]:
    common = {
        "session.id": session,
        "release": "1.4.2",
        "device.type": "desktop",
        "app.mode": "browser",
    }
    return {"name": name, "attributes": {**common, **attributes}}


async def _build(
    harness_container: ThrowawayNeo4j,
    neo4j_driver: AsyncDriver,
    run: RunIdentity,
    secrets: dict[str, bytes],
) -> AsyncIterator[Any]:
    await seed_edge_tenants(neo4j_driver, run.tenant_id, run.other_tenant_id)
    await ensure_audit_heads(neo4j_driver, run.tenant_id, run.other_tenant_id)
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        container = build_for_tests(
            clock=FixedClock(R01_TEST_NOW),
            neo4j=connection,
            secrets=FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET, **secrets}),
        )
        app = create_app(container)
        app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
        app.state.cache = InMemoryCache(container.clock)
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as http:
            yield http
    finally:
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def client(
    harness_container: ThrowawayNeo4j,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    run_identity: RunIdentity,
) -> AsyncIterator[AsyncClient]:
    async for http in _build(
        harness_container,
        neo4j_driver,
        run_identity,
        {MARKER_SECRET: b"test-only-telemetry-marker-secret-0123"},
    ):
        yield http


@pytest_asyncio.fixture(loop_scope="session")
async def client_without_secret(
    harness_container: ThrowawayNeo4j,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    run_identity: RunIdentity,
) -> AsyncIterator[AsyncClient]:
    async for http in _build(harness_container, neo4j_driver, run_identity, {}):
        yield http


async def _send(client: AsyncClient, tenant: str, events: list[dict[str, Any]]) -> Any:
    return await client.post(
        "/telemetry/ui",
        json={"events": events},
        headers=token_headers(tenant, Role.ADVISOR),
    )


async def _read(client: AsyncClient, tenant: str, tab: str, query: str = "range=7d") -> Any:
    return await client.get(
        f"/support/insight/{tab}?{query}", headers=token_headers(tenant, Role.SUPPORT)
    )


async def test_twelve_sessions_on_a_route_show_it_and_the_answer_names_no_session(
    client: AsyncClient, run_identity: RunIdentity
) -> None:
    for index in range(1, 13):
        sent = await _send(
            client,
            run_identity.tenant_id,
            [ui("ui.page_view", session_id(index), **{"page.route": "/advisor/board"})],
        )
        assert sent.status_code == 200, sent.text
        assert sent.json() == {"accepted": 1, "dropped": 0}

    response = await _read(client, run_identity.tenant_id, "paths")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["mostCommon"] == [
        {"route": "/advisor/board", "sessions": 12, "medianSeconds": None, "suppressed": False}
    ]
    assert session_id(1) not in response.text


async def test_nine_sessions_are_not_shown(client: AsyncClient, run_identity: RunIdentity) -> None:
    for index in range(1, 10):
        await _send(
            client,
            run_identity.tenant_id,
            [ui("ui.page_view", session_id(index), **{"page.route": "/advisor/board"})],
        )

    body = (await _read(client, run_identity.tenant_id, "paths")).json()

    assert body["mostCommon"] == [
        {"route": "/advisor/board", "sessions": None, "medianSeconds": None, "suppressed": True}
    ]


async def test_each_tenant_counts_and_reads_only_its_own_browsers(
    client: AsyncClient, run_identity: RunIdentity
) -> None:
    for index in range(1, 13):
        await _send(
            client,
            run_identity.tenant_id,
            [ui("ui.page_view", session_id(index), **{"page.route": "/mine-only"})],
        )
        await _send(
            client,
            run_identity.other_tenant_id,
            [ui("ui.page_view", session_id(index), **{"page.route": "/theirs-only"})],
        )

    mine = (await _read(client, run_identity.tenant_id, "paths")).json()
    theirs = (await _read(client, run_identity.other_tenant_id, "paths")).json()

    assert [row["route"] for row in mine["mostCommon"]] == ["/mine-only"]
    assert [row["route"] for row in theirs["mostCommon"]] == ["/theirs-only"]
    assert (await _read(client, run_identity.tenant_id, "paths")).text.count("theirs-only") == 0


async def test_every_tab_answers_with_its_own_shape_on_an_empty_tenant(
    client: AsyncClient, run_identity: RunIdentity
) -> None:
    shapes = {
        "funnels": {"tab", "range", "device", "funnels"},
        "paths": {"tab", "range", "device", "mostCommon", "uTurns", "unused"},
        "friction": {"tab", "range", "device", "rows", "suppressedGroups"},
        "performance": {
            "tab",
            "range",
            "device",
            "vitals",
            "slowestRoutes",
            "slowestQueries",
            "promptToBoard",
        },
        "releases": {"tab", "range", "compare", "measures", "pipeline"},
    }
    for tab, keys in shapes.items():
        response = await _read(client, run_identity.tenant_id, tab, "range=24h&device=phone")
        assert response.status_code == 200, (tab, response.text)
        assert set(response.json()) == keys, tab
        assert response.json()["tab"] == tab


async def test_the_funnels_list_each_browser_funnel_with_hidden_steps_when_there_is_no_data(
    client: AsyncClient, run_identity: RunIdentity
) -> None:
    body = (await _read(client, run_identity.tenant_id, "funnels")).json()

    names = [funnel["name"] for funnel in body["funnels"]]
    assert names == [
        "reporter-set-up",
        "daily-capacity-loop",
        "advisor-call",
        "registration",
        "criteria-review",
    ]
    assert all(step["suppressed"] for funnel in body["funnels"] for step in funnel["steps"])


@pytest.mark.parametrize("role", [Role.LEAD, Role.ADVISOR, Role.EXEC, Role.OWNER, Role.AUDIT])
async def test_other_roles_read_the_same_404_as_an_unknown_route(
    client: AsyncClient, run_identity: RunIdentity, role: Role
) -> None:
    response = await client.get(
        "/support/insight/paths?range=7d", headers=token_headers(run_identity.tenant_id, role)
    )

    assert response.status_code == 404


async def test_a_signed_out_request_is_refused(client: AsyncClient) -> None:
    sent = await client.post("/telemetry/ui", json={"events": []})
    read = await client.get("/support/insight/paths?range=7d")

    assert sent.status_code == 401
    assert read.status_code == 401


async def test_without_the_marker_secret_events_are_refused_not_dropped(
    client_without_secret: AsyncClient, run_identity: RunIdentity
) -> None:
    response = await _send(
        client_without_secret,
        run_identity.tenant_id,
        [ui("ui.click", session_id(1), **{"element.id": "ADV-X-BTN"})],
    )

    assert response.status_code == 503
