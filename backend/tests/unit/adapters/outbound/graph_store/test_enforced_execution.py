"""Seam step two, the execution point (TEN-030, DEC-144 item 3, DEC-146 items 2 and 3).

With the ratchet gone, `run_query` has one rule: a tenant statement runs on a `ScopedTx` that
carries a scope, and on nothing else. A raw transaction is refused whatever is bound in the
context; a unit of work, or any other code that opens its own transaction, refuses to open with
no scope bound. A global statement still runs on a raw transaction (the health ping and the tenant
directory run before any scope exists), and only through `run_global_query`.

The transaction is a recording stub: no Neo4j.
"""

from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.driver import (
    ScopedTx,
    run_global_query,
    run_query,
    set_query_observer,
)
from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry, Scenario
from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork
from diucs.application.tenancy import (
    RawTransactionRefused,
    ScopeId,
    TenantNotBound,
    bind_scope,
    bind_tenant,
    scope_for_new_unit,
)
from tests.support.fake_neo4j import FakeDriver

SCOPED_CYPHER = "MATCH (n:Observation {id: $id, tenantId: $tenant}) RETURN n.id AS id"
GLOBAL_CYPHER = "RETURN 1 AS ok"
A1 = ScopeId.tenant("a1")


class _Result:
    async def data(self) -> list[dict[str, Any]]:
        return [{"id": "r1"}]


class _Tx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append((cypher, dict(parameters or {})))
        return _Result()


@pytest.fixture
def registry() -> QueryRegistry:
    new = QueryRegistry()
    new.register(
        NamedQuery(
            id="Q-SCOPED", cypher=SCOPED_CYPHER, mode="read", scenario=Scenario("a scenario")
        )
    )
    new.register(NamedQuery(id="Q-NEO4J-PING", cypher=GLOBAL_CYPHER, mode="read", scope="global"))
    return new


@pytest.fixture(autouse=True)
def _no_observer() -> Any:
    set_query_observer(None)


# 1. A raw transaction is refused


async def test_a_raw_transaction_is_refused_even_with_a_scope_bound(registry: QueryRegistry) -> None:
    tx = _Tx()
    with bind_tenant("a1"), pytest.raises(RawTransactionRefused):
        await run_query(tx, registry.get("Q-SCOPED"), registry=registry, id="x")  # type: ignore[arg-type]
    assert tx.calls == []


async def test_a_raw_transaction_is_refused_with_no_scope_bound_too(registry: QueryRegistry) -> None:
    tx = _Tx()
    with pytest.raises(RawTransactionRefused):
        await run_query(tx, registry.get("Q-SCOPED"), registry=registry, id="x")  # type: ignore[arg-type]
    assert tx.calls == []


async def test_a_raw_transaction_still_runs_a_global_statement(registry: QueryRegistry) -> None:
    tx = _Tx()
    rows = await run_global_query(tx, registry.get("Q-NEO4J-PING"), registry=registry)  # type: ignore[arg-type]
    assert rows == [{"id": "r1"}]
    assert tx.calls == [(GLOBAL_CYPHER, {})]


def test_the_refusal_has_a_fixed_message_and_names_nothing() -> None:
    assert str(RawTransactionRefused()) == (
        "a tenant statement runs only on a scoped transaction, opened by a unit of work"
    )


# 2. A scoped transaction always carries a scope


def test_a_scoped_transaction_cannot_be_made_without_a_scope() -> None:
    with pytest.raises(TenantNotBound):
        ScopedTx(_Tx(), None)  # type: ignore[arg-type]


async def test_a_scoped_transaction_runs_the_statement_with_its_scope(
    registry: QueryRegistry,
) -> None:
    tx = _Tx()
    await run_query(ScopedTx(tx, A1), registry.get("Q-SCOPED"), registry=registry, id="x")  # type: ignore[arg-type]
    assert tx.calls == [(SCOPED_CYPHER, {"tenant": "a1", "id": "x"})]


# 3. Opening a unit refuses when nothing is bound


def test_a_new_unit_with_no_scope_bound_is_refused() -> None:
    with pytest.raises(TenantNotBound):
        scope_for_new_unit()


def test_a_new_unit_takes_the_scope_bound_now() -> None:
    with bind_tenant("a1"):
        assert scope_for_new_unit() == A1
        with bind_scope(ScopeId.network("net-pilot")):
            assert scope_for_new_unit() == ScopeId.network("net-pilot")


async def test_a_unit_of_work_with_no_scope_bound_opens_no_session_and_claims_nothing() -> None:
    driver = FakeDriver()
    unit = Neo4jUnitOfWork(driver)  # type: ignore[arg-type]
    with pytest.raises(TenantNotBound):
        async with unit:
            pytest.fail("the unit must not open")
    assert driver.calls == []
    # Nothing is claimed: a unit bound to a tenant opens at once.
    with bind_tenant("a1"):
        async with Neo4jUnitOfWork(driver) as opened:  # type: ignore[arg-type]
            assert opened.unit_scope == A1
