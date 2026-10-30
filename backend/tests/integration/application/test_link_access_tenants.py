"""Two-tenant tests for link access (L01, DEC-130 to DEC-132, DEC-167).

Tenant A and tenant B each have a service, a reporter, a figure on record and a prompt with a link.
A link is found only in the tenant it was issued in: asked for in the other tenant it is not found,
and answers exactly as a link nobody holds does, in every use case, with nothing read, changed or
queued. The budgets of the rate limits are per tenant.

The resource store stamps and scopes its nodes (TEN-009), so a second tenant's Concept or resource
with the same key is refused on the shared harness schema until TEN-032. This module therefore runs
on a private contracted container (DEC-159), as the other two-tenant tests do. The capacity,
communication, person and replay statements are still unconverted (tenant-pending, evidence L01),
so each tenant has its own service id and its own reporter phone; what is proved here is what the
link code itself decides.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases import link_access
from diucs.application.use_cases.link_access import LinkGone, LinkRateLimited
from tests.support.ladder_rig import PHONE_HASH_2
from tests.support.link_rig import ANSWER_AT, LinkRig, build_link_rig, new_secrets
from tests.support.neo4j import wipe_all
from tests.support.tenant_seed import contracted_container

pytestmark = pytest.mark.asyncio(loop_scope="session")

OTHER_PHONE = PHONE_HASH_2


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """A private Neo4j with every migration applied and the superseded single-property keys
    dropped (DEC-159)."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    """Overrides the session driver for this module: every test here runs two tenants."""
    return two_tenant_driver


@pytest_asyncio.fixture(loop_scope="session")
async def two(two_tenant_driver: AsyncDriver) -> AsyncIterator[None]:
    await wipe_all(two_tenant_driver)
    yield
    await wipe_all(two_tenant_driver)


@pytest.fixture
def links(
    two: None, uow_factory_a: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> LinkRig:
    """The rig for the run tenant, on a clock, a cache and secrets that tenant B's rig shares."""
    clock = FixedClock(ANSWER_AT)
    return build_link_rig(
        uow_factory_a,
        neo4j_driver,
        tenant_id,
        clock=clock,
        secrets=new_secrets(),
        cache=InMemoryCache(clock),
        ids=SequentialIds.scoped(tenant_id),
    )


async def _prompted(links: LinkRig) -> str:
    await links.seed()
    token = await links.prompt()
    links.clock.set(ANSWER_AT)
    return token


async def test_the_budgets_of_two_tenants_are_separate(
    links: LinkRig,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(link_access, "REQUESTS_PER_WINDOW", 2)
    token = await _prompted(links)
    other = build_link_rig(
        uow_factory_b,
        neo4j_driver,
        other_tenant_id,
        clock=links.clock,
        secrets=links.secrets,
        cache=links.cache,
        ids=SequentialIds.scoped(other_tenant_id),
        service_id="ucr-west-b",
        prefix="b-",
        phone=OTHER_PHONE,
    )
    await other.seed()
    with bind_tenant(other_tenant_id):
        other_token = await other.prompt()
    links.clock.set(ANSWER_AT)

    for _ in range(2):
        await links.view(token)
    with pytest.raises(LinkRateLimited):
        await links.view(token)
    with bind_tenant(other_tenant_id):
        assert (await other.view(other_token)).body["state"] == "ok"
        assert (await other.view(other_token)).body["state"] == "ok"
        with pytest.raises(LinkRateLimited):
            await other.view(other_token)


async def test_another_tenants_link_is_an_unknown_one_in_every_use_case(
    links: LinkRig,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
) -> None:
    token_a = await _prompted(links)
    other = build_link_rig(
        uow_factory_b,
        neo4j_driver,
        other_tenant_id,
        clock=links.clock,
        secrets=links.secrets,
        ids=SequentialIds.scoped(other_tenant_id),
        service_id="ucr-west-b",
        prefix="b-",
        phone=OTHER_PHONE,
    )
    await other.seed(figure=7)
    with bind_tenant(other_tenant_id):
        token_b = await other.prompt()
    links.clock.set(ANSWER_AT)
    before = await links.counts()

    # Tenant A is asked for tenant B's link: not found, the same as a link nobody holds.
    with pytest.raises(LinkGone) as view_b:
        await links.view(token_b)
    with pytest.raises(LinkGone) as view_unknown:
        await links.view("Z" * 23)
    with pytest.raises(LinkGone) as respond_b:
        await links.respond(token_b, "number", 4)
    await links.renew(token_b)

    assert view_b.value.state == view_unknown.value.state == respond_b.value.state == "expired"
    assert await links.counts() == before
    assert (await links.latest()).value == 3
    # Tenant B's link was not touched, and works in tenant B.
    with bind_tenant(other_tenant_id):
        assert "usedAt" not in await other.token_node(token_b)
        page = await other.view(token_b)
        assert page.body["recordedValue"] == 7
        assert page.body["serviceName"] == "UCR West"
    # ... and tenant B is asked for tenant A's link.
    with bind_tenant(other_tenant_id):
        with pytest.raises(LinkGone) as view_a:
            await other.view(token_a)
        assert view_a.value.state == "expired"
