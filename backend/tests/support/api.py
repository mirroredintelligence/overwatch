"""API test support (R01, TEN-018): the test container and the HTTP client every route test uses.

The app runs on the composition root's test profile, on the Docker Neo4j of the F10 harness, with
fakes only for external providers. Route tests add their own test-only routes to api_app.

The REST edge binds the tenant from the verified token and checks it against the tenant directory
(TEN-018), so the harness seeds an active tenant record for the run's tenant and for its second
tenant (`edge_tenants`, which `api_app` depends on), and a request is sent for a tenant with a token
that names it (`token_headers`). A test token with no tenant argument names the run tenant.
"""

import hashlib
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_directory import tenant_properties
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import issue_test_token
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import Role
from tests.support.neo4j import ThrowawayNeo4j, write_tx
from tests.support.tenancy import as_tenant
from tests.support.tenant_samples import make_tenant

# The clock of the R01 route tests (DEC-070 item 4): 14:12 London, passed explicitly. F08's
# TEST_NOW (13:00Z) is left unchanged.
R01_TEST_NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
# The key that hashes a phone number in the routes that take one (R08); synthetic.
TEST_PHONE_HASH_SECRET = b"phone-hash-route-test-secret-0123456789ab"


@pytest_asyncio.fixture(loop_scope="session")
async def test_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The composition root's test profile on the harness Neo4j. Each test owns one connection,
    which it closes; the graph was wiped by clean_graph."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(R01_TEST_NOW),
            neo4j=connection,
            secrets=FixedSecretStore({PHONE_HASH_SECRET: TEST_PHONE_HASH_SECRET}),
        )
    finally:
        await connection.close()


WALL_TEST_SUBS = ("prac-1", "device-wall-1", "device-wall-x")
"""The subjects the route tests give a wall token. The edge refuses a wall token whose screen is not
an active one of the tenant (W9I, `auth.ensure_screen_live`), so each tenant is seeded one active
screen per subject."""


async def seed_edge_tenants(driver: AsyncDriver, *tenant_ids: str, epoch: int = 1) -> None:
    """An active tenant record for each id (merged, so a second call changes nothing but the
    epoch), as the REST edge reads it from the directory, and an active wall screen for each
    subject a route test gives a wall token."""

    async def work(tx: AsyncManagedTransaction) -> None:
        for tenant_id in tenant_ids:
            props = tenant_properties(make_tenant(id=tenant_id, epoch=epoch))
            await tx.run("MERGE (t:Tenant {id: $id}) SET t += $props", id=tenant_id, props=props)

    async def screens(tx: AsyncManagedTransaction) -> None:
        for sub in WALL_TEST_SUBS:
            await tx.run(
                "MERGE (d:Device {id: $id, tenantId: $tenant, deviceType: 'wall-display'}) "
                "SET d.status = 'active', d.deviceName = 'Test wall screen', "
                "d.boardScope = 'tenant', d.tokenHash = $hash",
                id=sub,
                hash=hashlib.sha256(sub.encode()).hexdigest(),
            )

    await write_tx(driver, work)
    for tenant_id in tenant_ids:
        with as_tenant(tenant_id):
            await write_tx(driver, screens)


def token_headers(
    tenant: str | None = None,
    role: Role = Role.LEAD,
    services: Sequence[str] = (),
    sub: str = "prac-1",
    *,
    epoch: int = 1,
) -> dict[str, str]:
    """A bearer header for a token that names this tenant (the run tenant when none is given)."""
    token = issue_test_token(role, services, sub, tenant=tenant, epoch=epoch)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(loop_scope="session")
async def edge_tenants(
    test_container: Container, neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """The run tenant and the second tenant exist and are active, after clean_graph has wiped."""
    await seed_edge_tenants(neo4j_driver, tenant_id, other_tenant_id)


@pytest_asyncio.fixture(loop_scope="session")
async def api_app(test_container: Container, edge_tenants: None) -> FastAPI:
    return create_app(test_container)


@pytest_asyncio.fixture(loop_scope="session")
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=api_app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client
