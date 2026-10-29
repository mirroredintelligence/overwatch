"""Wall screen pairing over HTTP (R15), on the harness Neo4j with the real U10 use cases.

Clock: Friday 23 October 2026, 14:02 London (13:02Z), the time the prompt names. The run tenant is
the one the host `HOST_A` names; a second tenant owns `HOST_B`. Each test starts from a clean graph
and an empty in-memory cache. Synthetic values only: no patient data.

What a test asserts is what the endpoint answered and what was really stored, read back through the
graph (DEC-004). The code, the screen secret and the device token are never printed or logged by the
route; the log test checks that across a whole pairing.
"""

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Role
from diucs.domain.model.tenant import TenantStatus
from tests.integration.adapters.inbound.link_pages.conftest import seed_tenant_host
from tests.support.link_rig import HOST_A, HOST_B
from tests.support.neo4j import ThrowawayNeo4j, count_nodes, node_props
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

START = "/screens/pairing"
SCREENS = "/screens"
SECRET_HEADER = "X-Screen-Secret"
REFUSED = "That code is not valid or has expired."
NOT_FOUND = "The requested resource was not found."
LINK_SECRET = b"screen-test-link-secret-for-the-pairing-tests"
DEVICE_SECRET = b"screen-test-device-secret-for-the-pairing-tests"
JSON = {"Content-Type": "application/json"}
START_AT = datetime(2026, 10, 23, 13, 2, tzinfo=UTC)
WALL_NAME = "Ward A wall"


class FlakyCache(InMemoryCache):
    """An in-memory cache that refuses the named operations while they are in `down`: the stand-in
    for a Redis outage at one step."""

    def __init__(self, clock: FixedClock) -> None:
        super().__init__(clock)
        self.down: set[str] = set()

    async def set_if_absent(self, key: str, value: str, ttl: timedelta) -> bool:
        if "set_if_absent" in self.down:
            raise ConnectionError("cache is down")
        return await super().set_if_absent(key, value, ttl)

    async def delete(self, key: str) -> None:
        if "delete" in self.down:
            raise ConnectionError("cache is down")
        await super().delete(key)


def screen_secrets() -> FixedSecretStore:
    return FixedSecretStore({LINK_TOKEN_SECRET: LINK_SECRET, DEVICE_TOKEN_SECRET: DEVICE_SECRET})


def lead_headers(key: str = "key-1") -> dict[str, str]:
    token = issue_test_token(Role.LEAD, (), "prac-lead-1")
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


def advisor_headers() -> dict[str, str]:
    token = issue_test_token(Role.ADVISOR, (), "prac-advisor-1")
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": "key-advisor"}


def spaced(code: str) -> str:
    return f"{code[:3]} {code[3:]}"


def refusal(response: Response) -> None:
    assert response.status_code == 404
    assert response.json()["issue"][0]["diagnostics"] == REFUSED


async def start(client: AsyncClient) -> dict[str, Any]:
    response = await client.post(START, json={})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def claim(client: AsyncClient, pairing_id: str, secret: str) -> Response:
    return await client.get(f"{START}/{pairing_id}", headers={SECRET_HEADER: secret})


async def connect(
    client: AsyncClient, code: str, headers: dict[str, str] | None = None, **extra: Any
) -> Response:
    body = {"code": code, "name": WALL_NAME, "location": "Ward A", **extra}
    return await client.post(SCREENS, json=body, headers=headers or lead_headers())


@pytest.fixture
def screen_clock() -> FixedClock:
    return FixedClock(START_AT)


@pytest.fixture
def flaky_cache(screen_clock: FixedClock) -> FlakyCache:
    return FlakyCache(screen_clock)


@pytest_asyncio.fixture(loop_scope="session")
async def screens_container(
    harness_container: ThrowawayNeo4j,
    clean_graph: None,
    screen_clock: FixedClock,
    flaky_cache: FlakyCache,
) -> AsyncIterator[Container]:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=screen_clock,
            ids=SequentialIds(),
            neo4j=connection,
            secrets=screen_secrets(),
            cache=flaky_cache,
        )
    finally:
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def screens_app(screens_container: Container) -> FastAPI:
    app = create_app(screens_container)
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    return app


