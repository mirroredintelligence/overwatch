"""The execution point and the unit of work, for the network scope (TEN-037, DEC-132 item 4,
DEC-542).

`run_query` refuses a statement whose declared kinds do not include the kind of the scope its
transaction carries, refuses a write on a read-only unit, and accepts the `sourceTenant` parameter
only for a network-only statement on a network scope, with a valid tenant id. A unit of work binds
one scope, may be read-only, and cannot be entered inside another unit. The transaction is a
recording stub: no Neo4j.
"""

import dataclasses
from typing import Any, cast

import pytest

from diucs.adapters.outbound.graph_store import driver as driver_module
from diucs.adapters.outbound.graph_store.driver import (
    ScopedTx,
    run_global_query,
    run_query,
    set_query_observer,
)
from diucs.adapters.outbound.graph_store.queries import (
    BOTH_KINDS,
    NETWORK_KINDS,
    NamedQuery,
    QueryRegistry,
    Scenario,
)
from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork, RepositoryFactory
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.tenancy import (
    ReadOnlyUnitWrite,
    ScopeId,
    ScopeKindMismatch,
    SourceTenantRefused,
    UnitOfWorkAlreadyOpen,
    bind_network,
    bind_tenant,
)
from tests.support.fake_neo4j import FakeDriver

SCENARIO = Scenario("placeholder until TEN-060")
A1 = ScopeId.tenant("a1")
NET = ScopeId.network("net-pilot")

TENANT_READ = "MATCH (n:Observation {id: $id, tenantId: $tenant}) RETURN n.id AS id"
TENANT_WRITE = "MATCH (n:Observation {id: $id, tenantId: $tenant}) SET n.x = 1 RETURN n.id AS id"
NETWORK_READ = (
    "MATCH (p:ProjectedService {sourceServiceId: $id, tenantId: $tenant, "
    "sourceTenantId: $sourceTenant}) RETURN p.sourceServiceId AS id"
)
NETWORK_WRITE = (
    "MATCH (p:ProjectedService {sourceServiceId: $id, tenantId: $tenant}) "
    "SET p.active = false RETURN p.sourceServiceId AS id"
)
GENERIC_READ = "MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) RETURN h.lastSeq AS seq"
GENERIC_WRITE = "MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) SET h.lastSeq = $seq RETURN h.lastSeq AS s"


class _Result:
    async def data(self) -> list[dict[str, Any]]:
        return [{"id": "r1"}]


class _Tx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append((cypher, dict(parameters or {})))
        return _Result()


def _statement(
    query_id: str, cypher: str, mode: str, kinds: frozenset[str] | None = None
) -> NamedQuery:
    extra: dict[str, Any] = {} if kinds is None else {"scope_kinds": kinds}
    return NamedQuery(id=query_id, cypher=cypher, mode=mode, scenario=SCENARIO, **extra)  # type: ignore[arg-type]


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> QueryRegistry:
    new = QueryRegistry()
    for query in (
        _statement("Q-TENANT-READ", TENANT_READ, "read"),
        _statement("Q-TENANT-WRITE", TENANT_WRITE, "write"),
        _statement("Q-NETWORK-READ", NETWORK_READ, "read", NETWORK_KINDS),
        _statement("Q-NETWORK-WRITE", NETWORK_WRITE, "write", NETWORK_KINDS),
        _statement("Q-GENERIC-READ", GENERIC_READ, "read", BOTH_KINDS),
        _statement("Q-GENERIC-WRITE", GENERIC_WRITE, "write", BOTH_KINDS),
    ):
        new.register(query)
    monkeypatch.setattr(driver_module, "REGISTRY", new)
    return new


@pytest.fixture(autouse=True)
def _no_observer() -> None:
    set_query_observer(None)


def _tx(scope: ScopeId, *, read_only: bool = False) -> tuple[ScopedTx, _Tx]:
    stub = _Tx()
    return ScopedTx(cast(Any, stub), scope, read_only), stub


# The kind of the scope


