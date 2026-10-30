"""The execution point against a real Neo4j (TEN-001, DEC-142): the tenant that `run_query` adds
reaches the server as the `$tenant` parameter, a string or a forged statement never reaches it, and
the same key in two tenants does not collide. A raw transaction and a missing scope are refused
(TEN-030).

The unit tests use a recording transaction; this file is the one place the parameter is shown to
work end to end, because every later tenancy task relies on it. It uses a registry of its own, so
no shared statement is touched, and removes its own nodes.
"""

from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.driver import run_global_query, run_query
from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry, Scenario
from diucs.application.tenancy import (
    QueryNotRegistered,
    RawTransactionRefused,
    TenantNotBound,
    TenantParameterRefused,
    bind_tenant,
    scope_for_new_unit,
)
from tests.support.neo4j import run_scope_ids
from tests.support.scoped import scoped

pytestmark = pytest.mark.asyncio(loop_scope="session")

# The conftest binds the run tenant around every integration test (TEN-003). The two tests marked
# `no_tenant` below prove what happens with nothing bound, so they run with nothing bound.

_SCENARIO = Scenario("placeholder until TEN-004")


def _registry() -> QueryRegistry:
    registry = QueryRegistry()
    registry.register(
        NamedQuery(
            id="Q-TEST-PROBE-CREATE",
            cypher="CREATE (n:TenancyProbe {id: $id, note: $note, tenantId: $tenant}) "
            "RETURN n.tenantId AS tenant",
            mode="write",
            scenario=_SCENARIO,
        )
    )
    registry.register(
        NamedQuery(
            id="Q-TEST-PROBE-COUNT",
            cypher="MATCH (n:TenancyProbe {id: $id, tenantId: $tenant}) RETURN count(n) AS n",
            mode="read",
            scenario=_SCENARIO,
        )
    )
    registry.register(
        NamedQuery(id="Q-NEO4J-PING", cypher="RETURN 1 AS ok", mode="read", scope="global")
    )
    return registry


async def _write(driver: AsyncDriver, registry: QueryRegistry, query_id: str, **params: Any) -> Any:
    query = registry.get(query_id)
    async with driver.session() as session:
        return await session.execute_write(
            lambda tx: run_query(scoped(tx), query, registry=registry, **params)
        )


async def _read(driver: AsyncDriver, registry: QueryRegistry, query_id: str, **params: Any) -> Any:
    query = registry.get(query_id)
    async with driver.session() as session:
        return await session.execute_read(
            lambda tx: run_query(scoped(tx), query, registry=registry, **params)
        )


async def _count_all(driver: AsyncDriver, probe_id: str) -> int:
    """The probes with this id in every tenant of the run, counted with raw Cypher (not a
    registered one)."""
    async with driver.session() as session:
        result = await session.run(
            "MATCH (n:TenancyProbe {id: $id}) WHERE n.tenantId IN $scopes RETURN count(n) AS n",
            id=probe_id,
            scopes=run_scope_ids(),
        )
        record = await result.single()
    assert record is not None
    return int(record["n"])


async def test_the_bound_tenant_reaches_the_server_as_the_tenant_parameter(
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    registry = _registry()
    with bind_tenant(tenant_id):
        rows = await _write(neo4j_driver, registry, "Q-TEST-PROBE-CREATE", id="x", note="n")
    assert rows == [{"tenant": tenant_id}]


async def test_the_same_id_in_two_tenants_does_not_collide_and_each_sees_only_its_own(
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    registry = _registry()
    with bind_tenant(tenant_id):
        await _write(neo4j_driver, registry, "Q-TEST-PROBE-CREATE", id="same", note="a")
    with bind_tenant(other_tenant_id):
        assert await _read(neo4j_driver, registry, "Q-TEST-PROBE-COUNT", id="same") == [{"n": 0}]
        await _write(neo4j_driver, registry, "Q-TEST-PROBE-CREATE", id="same", note="b")
        await _write(neo4j_driver, registry, "Q-TEST-PROBE-CREATE", id="only-b", note="b")
    with bind_tenant(tenant_id):
        assert await _read(neo4j_driver, registry, "Q-TEST-PROBE-COUNT", id="same") == [{"n": 1}]
        assert await _read(neo4j_driver, registry, "Q-TEST-PROBE-COUNT", id="only-b") == [{"n": 0}]
    with bind_tenant(other_tenant_id):
        assert await _read(neo4j_driver, registry, "Q-TEST-PROBE-COUNT", id="same") == [{"n": 1}]
        assert await _read(neo4j_driver, registry, "Q-TEST-PROBE-COUNT", id="only-b") == [{"n": 1}]


@pytest.mark.no_tenant
async def test_with_no_tenant_bound_nothing_opens_and_a_raw_transaction_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    registry = _registry()
    # No unit of work, and no other code that opens its own transaction, opens unbound.
    with pytest.raises(TenantNotBound):
        scope_for_new_unit()
    # With nothing bound `scoped` leaves the transaction raw, and a raw transaction is refused.
    with pytest.raises(RawTransactionRefused):
        await _write(neo4j_driver, registry, "Q-TEST-PROBE-CREATE", id="x", note="n")
    assert await _count_all(neo4j_driver, "x") == 0


async def test_a_caller_supplied_tenant_never_reaches_the_server(
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    registry = _registry()
    with bind_tenant(tenant_id), pytest.raises(TenantParameterRefused):
        await _write(neo4j_driver, registry, "Q-TEST-PROBE-CREATE", id="x", note="n", tenant="evil")
    assert await _count_all(neo4j_driver, "x") == 0


async def test_a_string_and_a_forged_statement_are_refused_and_write_nothing(
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    registry = _registry()
    forged = NamedQuery(
        id="Q-TEST-PROBE-CREATE",
        cypher="CREATE (n:TenancyProbe {id: $id, note: $note, tenantId: 'forged'}) RETURN $tenant",
        mode="write",
        scenario=_SCENARIO,
    )
    async with neo4j_driver.session() as session:
        with bind_tenant(tenant_id):
            with pytest.raises(QueryNotRegistered):
                await session.execute_write(
                    lambda tx: run_query(
                        scoped(tx),
                        "Q-TEST-PROBE-CREATE",
                        registry=registry,
                        id="x",
                        note="n",  # type: ignore[arg-type]
                    )
                )
            with pytest.raises(QueryNotRegistered):
                await session.execute_write(
                    lambda tx: run_query(scoped(tx), forged, registry=registry, id="x", note="n")
                )
    assert await _count_all(neo4j_driver, "x") == 0


async def test_a_raw_transaction_is_refused_with_a_scope_bound_and_writes_nothing(
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    registry = _registry()
    create = registry.get("Q-TEST-PROBE-CREATE")
    with bind_tenant(tenant_id):
        async with neo4j_driver.session() as session:
            with pytest.raises(RawTransactionRefused):
                await session.execute_write(
                    lambda tx: run_query(tx, create, registry=registry, id="x", note="n")  # type: ignore[arg-type]
                )
    assert await _count_all(neo4j_driver, "x") == 0


async def test_a_global_statement_runs_through_run_global_query_with_no_scope_bound(
    neo4j_driver: AsyncDriver,
) -> None:
    registry = _registry()
    ping = registry.get("Q-NEO4J-PING")
    async with neo4j_driver.session() as session:
        rows = await session.execute_read(lambda tx: run_global_query(tx, ping, registry=registry))
    assert rows == [{"ok": 1}]