@pytest_asyncio.fixture(loop_scope="session")
async def hosts(neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str) -> None:
    await seed_tenant_host(neo4j_driver, tenant_id, HOST_A)
    await seed_tenant_host(neo4j_driver, other_tenant_id, HOST_B)


def client_for(app: FastAPI, host: str = HOST_A) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url=f"https://{host}",
    )


@pytest_asyncio.fixture(loop_scope="session")
async def screens(screens_app: FastAPI, hosts: None) -> AsyncIterator[AsyncClient]:
    async with client_for(screens_app) as client:
        yield client


@pytest_asyncio.fixture(loop_scope="session")
async def other_screens(screens_app: FastAPI, hosts: None) -> AsyncIterator[AsyncClient]:
    async with client_for(screens_app, HOST_B) as client:
        yield client


async def test_start_gives_a_six_digit_code_that_lapses_in_ten_minutes(
    screens: AsyncClient, screen_clock: FixedClock
) -> None:
    response = await screens.post(START, json={})
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"pairingId", "code", "expiresAt", "screenSecret"}
    assert re.fullmatch(r"[0-9]{6}", body["code"])
    assert datetime.fromisoformat(body["expiresAt"]) == screen_clock.now() + timedelta(minutes=10)
    assert body["screenSecret"]


async def test_a_claim_before_a_lead_connects_is_waiting_and_has_no_token(
    screens: AsyncClient,
) -> None:
    started = await start(screens)
    response = await claim(screens, started["pairingId"], started["screenSecret"])
    assert response.status_code == 200
    assert response.json() == {"status": "waiting"}


