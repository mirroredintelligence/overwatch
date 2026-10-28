"""The harness binds a tenant per run (TEN-003, DEC-130 item 9, DEC-147), against a real Neo4j.

Every integration test runs with the run tenant bound, units of work carry it, and a second tenant
is one fixture away. The wipe is still the whole database (TEN-033), so these tests clean up
through the ordinary `clean_graph`, and the nodes they write carry a `tenantId` that only a
converted statement writes: the probe statements here are the first in the code base to run in a
tenant, which shows that a converted statement can run in tests.
"""

from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry, Scenario
from diucs.adapters.outbound.graph_store.unit_of_work import DEFAULT_FACTORIES, neo4j_uow_factory
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, current_scope_or_none, current_tenant
from tests.support.tenancy import as_tenant
from tests.support.uow import tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def tenant_at_setup() -> ScopeId | None:
    """What an async fixture of the test sees when it is set up."""
    return current_scope_or_none()


async def test_the_run_tenant_is_bound_and_every_factory_hands_out_its_own_tenant(
    tenant_id: str,
    other_tenant_id: str,
    uow_factory: UnitOfWorkFactory,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    assert current_tenant() == tenant_id
    async with uow_factory() as ambient:
        assert ambient.unit_scope == ScopeId.tenant(tenant_id)
    async with uow_factory_a() as a:
        assert a.unit_scope == ScopeId.tenant(tenant_id)
    # A's unit is finished, so B's opens; neither changed what is bound in the test.
    async with uow_factory_b() as b:
        assert b.unit_scope == ScopeId.tenant(other_tenant_id)
        assert current_tenant() == tenant_id
    assert current_tenant() == tenant_id
    assert other_tenant_id != tenant_id


async def test_an_async_fixture_is_set_up_with_the_run_tenant_already_bound(
    tenant_at_setup: ScopeId | None, tenant_id: str
) -> None:
    assert tenant_at_setup == ScopeId.tenant(tenant_id)


# A converted statement runs in the bound tenant, and the same id in two tenants does not collide.

_SCENARIO = Scenario("placeholder until TEN-004")


def _registry() -> QueryRegistry:
    registry = QueryRegistry()
    registry.register(
        NamedQuery(
            id="Q-HARNESS-CREATE",
            cypher="CREATE (n:HarnessProbe {id: $id, tenantId: $tenant}) "
            "RETURN n.tenantId AS tenant",
            mode="write",
            scenario=_SCENARIO,
        )
    )
    registry.register(
        NamedQuery(
            id="Q-HARNESS-COUNT",
            cypher="MATCH (n:HarnessProbe {id: $id, tenantId: $tenant}) RETURN count(n) AS n",
            mode="read",
            scenario=_SCENARIO,
        )
    )
    return registry


class _Probe:
    def __init__(self, tx: Any, registry: QueryRegistry) -> None:
        self._tx = tx
        self._registry = registry

    async def create(self, id: str) -> str:
        rows = await run_query(
            self._tx, self._registry.get("Q-HARNESS-CREATE"), registry=self._registry, id=id
        )
        return str(rows[0]["tenant"])

    async def count(self, id: str) -> int:
        rows = await run_query(
            self._tx, self._registry.get("Q-HARNESS-COUNT"), registry=self._registry, id=id
        )
        return int(rows[0]["n"])


async def test_the_same_id_in_the_run_tenant_and_the_second_tenant_does_not_collide(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    registry = _registry()
    factories = {**DEFAULT_FACTORIES, "probe": lambda tx, store: _Probe(tx, registry)}
    # The ambient run tenant (the conftest bound it) and the second tenant, one unit each.
    ambient = neo4j_uow_factory(neo4j_driver, factories=factories)
    other = tenant_uow_factory(neo4j_driver, other_tenant_id, factories=factories)

    async with ambient() as uow:
        assert await uow.probe.create("same") == tenant_id  # type: ignore[attr-defined]
        assert await uow.probe.create("only-a") == tenant_id  # type: ignore[attr-defined]
        await uow.commit()
    async with other() as uow:
        assert await uow.probe.count("same") == 0  # type: ignore[attr-defined]
        assert await uow.probe.create("same") == other_tenant_id  # type: ignore[attr-defined]
        assert await uow.probe.count("only-a") == 0  # type: ignore[attr-defined]
        await uow.commit()
    async with ambient() as uow:
        assert await uow.probe.count("same") == 1  # type: ignore[attr-defined]
        assert await uow.probe.count("only-a") == 1  # type: ignore[attr-defined]


# as_tenant inside a test is not a leak, and the next test is bound again.


async def test_a_test_that_switches_tenant_and_returns_is_not_flagged(
    tenant_id: str, other_tenant_id: str
) -> None:
    with as_tenant(other_tenant_id):
        assert current_tenant() == other_tenant_id
    assert current_tenant() == tenant_id


async def test_the_test_after_it_sees_the_run_tenant_again(tenant_id: str) -> None:
    assert current_tenant() == tenant_id


@pytest.mark.no_tenant
async def test_a_test_marked_no_tenant_runs_with_nothing_bound(
    uow_factory: UnitOfWorkFactory,
) -> None:
    assert current_scope_or_none() is None
    async with uow_factory() as uow:
        assert uow.unit_scope is None
