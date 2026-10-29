"""Fixtures for the link page tests (L01): the FHIR app with the link pages' collaborators set, two
tenants with a host each in the real tenant directory of the harness Neo4j, and the rig that seeds
a service, a reporter and a real prompt in either tenant.

The tests that call the app run with no tenant bound (`no_tenant`): the route has to bind the tenant
from the host itself, which a binding left over from the harness would hide. The rig's units of work
bind the tenant they are for.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.link_pages.capacity_links import LinkPagesDeps
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_directory import tenant_properties
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.model.tenant import TenantStatus
from tests.support.ladder_rig import PHONE_HASH_2
from tests.support.link_rig import (
    ANSWER_AT,
    HOST_A,
    HOST_B,
    LinkRig,
    build_link_rig,
    new_secrets,
)
from tests.support.neo4j import ThrowawayNeo4j, write_tx
from tests.support.tenant_samples import make_tenant
from tests.support.uow import tenant_uow_factory

OTHER_SERVICE = "ucr-west-b"


@pytest_asyncio.fixture(loop_scope="session")
async def link_container(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Container]:
    """The composition root's test profile on the harness Neo4j, at 10:05 London on the day of the
    prompt, with the two secrets the links use."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(ANSWER_AT),
            ids=SequentialIds(),
            neo4j=connection,
            secrets=new_secrets(),
        )
    finally:
        await connection.close()


@pytest.fixture
def link_clock(link_container: Container) -> FixedClock:
    clock = link_container.clock
    assert isinstance(clock, FixedClock)
    return clock


@pytest.fixture
def link_cache(link_clock: FixedClock) -> InMemoryCache:
    return InMemoryCache(link_clock)


@pytest.fixture
def link_app(link_container: Container, link_cache: InMemoryCache) -> FastAPI:
    app = create_app(link_container)
    app.state.link_pages = LinkPagesDeps(
        cache=link_cache, sealer=AesGcmContentSealer(link_container.secrets)
    )
    return app


async def seed_tenant_host(
    driver: AsyncDriver,
    tenant_id: str,
    host: str,
    status: TenantStatus = TenantStatus.ACTIVE,
    damage: dict[str, object] | None = None,
) -> None:
    """A tenant record with this host. `damage` overwrites properties to make a record the domain
    refuses."""
    props = tenant_properties(make_tenant(status, id=tenant_id))
    props["host"] = host
    props.update(damage or {})

    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run("CREATE (t:Tenant) SET t = $props", props=props)

    await write_tx(driver, work)


@pytest_asyncio.fixture
async def hosts(neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str) -> None:
    """Each run tenant has a host: alpha for the run tenant, bravo for the second."""
    await seed_tenant_host(neo4j_driver, tenant_id, HOST_A)
    await seed_tenant_host(neo4j_driver, other_tenant_id, HOST_B)


def client_for(app: FastAPI, host: str = HOST_A) -> AsyncClient:
    """A client that reaches the app as `host`, as a request through the proxy would."""
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url=f"https://{host}",
    )


@pytest_asyncio.fixture
async def link_client(link_app: FastAPI, hosts: None) -> AsyncIterator[AsyncClient]:
    async with client_for(link_app) as client:
        yield client


@pytest_asyncio.fixture
async def other_client(link_app: FastAPI, hosts: None) -> AsyncIterator[AsyncClient]:
    async with client_for(link_app, HOST_B) as client:
        yield client


@pytest.fixture
def links(
    link_container: Container,
    link_cache: InMemoryCache,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> LinkRig:
    """The rig for the run tenant: its units of work bind that tenant, so the body needs none."""
    return build_link_rig(
        tenant_uow_factory(neo4j_driver, tenant_id, link_container.clock),
        neo4j_driver,
        tenant_id,
        clock=link_container.clock,  # type: ignore[arg-type]
        secrets=link_container.secrets,  # type: ignore[arg-type]
        cache=link_cache,
        ids=SequentialIds.scoped(tenant_id),
    )


@pytest.fixture
def other_links(
    link_container: Container,
    link_cache: InMemoryCache,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
) -> LinkRig:
    """The rig for the second tenant: its own service, reporter and phone (a phone number is still
    found across tenants until the person statements are converted, TEN-011)."""
    return build_link_rig(
        tenant_uow_factory(neo4j_driver, other_tenant_id, link_container.clock),
        neo4j_driver,
        other_tenant_id,
        clock=link_container.clock,  # type: ignore[arg-type]
        secrets=link_container.secrets,  # type: ignore[arg-type]
        cache=link_cache,
        ids=SequentialIds.scoped(other_tenant_id),
        service_id=OTHER_SERVICE,
        prefix="b-",
        phone=PHONE_HASH_2,
    )
