"""The scoped transaction (TEN-002, DEC-142, DEC-144): a unit of work binds one scope when it opens
and carries it on a `ScopedTx`; `run_query` reads that scope and not the ambient context, so
rebinding the context afterwards changes nothing for that unit.

The transaction is a recording stub: no Neo4j. The ambient context is rebound inside each test to
show that the carried scope wins.
"""

import dataclasses
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store import driver as driver_module
from diucs.adapters.outbound.graph_store.driver import (
    ScopedTx,
    run_global_query,
    run_query,
    set_query_observer,
)
from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry, Scenario
from diucs.application.tenancy import (
    GlobalStatementMisuse,
    ScopeId,
    TenantNotBound,
    TenantParameterRefused,
    bind_scope,
    bind_tenant,
)

SCOPED_CYPHER = "MATCH (n:Observation {id: $id, tenantId: $tenant}) RETURN n.id AS id"
OLD_CYPHER = "MATCH (n:Observation {id: $id}) RETURN n.id AS id"
GLOBAL_CYPHER = "RETURN 1 AS ok"
SCENARIO = Scenario("placeholder until TEN-004")

A1 = ScopeId.tenant("a1")
B1 = ScopeId.tenant("b1")
NETWORK = ScopeId.network("net-pilot")


class _StubResult:
    async def data(self) -> list[dict[str, Any]]:
        return [{"id": "r1"}]