async def test_a_tenant_statement_runs_in_a_tenant_scope_and_is_refused_in_a_network_scope(
    registry: QueryRegistry,
) -> None:
    tx, stub = _tx(A1)
    await run_query(tx, registry.get("Q-TENANT-READ"), id="x")
    assert stub.calls == [(TENANT_READ, {"tenant": "a1", "id": "x"})]
    net_tx, net_stub = _tx(NET)
    with pytest.raises(ScopeKindMismatch):
        await run_query(net_tx, registry.get("Q-TENANT-READ"), id="x")
    assert net_stub.calls == []


async def test_a_network_statement_runs_in_a_network_scope_and_is_refused_in_a_tenant_scope(
    registry: QueryRegistry,
) -> None:
    tx, stub = _tx(NET)
    await run_query(tx, registry.get("Q-NETWORK-READ"), id="x", sourceTenant="a1")
    assert stub.calls == [(NETWORK_READ, {"tenant": "net-pilot", "id": "x", "sourceTenant": "a1"})]
    tenant_tx, tenant_stub = _tx(A1)
    with pytest.raises(ScopeKindMismatch):
        await run_query(tenant_tx, registry.get("Q-NETWORK-READ"), id="x", sourceTenant="a1")
    assert tenant_stub.calls == []


@pytest.mark.parametrize("scope", [A1, NET])
async def test_a_statement_for_both_kinds_runs_in_either(
    registry: QueryRegistry, scope: ScopeId
) -> None:
    tx, stub = _tx(scope)
    await run_query(tx, registry.get("Q-GENERIC-READ"))
    assert stub.calls == [(GENERIC_READ, {"tenant": scope.value})]


async def test_the_kind_check_comes_before_any_cypher_whatever_the_bound_context_says(
    registry: QueryRegistry,
) -> None:
    tx, stub = _tx(NET)
    with bind_tenant("a1"), pytest.raises(ScopeKindMismatch):
        await run_query(tx, registry.get("Q-TENANT-READ"), id="x")
    assert stub.calls == []


async def test_the_tenant_parameter_and_a_global_statement_are_still_refused_first(
    registry: QueryRegistry,
) -> None:
    from diucs.application.tenancy import TenantParameterRefused

    tx, stub = _tx(NET)
    with pytest.raises(TenantParameterRefused):
        await run_query(tx, registry.get("Q-NETWORK-READ"), id="x", tenant="a1")
    assert stub.calls == []


# $sourceTenant


@pytest.mark.parametrize("value", ["", "net-pilot", "A1", "a", "a1/b", 7, None, ("a1",)])
async def test_a_source_tenant_that_is_not_a_tenant_id_is_refused(
    registry: QueryRegistry, value: object
) -> None:
    tx, stub = _tx(NET)
    with pytest.raises(SourceTenantRefused):
        await run_query(tx, registry.get("Q-NETWORK-READ"), id="x", sourceTenant=value)
    assert stub.calls == []


async def test_a_source_tenant_is_refused_for_a_statement_that_is_not_network_only(
    registry: QueryRegistry,
) -> None:
    for query_id in ("Q-GENERIC-READ", "Q-TENANT-READ"):
        tx, stub = _tx(NET if query_id == "Q-GENERIC-READ" else A1)
        with pytest.raises(SourceTenantRefused):
            await run_query(tx, registry.get(query_id), id="x", sourceTenant="a1")
        assert stub.calls == []


async def test_a_global_statement_is_never_given_a_source_tenant(registry: QueryRegistry) -> None:
    from diucs.adapters.outbound.graph_store.queries import GLOBAL_STATEMENTS  # noqa: F401

    ping = NamedQuery(id="Q-NEO4J-PING", cypher="RETURN 1 AS ok", mode="read", scope="global")
    own = QueryRegistry()
    own.register(ping)
    stub = _Tx()
    with pytest.raises(SourceTenantRefused):
        await run_global_query(cast(Any, stub), ping, registry=own, sourceTenant="a1")
    assert stub.calls == []


# Read-only


