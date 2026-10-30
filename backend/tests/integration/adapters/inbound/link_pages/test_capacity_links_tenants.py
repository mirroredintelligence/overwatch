"""Two tenants through the link pages' API (L01, DEC-130 to DEC-132, DEC-134 item 3, DEC-167).

The host picks the tenant, and a link is found only in the tenant it was issued in: A's link asked
for on B's host, and B's on A's, answer exactly as a link nobody holds does, and nothing is read,
changed or queued. A tenant in the query string, a header or the body changes nothing. A budget
spent by one address in one tenant is not spent in another.

These run on a private contracted container (DEC-159): the resource store stamps and scopes its
nodes (TEN-009), and the shared harness schema refuses a second tenant's Concept until TEN-032. The
capacity, communication, person and replay statements are still unconverted, so each tenant has its
own service id and reporter phone (evidence L01, tenant-pending). The tests run with no tenant
bound, so the route must bind it from the host.
"""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.use_cases import link_access
from diucs.bootstrap.container import Container, build_for_tests
from tests.support.link_rig import (
    ANSWER_AT,
    REPLY_BY,
    LinkRig,
    new_secrets,
)
from tests.support.neo4j import ThrowawayNeo4j

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.no_tenant]

EXPIRED_BODY = {"state": "expired"}


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant(
    harness_container: ThrowawayNeo4j, harness_driver: AsyncDriver
) -> tuple[ThrowawayNeo4j, AsyncDriver]:
    """The shared harness database, which has the contracted schema (DEC-159)."""
    return harness_container, harness_driver


@pytest_asyncio.fixture(loop_scope="session")
async def link_container(
    two_tenant: tuple[ThrowawayNeo4j, AsyncDriver], clean_graph: None
) -> AsyncIterator[Container]:
    container, driver = two_tenant
    connection = Neo4jConnection(container.uri, container.user, container.password)
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


async def _prompted(links: LinkRig) -> str:
    await links.seed()
    token = await links.prompt()
    links.clock.set(ANSWER_AT)
    return token


async def test_the_host_picks_the_tenant_and_another_tenants_link_is_an_unknown_one(
    link_client: AsyncClient,
    other_client: AsyncClient,
    links: LinkRig,
    other_links: LinkRig,
) -> None:
    token_a = await _prompted(links)
    await other_links.seed(figure=7)
    token_b = await other_links.prompt()
    links.clock.set(ANSWER_AT)

    on_a = await link_client.get(f"/links/{token_a}")
    on_b = await other_client.get(f"/links/{token_b}")
    cross_a = await other_client.get(f"/links/{token_a}")  # A's link on B's host
    cross_b = await link_client.get(f"/links/{token_b}")  # B's link on A's host
    unknown = await link_client.get(f"/links/{'Q' * 23}")

    assert (on_a.status_code, on_b.status_code) == (200, 200)
    assert on_a.json()["recordedValue"] == 3 and on_b.json()["recordedValue"] == 7
    for crossed in (cross_a, cross_b):
        assert (crossed.status_code, crossed.content) == (unknown.status_code, unknown.content)
        assert dict(crossed.headers) == dict(unknown.headers)


async def test_a_link_cannot_be_answered_renewed_or_burned_from_another_tenants_host(
    link_client: AsyncClient,
    other_client: AsyncClient,
    links: LinkRig,
    other_links: LinkRig,
    link_clock: FixedClock,
) -> None:
    await links.seed()
    await other_links.seed(figure=7)
    token_b = await other_links.prompt()
    link_clock.set(ANSWER_AT)
    before_a, before_b = await links.counts(), await other_links.counts()

    answered = await link_client.post(
        f"/links/{token_b}",
        json={"action": "number", "value": 5},
        headers={"X-CSRF-Token": other_links.csrf(token_b)},  # the right token, the wrong host
    )
    link_clock.set(REPLY_BY + timedelta(minutes=3))
    renewed = await link_client.post(f"/links/{token_b}/renew")

    assert (answered.status_code, answered.json()) == (410, EXPIRED_BODY)
    assert renewed.status_code == 202
    assert await links.counts() == before_a  # nothing was recorded or queued in A
    assert await other_links.counts() == before_b  # nor in B
    assert "usedAt" not in await other_links.token_node(token_b)


async def test_a_tenant_in_the_query_a_header_or_the_body_changes_nothing(
    link_client: AsyncClient, links: LinkRig, other_links: LinkRig
) -> None:
    token = await _prompted(links)
    await other_links.seed()
    other_token = await other_links.prompt()
    links.clock.set(ANSWER_AT)
    names = {"tenant": other_links.tenant, "tenantId": other_links.tenant}
    headers = {"X-Tenant-Id": other_links.tenant, "X-Tenant": other_links.tenant}

    mine = await link_client.get(f"/links/{token}", params=names, headers=headers)
    theirs = await link_client.get(f"/links/{other_token}", params=names, headers=headers)
    forced = await link_client.post(
        f"/links/{token}",
        json={"action": "confirm", "tenantId": other_links.tenant},
        headers={"X-CSRF-Token": links.csrf(token), **headers},
    )

    assert mine.status_code == 200 and mine.json()["recordedValue"] == 3
    assert (theirs.status_code, theirs.json()) == (410, EXPIRED_BODY)
    assert forced.status_code == 400  # a field this link does not take


async def test_an_address_that_keeps_missing_gets_429_and_another_tenant_is_not_affected(
    link_client: AsyncClient,
    other_client: AsyncClient,
    links: LinkRig,
    other_links: LinkRig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(link_access, "BAD_ATTEMPTS_PER_ADDRESS", 2)
    await links.seed()
    await other_links.seed()
    other_token = await other_links.prompt()
    links.clock.set(ANSWER_AT)

    misses = [(await link_client.get(f"/links/{c * 23}")).status_code for c in "ABC"]

    assert misses == [410, 410, 429]
    assert (await other_client.get(f"/links/{other_token}")).status_code == 200
