"""The API boots from its own composition (B1, N3): the real app, built the way the serving process
builds it, on the shared Neo4j, with two tenants that have a host each.

What is proved, end to end through the real edge, the real routes and the real stores (the identity
verifier, the secret store and the bus are fakes of external providers):

- the health route answers and the public profile of each tenant is served on that tenant's host;
- a request that comes through Cloudflare (a peer inside its published ranges, with the visitor
  address and the original host in the edge's headers) is served for the host the edge names, and
  the same headers from any other peer are ignored, so a forged host reaches no tenant;
- the token exchange issues a tenant-bound token and one authenticated route and the network read
  route (`app.state.network_services`) accept it; a request with no token is refused;
- the exchange's address limit counts the visitor, not the proxy that carried it;
- the Twilio webhook and the link pages are wired (they answer as themselves, never as an
  unconfigured server's 500).

Synthetic values only: sample hosts, a made-up Entra directory, no real number.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_config_repository import (
    Neo4jTenantConfigRepository,
)
from diucs.adapters.testing.fake_identity_verifier import FakeIdentityVerifier
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.identity_verifier import Audience, VerifiedIdentity
from diucs.bootstrap.api_main import REQUIRED_SECRETS, ApiParts, build_api
from diucs.bootstrap.container import Container, build_for_tests
from diucs.bootstrap.settings import Settings
from diucs.domain.codes import Role
from diucs.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
)
from diucs.domain.rules.bff_token import decode_bff_token
from tests.support.api import seed_edge_tenants
from tests.support.neo4j import ThrowawayNeo4j, write_tx
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
SECRET = b"synthetic-secret-for-the-api-boot-test-0123456789ab"
D_A = "11111111-1111-4111-8111-111111111111"
D_B = "22222222-2222-4222-8222-222222222222"
OID = "33333333-3333-4333-8333-333333333333"
G_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
G_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
CLOUDFLARE_PEER = "173.245.48.10"
OTHER_PEER = "203.0.113.9"
VISITOR = "198.51.100.77"
OTHER_VISITOR = "198.51.100.78"
BOARD = "/fhir/HealthcareService/$board"


@pytest_asyncio.fixture(loop_scope="session")
async def container(
    harness_container: ThrowawayNeo4j, clean_graph: None
) -> AsyncIterator[Container]:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(NOW),
            ids=SequentialIds(),
            neo4j=connection,
            secrets=FixedSecretStore({name: SECRET for name in REQUIRED_SECRETS}),
        )
    finally:
        await connection.close()


async def _tenant(driver: AsyncDriver, tenant: str, host: str, name: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "MATCH (t:Tenant {id: $id}) SET t.host = $host, t.displayName = $name",
            id=tenant,
            host=host,
            name=name,
        )

    await write_tx(driver, work)


async def _configure(driver: AsyncDriver, tenant: str, directory: str, group: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jTenantConfigRepository(tx)  # type: ignore[arg-type]
        await repo.put_binding(
            EntraBinding(
                directory_id=directory,
                status=BindingStatus.VERIFIED,
                verified_at=NOW,
                verified_by_ref="operator-ref-1",
            )
        )
        await repo.put_role_mapping(RoleMapping(group, Role.LEAD, MappingStatus.ACTIVE))

    with as_tenant(tenant):
        await write_tx(driver, work)


@pytest_asyncio.fixture(loop_scope="session")
async def hosts(
    container: Container,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> dict[str, str]:
    host_a, host_b = f"{tenant_id}.example.test", f"{other_tenant_id}.example.test"
    await seed_edge_tenants(neo4j_driver, tenant_id, other_tenant_id)
    await _tenant(neo4j_driver, tenant_id, host_a, "Alpha ICB")
    await _tenant(neo4j_driver, other_tenant_id, host_b, "Beta ICB")
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    await _configure(neo4j_driver, tenant_id, D_A, G_A)
    await _configure(neo4j_driver, other_tenant_id, D_B, G_B)
    return {"a": host_a, "b": host_b}


def _identity(directory: str, group: str) -> VerifiedIdentity:
    return VerifiedIdentity(
        directory_id=directory, object_id=OID, group_ids=frozenset({group}), app_roles=frozenset()
    )


@pytest_asyncio.fixture(loop_scope="session")
async def app(container: Container, hosts: dict[str, str]) -> FastAPI:
    verifier = FakeIdentityVerifier()
    verifier.accepts("credential-of-a", _identity(D_A, G_A), Audience.STAFF)
    verifier.accepts("credential-of-b", _identity(D_B, G_B), Audience.STAFF)
    parts = ApiParts(
        secrets=FixedSecretStore({name: SECRET for name in REQUIRED_SECRETS}),
        verifier=verifier,
        event_bus=ManualEventBus(container.clock),
    )
    return build_api(Settings(), container, parts)


def _client(app: FastAPI, peer: str = CLOUDFLARE_PEER) -> AsyncClient:
    transport = ASGITransport(app=app, client=(peer, 4321), raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://internal:8000")


def _via_cloudflare(host: str, visitor: str = VISITOR) -> dict[str, str]:
    return {"CF-Connecting-IP": visitor, "X-Forwarded-Host": host}


async def _token(c: AsyncClient, host: str, credential: str, visitor: str = VISITOR) -> str:
    response = await c.post(
        "/auth/token", json={"idToken": credential}, headers=_via_cloudflare(host, visitor)
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["token"]
    return token


async def test_the_health_route_answers(app: FastAPI) -> None:
    async with _client(app, OTHER_PEER) as c:
        response = await c.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_each_tenants_profile_is_served_on_its_own_host(
    app: FastAPI, hosts: dict[str, str]
) -> None:
    async with _client(app) as c:
        a = await c.get("/public/tenant-profile", headers=_via_cloudflare(hosts["a"]))
        b = await c.get("/public/tenant-profile", headers=_via_cloudflare(hosts["b"]))

    assert (a.status_code, b.status_code) == (200, 200)
    assert (a.json()["displayName"], b.json()["displayName"]) == ("Alpha ICB", "Beta ICB")


async def test_a_host_named_by_a_peer_that_is_not_cloudflare_reaches_no_tenant(
    app: FastAPI, hosts: dict[str, str]
) -> None:
    async with _client(app, OTHER_PEER) as c:
        forged = await c.get("/public/tenant-profile", headers=_via_cloudflare(hosts["a"]))
        direct = await c.get(
            "/public/tenant-profile", headers={"Host": hosts["a"], "CF-Connecting-IP": VISITOR}
        )

    assert forged.status_code == 404
    assert (
        direct.status_code == 200
    )  # the Host header itself is the tenant's: no edge header needed


async def test_the_token_exchange_issues_a_token_that_an_authenticated_route_accepts(
    app: FastAPI, hosts: dict[str, str]
) -> None:
    async with _client(app) as c:
        token = await _token(c, hosts["a"], "credential-of-a")
        board = await c.get(BOARD, headers={"Authorization": f"Bearer {token}"})
        refused = await c.get(BOARD)

    assert board.status_code == 200
    assert refused.status_code == 401


async def test_each_hosts_token_names_its_own_tenant_and_no_member_crosses_over(
    app: FastAPI, hosts: dict[str, str], tenant_id: str, other_tenant_id: str
) -> None:
    async with _client(app) as c:
        token_a = await _token(c, hosts["a"], "credential-of-a")
        token_b = await _token(c, hosts["b"], "credential-of-b")
        cross = await c.post(
            "/auth/token", json={"idToken": "credential-of-a"}, headers=_via_cloudflare(hosts["b"])
        )

    assert decode_bff_token(token_a, SECRET, NOW).tenant == tenant_id
    assert decode_bff_token(token_b, SECRET, NOW).tenant == other_tenant_id
    assert cross.status_code == 403  # tenant A's member on tenant B's host gets nothing


async def test_the_network_read_route_is_wired_and_answers_a_lead_with_no_networks(
    app: FastAPI, hosts: dict[str, str]
) -> None:
    async with _client(app) as c:
        token = await _token(c, hosts["a"], "credential-of-a")
        response = await c.get("/networks", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"networks": []}


async def test_the_exchange_limit_counts_the_visitor_and_not_the_proxy(
    app: FastAPI, hosts: dict[str, str]
) -> None:
    async with _client(app) as c:
        statuses = [
            (
                await c.post(
                    "/auth/token",
                    json={"idToken": "unknown-credential"},
                    headers=_via_cloudflare(hosts["a"], VISITOR),
                )
            ).status_code
            for _ in range(61)
        ]
        other = await c.post(
            "/auth/token",
            json={"idToken": "unknown-credential"},
            headers=_via_cloudflare(hosts["a"], OTHER_VISITOR),
        )

    assert statuses[:60] == [403] * 60
    assert statuses[60] == 429
    assert other.status_code == 403  # another visitor behind the same proxy is not limited


async def test_a_forged_visitor_address_from_another_peer_does_not_dodge_the_limit(
    app: FastAPI, hosts: dict[str, str]
) -> None:
    async with _client(app, OTHER_PEER) as c:
        statuses: list[int] = []
        for n in range(61):
            response = await c.post(
                "/auth/token",
                json={"idToken": "unknown-credential"},
                headers={"Host": hosts["a"], "CF-Connecting-IP": f"198.51.100.{n % 200 + 1}"},
            )
            statuses.append(response.status_code)

    assert statuses[60] == 429


async def test_the_sms_webhook_is_wired_and_refuses_an_unsigned_post(app: FastAPI) -> None:
    async with _client(app, OTHER_PEER) as c:
        response = await c.post(
            "/webhooks/sms/twilio",
            data={"To": "+447700900123", "From": "+447700900124", "Body": "Y", "MessageSid": "SM1"},
        )

    assert response.status_code == 403  # an unconfigured server would answer 500


async def test_the_link_pages_are_wired_and_an_unknown_link_is_gone_not_broken(
    app: FastAPI, hosts: dict[str, str]
) -> None:
    async with _client(app) as c:
        response = await c.get("/l/AbCdEfGhIjKlMnOpQrStUvW", headers=_via_cloudflare(hosts["a"]))

    assert response.status_code in (404, 410)


async def test_the_platform_and_tenant_routes_are_wired(app: FastAPI) -> None:
    async with _client(app, OTHER_PEER) as c:
        platform: Any = await c.get("/platform/tenants")
        tenant: Any = await c.get("/tenant/configuration")

    assert platform.status_code == 401
    assert tenant.status_code in (401, 404)