def test_a_scoped_transaction_has_a_read_only_flag_that_is_off_by_default() -> None:
    assert [f.name for f in dataclasses.fields(ScopedTx)] == ["tx", "scope", "read_only"]
    assert ScopedTx(cast(Any, _Tx()), A1).read_only is False


async def test_a_read_only_transaction_runs_a_read_and_refuses_every_write(
    registry: QueryRegistry,
) -> None:
    tx, stub = _tx(NET, read_only=True)
    await run_query(tx, registry.get("Q-NETWORK-READ"), id="x", sourceTenant="a1")
    await run_query(tx, registry.get("Q-GENERIC-READ"))
    assert len(stub.calls) == 2
    for query_id, params in (
        ("Q-NETWORK-WRITE", {"id": "x"}),
        ("Q-GENERIC-WRITE", {"seq": 1}),
    ):
        with pytest.raises(ReadOnlyUnitWrite):
            await run_query(tx, registry.get(query_id), **params)
    assert len(stub.calls) == 2
    tenant_tx, tenant_stub = _tx(A1, read_only=True)
    with pytest.raises(ReadOnlyUnitWrite):
        await run_query(tenant_tx, registry.get("Q-TENANT-WRITE"), id="x")
    assert tenant_stub.calls == []


async def test_a_transaction_that_is_not_read_only_writes(registry: QueryRegistry) -> None:
    tx, stub = _tx(NET)
    await run_query(tx, registry.get("Q-NETWORK-WRITE"), id="x")
    assert stub.calls[0][1] == {"tenant": "net-pilot", "id": "x"}


# The unit of work


def _unit(*, read_only: bool = False, factories: dict[str, RepositoryFactory] | None = None) -> Any:
    return Neo4jUnitOfWork(
        cast(Any, FakeDriver()), {} if factories is None else factories, None, read_only=read_only
    )


async def test_a_unit_of_work_in_a_network_scope_binds_that_scope() -> None:
    with bind_network("net-pilot"):
        async with _unit() as uow:
            assert uow.unit_scope == NET
            assert uow.read_only is False


async def test_a_read_only_unit_hands_its_repositories_a_read_only_transaction() -> None:
    received: list[Any] = []

    def make(tx: Any, store: object) -> object:
        received.append(tx)
        return object()

    with bind_network("net-pilot"):
        async with _unit(read_only=True, factories={"probe": make}) as uow:
            assert uow.read_only is True
            _ = uow.probe
    [tx] = received
    assert isinstance(tx, ScopedTx)
    assert tx.read_only is True
    assert tx.scope == NET


async def test_committing_a_read_only_unit_rolls_back_and_does_not_commit() -> None:
    driver = FakeDriver()
    unit = Neo4jUnitOfWork(cast(Any, driver), {}, None, read_only=True)
    with bind_network("net-pilot"):
        async with unit as uow:
            await uow.commit()
    [tx] = driver.transactions
    assert tx.rolled_back is True
    assert tx.committed is False
    assert driver.closed_sessions == 1


async def test_a_unit_that_is_not_read_only_commits() -> None:
    driver = FakeDriver()
    unit = Neo4jUnitOfWork(cast(Any, driver), {}, None)
    with bind_network("net-pilot"):
        async with unit as uow:
            await uow.commit()
    assert driver.transactions[0].committed is True


async def test_a_unit_cannot_be_entered_inside_another_whatever_the_kinds() -> None:
    with bind_tenant("a1"):
        async with _unit():
            with bind_network("net-pilot"), pytest.raises(UnitOfWorkAlreadyOpen):
                async with _unit():
                    pass
    with bind_network("net-pilot"):
        async with _unit(read_only=True):
            with bind_tenant("a1"), pytest.raises(UnitOfWorkAlreadyOpen):
                async with _unit():
                    pass
    # The place is given back: the next unit opens.
    with bind_network("net-pilot"):
        async with _unit() as uow:
            assert uow.unit_scope == NET


async def test_the_unit_port_has_the_read_only_property() -> None:
    import typing

    assert "read_only" in typing.get_protocol_members(UnitOfWork)