async def test_a_lead_connects_the_screen_and_the_display_gets_its_token_once(
    screens: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    started = await start(screens)
    connected = await connect(screens, spaced(started["code"]))
    assert connected.status_code == 201
    device = connected.json()
    assert device["status"] == "online"
    assert device["name"] == WALL_NAME
    assert set(device) == {"deviceId", "name", "status"}

    first = (await claim(screens, started["pairingId"], started["screenSecret"])).json()
    assert first["status"] == "paired"
    token = first["deviceToken"]
    assert isinstance(token, str) and token

    second = await claim(screens, started["pairingId"], started["screenSecret"])
    assert second.json() == {"status": "paired"}

    stored = await node_props(neo4j_driver, "Device", id=device["deviceId"])
    assert stored["status"] == "active"
    assert token not in stored.values()


async def test_a_wrong_screen_secret_is_the_same_not_found(screens: AsyncClient) -> None:
    started = await start(screens)
    refusal(await claim(screens, started["pairingId"], "A" * 23))


async def test_a_claim_with_no_secret_header_is_refused_the_same_way(
    screens: AsyncClient,
) -> None:
    started = await start(screens)
    refusal(await screens.get(f"{START}/{started['pairingId']}"))


async def test_a_wrong_code_and_an_expired_code_give_the_same_answer(
    screens: AsyncClient, screen_clock: FixedClock
) -> None:
    started = await start(screens)
    wrong = f"{(int(started['code']) + 1) % 1_000_000:06d}"
    wrong_answer = await connect(screens, wrong)
    refusal(wrong_answer)

    expired = await start(screens)
    screen_clock.advance(timedelta(minutes=11))
    expired_answer = await connect(screens, expired["code"])
    refusal(expired_answer)
    assert expired_answer.json() == wrong_answer.json()


async def test_an_advisor_cannot_connect_a_screen_and_nothing_is_stored(
    screens: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    started = await start(screens)
    before = await count_nodes(neo4j_driver, "Device")
    response = await connect(screens, spaced(started["code"]), advisor_headers())
    assert response.status_code == 404
    assert await count_nodes(neo4j_driver, "Device") == before
    # The code is still live: a lead can connect it after the refusal.
    assert (await connect(screens, spaced(started["code"]))).status_code == 201


async def test_a_screen_that_no_lead_connects_in_ten_minutes_has_expired(
    screens: AsyncClient, screen_clock: FixedClock
) -> None:
    started = await start(screens)
    screen_clock.advance(timedelta(minutes=10))
    response = await claim(screens, started["pairingId"], started["screenSecret"])
    assert response.json() == {"status": "expired"}


async def test_a_connect_without_an_idempotency_key_is_a_bad_request(
    screens: AsyncClient,
) -> None:
    started = await start(screens)
    headers = {k: v for k, v in lead_headers().items() if k != "Idempotency-Key"}
    response = await connect(screens, spaced(started["code"]), headers)
    assert response.status_code == 400


async def test_a_body_that_names_a_tenant_or_a_bad_board_scope_is_refused(
    screens: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    started = await start(screens)
    tenanted = await connect(screens, spaced(started["code"]), tenantId="someone-else")
    assert tenanted.status_code == 400
    scoped = await connect(screens, spaced(started["code"]), boardScope="everyone")
    assert scoped.status_code == 400
    assert await count_nodes(neo4j_driver, "Device") == 0


async def test_a_network_board_scope_is_stored(
    screens: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    started = await start(screens)
    response = await connect(screens, spaced(started["code"]), boardScope="network")
    assert response.status_code == 201
    stored = await node_props(neo4j_driver, "Device", id=response.json()["deviceId"])
    assert stored["boardScope"] == "network"


async def owner_starts(app: FastAPI) -> None:
    """A positive control: the run's own host starts a pairing. Every refusal below is checked
    against this, so it cannot pass because no route exists (the framework's own 404)."""
    async with client_for(app) as owner:
        await start(owner)


@pytest.mark.no_tenant
async def test_a_host_no_tenant_owns_is_not_found_and_nothing_is_written(
    neo4j_driver: AsyncDriver, screens_app: FastAPI, hosts: None
) -> None:
    await owner_starts(screens_app)
    before = await count_nodes(neo4j_driver, "LinkToken")
    async with client_for(screens_app, "nobody.example.org") as stranger:
        response = await stranger.post(START, json={})
    assert response.status_code == 404
    assert response.json()["issue"][0]["diagnostics"] == NOT_FOUND
    assert await count_nodes(neo4j_driver, "LinkToken") == before


@pytest.mark.no_tenant
async def test_a_suspended_tenant_cannot_start_a_pairing(
    neo4j_driver: AsyncDriver, screens_app: FastAPI, hosts: None
) -> None:
    await owner_starts(screens_app)
    await seed_tenant_host(
        neo4j_driver, "suspended-tenant", "suspended.example.org", TenantStatus.SUSPENDED
    )
    before = await count_nodes(neo4j_driver, "LinkToken")
    async with client_for(screens_app, "suspended.example.org") as client:
        response = await client.post(START, json={})
    assert response.status_code == 404
    assert await count_nodes(neo4j_driver, "LinkToken") == before


@pytest.mark.no_tenant
async def test_a_damaged_tenant_record_is_refused_not_guessed(
    neo4j_driver: AsyncDriver, screens_app: FastAPI, hosts: None
) -> None:
    await owner_starts(screens_app)
    await seed_tenant_host(
        neo4j_driver, "damaged-tenant", "damaged.example.org", damage={"status": "bogus"}
    )
    before = await count_nodes(neo4j_driver, "LinkToken")
    async with client_for(screens_app, "damaged.example.org") as client:
        response = await client.post(START, json={})
    assert response.status_code == 404
    assert await count_nodes(neo4j_driver, "LinkToken") == before


async def test_a_second_tenant_cannot_connect_or_claim_another_tenants_screen(
    screens: AsyncClient,
    other_screens: AsyncClient,
    other_tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    started = await start(screens)
    with as_tenant(other_tenant_id):
        refusal(await connect(screens, spaced(started["code"])))
    refusal(await claim(other_screens, started["pairingId"], started["screenSecret"]))

    connected = await connect(screens, spaced(started["code"]))
    assert connected.status_code == 201
    assert await count_nodes(neo4j_driver, "Device") == 1


@pytest.mark.no_tenant
async def test_a_connect_with_no_tenant_bound_fails_closed(
    screens: AsyncClient, neo4j_driver: AsyncDriver
) -> None:
    started = await start(screens)
    response = await connect(screens, spaced(started["code"]))
    assert response.status_code == 500
    assert await count_nodes(neo4j_driver, "Device") == 0


async def test_missing_pairing_secrets_fail_closed_before_anything_is_written(
    screens_container: Container, neo4j_driver: AsyncDriver
) -> None:
    unconfigured = replace(screens_container, secrets=FixedSecretStore({}))
    app = create_app(unconfigured)
    app.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    async with client_for(app) as client:
        response = await client.post(START, json={})
    assert response.status_code == 500
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


async def test_a_start_from_one_address_is_throttled_after_twenty(
    screens: AsyncClient,
) -> None:
    for _ in range(20):
        await start(screens)
    response = await screens.post(START, json={})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "600"
    assert response.json()["issue"][0]["code"] == "throttled"


async def test_polling_while_waiting_is_never_throttled(screens: AsyncClient) -> None:
    started = await start(screens)
    for _ in range(25):
        response = await claim(screens, started["pairingId"], started["screenSecret"])
        assert response.json() == {"status": "waiting"}


async def test_refused_claims_from_one_address_are_throttled_until_the_window_passes(
    screens: AsyncClient, screen_clock: FixedClock
) -> None:
    started = await start(screens)
    for _ in range(20):
        refusal(await claim(screens, started["pairingId"], "B" * 23))
    throttled = await claim(screens, started["pairingId"], started["screenSecret"])
    assert throttled.status_code == 429
    screen_clock.advance(timedelta(minutes=10))
    back = await claim(screens, started["pairingId"], started["screenSecret"])
    assert back.status_code == 200
    assert back.json() == {"status": "expired"}


async def test_a_lead_who_fails_five_codes_is_throttled_even_with_the_right_one(
    screens: AsyncClient,
) -> None:
    started = await start(screens)
    for _ in range(5):
        refusal(await connect(screens, "000000"))
    throttled = await connect(screens, spaced(started["code"]))
    assert throttled.status_code == 429
    assert throttled.json()["issue"][0]["code"] == "throttled"


async def test_a_cache_that_is_down_refuses_a_start_and_writes_nothing(
    screens: AsyncClient, flaky_cache: FlakyCache, neo4j_driver: AsyncDriver
) -> None:
    flaky_cache.down.add("set_if_absent")
    response = await screens.post(START, json={})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


async def test_a_cache_that_is_down_when_a_lead_connects_writes_nothing_and_the_code_still_works(
    screens: AsyncClient, flaky_cache: FlakyCache, neo4j_driver: AsyncDriver
) -> None:
    started = await start(screens)
    flaky_cache.down.add("delete")
    response = await connect(screens, spaced(started["code"]))
    assert response.status_code == 503
    assert await count_nodes(neo4j_driver, "Device") == 0

    flaky_cache.down.clear()
    retried = await connect(screens, spaced(started["code"]), lead_headers("key-retry"))
    assert retried.status_code == 201


async def test_a_cache_that_is_down_when_the_display_claims_issues_no_token(
    screens: AsyncClient, flaky_cache: FlakyCache, neo4j_driver: AsyncDriver
) -> None:
    started = await start(screens)
    assert (await connect(screens, spaced(started["code"]))).status_code == 201
    flaky_cache.down.add("set_if_absent")
    response = await claim(screens, started["pairingId"], started["screenSecret"])
    assert response.status_code == 503
    assert "deviceToken" not in response.text

    flaky_cache.down.clear()
    answered = await claim(screens, started["pairingId"], started["screenSecret"])
    assert answered.json()["status"] == "paired"
    assert answered.json()["deviceToken"]


async def test_a_claim_keeps_its_token_when_only_the_slot_release_fails(
    screens: AsyncClient, flaky_cache: FlakyCache
) -> None:
    started = await start(screens)
    assert (await connect(screens, spaced(started["code"]))).status_code == 201
    flaky_cache.down.add("delete")
    response = await claim(screens, started["pairingId"], started["screenSecret"])
    assert response.status_code == 200
    assert response.json()["deviceToken"]


async def test_nothing_the_pairing_routes_handle_is_logged_by_the_application(
    screens: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    started = await start(screens)
    code = started["code"]
    secret = started["screenSecret"]
    await connect(screens, spaced(code))
    token = (await claim(screens, started["pairingId"], secret)).json()["deviceToken"]
    await connect(screens, "111111")
    await claim(screens, started["pairingId"], "C" * 23)
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("diucs"))
    for value in (code, spaced(code), secret, token):
        assert value not in logged