class _StubTx:
    """Stands in for the managed transaction: records what it was asked to run."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _StubResult:
        self.calls.append((cypher, dict(parameters or {})))
        return _StubResult()


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> QueryRegistry:
    new = QueryRegistry(unconverted=frozenset({"Q-OLD"}))
    new.register(NamedQuery(id="Q-SCOPED", cypher=SCOPED_CYPHER, mode="read", scenario=SCENARIO))
    new.register(NamedQuery(id="Q-OLD", cypher=OLD_CYPHER, mode="read"))
    new.register(NamedQuery(id="Q-NEO4J-PING", cypher=GLOBAL_CYPHER, mode="read", scope="global"))
    monkeypatch.setattr(driver_module, "REGISTRY", new)
    return new


@pytest.fixture(autouse=True)
def _no_observer() -> Any:
    set_query_observer(None)


# 1. The type


def test_a_scoped_transaction_is_a_frozen_pair_with_no_way_to_run_cypher() -> None:
    scoped = ScopedTx(_StubTx(), A1)  # type: ignore[arg-type]
    assert [field.name for field in dataclasses.fields(ScopedTx)] == ["tx", "scope"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        scoped.scope = B1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        scoped.tx = _StubTx()  # type: ignore[misc,assignment]
    # The only way to run a statement on it is run_query, so a repository cannot bypass the
    # tenant parameter.
    assert not hasattr(ScopedTx, "run")
    assert not hasattr(scoped, "run")
    assert not hasattr(scoped, "execute_query")


# 2. A unit keeps its scope however the context changes


async def test_a_scoped_transaction_sends_its_own_scope_not_the_ambient_one(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    with bind_scope(B1):
        rows = await run_query(
            ScopedTx(stub, A1),  # type: ignore[arg-type]
            registry.get("Q-SCOPED"),
            id="x",
        )
    assert rows == [{"id": "r1"}]
    assert stub.calls == [(SCOPED_CYPHER, {"tenant": "a1", "id": "x"})]


async def test_the_scope_carried_by_a_scoped_transaction_survives_every_rebinding(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    scoped = ScopedTx(stub, A1)  # type: ignore[arg-type]
    query = registry.get("Q-SCOPED")
    await run_query(scoped, query, id="1")
    with bind_scope(B1):
        await run_query(scoped, query, id="2")
        with bind_scope(NETWORK):
            await run_query(scoped, query, id="3")
    await run_query(scoped, query, id="4")
    assert [params["tenant"] for _, params in stub.calls] == ["a1", "a1", "a1", "a1"]


async def test_a_scoped_transaction_with_no_scope_sends_no_tenant_for_a_statement_not_yet_converted(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    with bind_scope(B1):
        await run_query(ScopedTx(stub, None), registry.get("Q-OLD"), id="x")  # type: ignore[arg-type]
    assert stub.calls == [(OLD_CYPHER, {"id": "x"})]


async def test_a_scoped_transaction_with_no_scope_refuses_a_converted_statement_though_one_is_bound(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    with bind_scope(B1), pytest.raises(TenantNotBound):
        await run_query(ScopedTx(stub, None), registry.get("Q-SCOPED"), id="x")  # type: ignore[arg-type]
    assert stub.calls == []


async def test_a_scoped_transaction_gives_a_statement_not_yet_converted_its_scope_unused(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    await run_query(ScopedTx(stub, A1), registry.get("Q-OLD"), id="x")  # type: ignore[arg-type]
    assert stub.calls == [(OLD_CYPHER, {"tenant": "a1", "id": "x"})]


async def test_a_network_scope_reaches_the_statement_as_the_same_parameter(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    await run_query(ScopedTx(stub, NETWORK), registry.get("Q-SCOPED"), id="x")  # type: ignore[arg-type]
    assert stub.calls[0][1]["tenant"] == "net-pilot"


async def test_a_caller_supplied_tenant_is_refused_on_a_scoped_transaction_too(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    for name in ("tenant", "parameters"):
        with pytest.raises(TenantParameterRefused):
            await run_query(
                ScopedTx(stub, A1),  # type: ignore[arg-type]
                registry.get("Q-SCOPED"),
                **{name: "evil"},
            )
    assert stub.calls == []


async def test_a_global_statement_is_refused_by_run_query_on_a_scoped_transaction(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    with pytest.raises(GlobalStatementMisuse):
        await run_query(ScopedTx(stub, A1), registry.get("Q-NEO4J-PING"))  # type: ignore[arg-type]
    assert stub.calls == []


# 3. A raw transaction behaves as TEN-001 left it


async def test_a_raw_transaction_still_takes_the_ambient_scope(registry: QueryRegistry) -> None:
    stub = _StubTx()
    with bind_tenant("b1"):
        await run_query(stub, registry.get("Q-SCOPED"), id="x")  # type: ignore[arg-type]
    assert stub.calls == [(SCOPED_CYPHER, {"tenant": "b1", "id": "x"})]
    with pytest.raises(TenantNotBound):
        await run_query(stub, registry.get("Q-SCOPED"), id="x")  # type: ignore[arg-type]


# 4. The global path takes either kind and never a tenant


@pytest.mark.parametrize("wrap", [False, True])
async def test_run_global_query_sends_no_tenant_on_either_kind_of_transaction(
    registry: QueryRegistry, wrap: bool
) -> None:
    stub = _StubTx()
    tx = ScopedTx(stub, A1) if wrap else stub
    with bind_scope(B1):
        rows = await run_global_query(tx, registry.get("Q-NEO4J-PING"))  # type: ignore[arg-type]
    assert rows == [{"id": "r1"}]
    assert stub.calls == [(GLOBAL_CYPHER, {})]


async def test_run_global_query_refuses_a_tenant_statement_on_a_scoped_transaction(
    registry: QueryRegistry,
) -> None:
    stub = _StubTx()
    with pytest.raises(GlobalStatementMisuse):
        await run_global_query(ScopedTx(stub, A1), registry.get("Q-SCOPED"))  # type: ignore[arg-type]
    assert stub.calls == []


async def test_the_observer_sees_a_run_on_a_scoped_transaction_without_the_scope(
    registry: QueryRegistry,
) -> None:
    seen: list[tuple[str, str, int]] = []
    set_query_observer(lambda query_id, mode, rows, ms: seen.append((query_id, mode, rows)))
    await run_query(ScopedTx(_StubTx(), A1), registry.get("Q-SCOPED"), id="x")  # type: ignore[arg-type]
    assert seen == [("Q-SCOPED", "read", 1)]
