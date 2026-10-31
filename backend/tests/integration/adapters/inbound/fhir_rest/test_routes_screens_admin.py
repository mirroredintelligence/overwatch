"""The lead's wall screen list and revoke, end to end on the harness Neo4j (W9I, TEN-072, TEN-043).

A screen is paired through the pairing routes, exchanges its device token for a wall token, reads
through a route a wall may reach (which marks it seen), and is then revoked by the lead. From that
moment its wall token is refused (401) by the edge, its device token gets no new wall token (404),
and the list says revoked. A second tenant holds a screen with the same id: its list never shows the
first tenant's, and the lead of one cannot revoke the other's (404, nothing changes). Clock: 30
October 2026, 10:00. Synthetic values only; no body holds a token, a hash or a secret.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, Any

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME, require_role
from diucs.adapters.inbound.fhir_rest.routes_auth import DEVICE_PATH, ExchangeDeps
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fake_identity_verifier import FakeIdentityVerifier
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET, PHONE_HASH_SECRET
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.use_cases.exchange_token import ACCOUNT_REF_SECRET
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Role
from tests.support.neo4j import ThrowawayNeo4j, write_tx
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
PLATFORM_KEY = b"synthetic-platform-key-for-the-screen-admin-it"
START = "/screens/pairing"
SCREENS = "/screens"
SECRET_WORDS = ("tokenHash", "screenSecret", "deviceToken")


def _secrets() -> FixedSecretStore:
    return FixedSecretStore(
        {
            BFF_SECRET_NAME: TEST_BFF_SECRET,
            ACCOUNT_REF_SECRET: PLATFORM_KEY,
            DEVICE_TOKEN_SECRET: PLATFORM_KEY + b"-device",
            LINK_TOKEN_SECRET: PLATFORM_KEY + b"-link",
            PHONE_HASH_SECRET: PLATFORM_KEY,
        }
    )


class _NoNetworks:
    async def networks_of_tenant(self, tenant_id: str) -> list[Any]:
        return []


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest_asyncio.fixture(loop_scope="session")
async def container(
    harness_container: ThrowawayNeo4j, clean_graph: None, clock: FixedClock
) -> AsyncIterator[Container]:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=clock,
            ids=SequentialIds(),
            neo4j=connection,
            secrets=_secrets(),
            cache=InMemoryCache(clock),
        )
    finally:
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def hosts(
    container: Container,
    neo4j_driver: AsyncDriver,
    edge_tenants: None,
    tenant_id: str,
    other_tenant_id: str,
) -> dict[str, str]:
    host_a, host_b = f"{tenant_id}.example.test", f"{other_tenant_id}.example.test"

    async def host(tenant: str, name: str) -> None:
        async def work(tx: AsyncManagedTransaction) -> None:
            await tx.run("MATCH (t:Tenant {id: $id}) SET t.host = $host", id=tenant, host=name)

        await write_tx(neo4j_driver, work)

    async def no_seeded_screens(tx: AsyncManagedTransaction) -> None:
        # The shared route-test seed gives each tenant a few active screens for wall tokens; this
        # file counts screens, so it starts with none.
        await tx.run(
            "MATCH (d:Device {tenantId: $tenant, deviceType: 'wall-display'}) DETACH DELETE d"
        )

    for tenant in (tenant_id, other_tenant_id):
        with as_tenant(tenant):
            await write_tx(neo4j_driver, no_seeded_screens)
    await host(tenant_id, host_a)
    await host(other_tenant_id, host_b)
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    return {"a": host_a, "b": host_b}


@pytest_asyncio.fixture(loop_scope="session")
async def app(container: Container, hosts: dict[str, str]) -> FastAPI:
    built = create_app(container)
    built.state.secrets = _secrets()
    built.state.cache = container.cache
    # The list asks the tenant's networks; these tests have none (the setting is W9B's own tests).
    built.state.network_services = SimpleNamespace(access=_NoNetworks())
    built.state.token_exchange = ExchangeDeps(
        verifier=FakeIdentityVerifier(), operator_directory_id=None
    )

    @built.get("/wall-probe")
    async def probe(
        _actor: Annotated[Actor, Depends(require_role(Role.WALL))],
    ) -> dict[str, bool]:
        return {"ok": True}

    return built


def _client(app: FastAPI, host: str) -> AsyncClient:
    transport = ASGITransport(app=app, client=("203.0.113.9", 4321), raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url=f"https://{host}")


def _lead(tenant: str, key: str = "key-1") -> dict[str, str]:
    token = issue_test_token(
        Role.LEAD, (), "prac-lead-1", tenant=tenant, expires_at=NOW + timedelta(hours=8)
    )
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


async def _pair(c: AsyncClient, tenant: str, name: str, key: str) -> tuple[str, str]:
    """Pair one screen on this host. Returns its id and its device token."""
    started = (await c.post(START, json={})).json()
    connected = await c.post(
        SCREENS, json={"code": started["code"], "name": name}, headers=_lead(tenant, key)
    )
    assert connected.status_code == 201, connected.text
    claimed = await c.get(
        f"{START}/{started['pairingId']}", headers={"X-Screen-Secret": started["screenSecret"]}
    )
    return connected.json()["deviceId"], claimed.json()["deviceToken"]


async def _wall_token(c: AsyncClient, device_token: str) -> str:
    response = await c.post(
        DEVICE_PATH, json={}, headers={"Authorization": f"Bearer {device_token}"}
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["token"]
    return token


async def _list(c: AsyncClient, tenant: str) -> list[dict[str, Any]]:
    response = await c.get(SCREENS, headers=_lead(tenant))
    assert response.status_code == 200, response.text
    for word in SECRET_WORDS:
        assert word not in response.text
    screens: list[dict[str, Any]] = response.json()["screens"]
    return screens


async def test_a_paired_screen_is_listed_waiting_then_offline_then_online_when_it_reads(
    app: FastAPI, hosts: dict[str, str], tenant_id: str
) -> None:
    async with _client(app, hosts["a"]) as c:
        started = (await c.post(START, json={})).json()
        await c.post(
            SCREENS, json={"code": started["code"], "name": "Ward 4"}, headers=_lead(tenant_id)
        )
        [waiting] = await _list(c, tenant_id)
        assert (waiting["state"], waiting["lastSeenAt"]) == ("waiting", None)
        assert waiting["pairedAt"] == "2026-10-30T10:00:00Z"
        assert waiting["name"] == "Ward 4"

        claimed = await c.get(
            f"{START}/{started['pairingId']}", headers={"X-Screen-Secret": started["screenSecret"]}
        )
        [collected] = await _list(c, tenant_id)
        assert (collected["state"], collected["lastSeenAt"]) == ("offline", None)

        wall = await _wall_token(c, claimed.json()["deviceToken"])
        assert (
            await c.get("/wall-probe", headers={"Authorization": f"Bearer {wall}"})
        ).status_code == 200
        [online] = await _list(c, tenant_id)
        assert online["state"] == "online"
        assert online["lastSeenAt"] == "2026-10-30T10:00:00Z"


async def test_a_revoked_screen_is_cut_off_at_once_and_listed_revoked(
    app: FastAPI, container: Container, hosts: dict[str, str], tenant_id: str
) -> None:
    async with _client(app, hosts["a"]) as c:
        device_id, device_token = await _pair(c, tenant_id, "Ward 4", "pair-1")
        wall = {"Authorization": f"Bearer {await _wall_token(c, device_token)}"}
        assert (await c.get("/wall-probe", headers=wall)).status_code == 200

        revoked = await c.post(
            f"{SCREENS}/{device_id}/revoke", json={}, headers=_lead(tenant_id, "rev-1")
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json() == {
            "deviceId": device_id,
            "status": "revoked",
            "revokedAt": "2026-10-30T10:00:00Z",
        }

        # The wall token the screen already holds is refused on its next read, not an hour later.
        assert (await c.get("/wall-probe", headers=wall)).status_code == 401
        # And the device token no longer buys a new one.
        again = await c.post(
            DEVICE_PATH, json={}, headers={"Authorization": f"Bearer {device_token}"}
        )
        assert again.status_code == 404
        [row] = await _list(c, tenant_id)
        assert (row["state"], row["revokedAt"]) == ("revoked", "2026-10-30T10:00:00Z")

        # A second revoke, with a new key, changes nothing and writes no second audit entry.
        repeat = await c.post(
            f"{SCREENS}/{device_id}/revoke", json={}, headers=_lead(tenant_id, "rev-2")
        )
        assert repeat.status_code == 200
        assert repeat.json()["revokedAt"] == "2026-10-30T10:00:00Z"

    with as_tenant(tenant_id):
        async with container.uow_factory() as uow:
            actions = [record.entry.action for record in await uow.audit.records()]
    assert actions.count("wall-screen-revoked") == 1


async def test_the_other_tenants_lead_sees_none_of_it_and_cannot_revoke_it(
    app: FastAPI, hosts: dict[str, str], tenant_id: str, other_tenant_id: str
) -> None:
    async with _client(app, hosts["a"]) as a, _client(app, hosts["b"]) as b:
        device_a, token_a = await _pair(a, tenant_id, "Ward A", "pair-a")
        device_b, _token_b = await _pair(b, other_tenant_id, "Ward B", "pair-b")

        assert [s["name"] for s in await _list(a, tenant_id)] == ["Ward A"]
        assert [s["name"] for s in await _list(b, other_tenant_id)] == ["Ward B"]

        refused = await b.post(
            f"{SCREENS}/{device_a}/revoke", json={}, headers=_lead(other_tenant_id, "cross-1")
        )
        assert refused.status_code == 404
        wall = {"Authorization": f"Bearer {await _wall_token(a, token_a)}"}
        assert (await a.get("/wall-probe", headers=wall)).status_code == 200
        assert [s["state"] for s in await _list(a, tenant_id)] != ["revoked"]

        # B's lead revokes B's own screen; A's list does not change.
        own = await b.post(
            f"{SCREENS}/{device_b}/revoke", json={}, headers=_lead(other_tenant_id, "own-1")
        )
        assert own.status_code == 200
        assert [s["state"] for s in await _list(b, other_tenant_id)] == ["revoked"]
        assert [s["state"] for s in await _list(a, tenant_id)] != ["revoked"]
        assert (await a.get("/wall-probe", headers=wall)).status_code == 200
