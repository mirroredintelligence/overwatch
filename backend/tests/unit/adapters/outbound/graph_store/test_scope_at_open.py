"""Every code path that opens a transaction outside a unit of work reads the scope once, before it
opens a session, and carries it on a `ScopedTx` (TEN-002, audit A 7.1 items 3, 4 and 7):
`DriverIdempotencyStore`, `ensure_audit_head` and the connection's scoped helpers. The health ping
and the migration runner stay on the global path.

A recording fake driver stands in for Neo4j (tests/support/fake_neo4j.py). Some tests make the fake
run the managed-transaction callback twice, as the real driver does after a transient error, and
rebind the ambient scope between the two calls: a retry must use the scope captured at the start.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, cast

import pytest

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store import connection as connection_module
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.health import (
    PING_QUERY_ID,
    HealthStatus,
    neo4j_health,
)
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.graph_store.queries import (
    GLOBAL_QUERY_IDS,
    REGISTRY,
    NamedQuery,
    QueryRegistry,
    Scenario,
)
from diucs.application.ports.outbound.audit import GENESIS_HASH, genesis_hash_for
from diucs.application.tenancy import (
    DEFAULT_TENANT_ID,
    GlobalStatementMisuse,
    ScopeId,
    TenantNotBound,
    bind_tenant,
)
from diucs.domain.codes import Role
from tests.support.fake_neo4j import FakeDriver, FakeTx

A1 = ScopeId.tenant("a1")
PROBE_CYPHER = "MATCH (n:Probe {id: $id, tenantId: $tenant}) RETURN n.id AS id"


@contextmanager
def _rebinding_between_attempts(driver: FakeDriver, tenant: str) -> Iterator[None]:
    """Make the fake bind `tenant` just before its second attempt, and undo it afterwards."""
    binding: list[AbstractContextManager[ScopeId]] = []

    def rebind() -> None:
        binding.append(bind_tenant(tenant))
        binding[0].__enter__()

    driver.between_attempts = rebind
    driver.attempts = 2
    try:
        yield
    finally:
        for entered in binding:
            entered.__exit__(None, None, None)


def _probe_registry() -> QueryRegistry:
    registry = QueryRegistry()
    registry.register(
        NamedQuery(
            id="Q-PROBE",
            cypher=PROBE_CYPHER,
            mode="read",
            scenario=Scenario("placeholder until TEN-004"),
        )
    )
    return registry


async def _probe(tx: object, registry: QueryRegistry, id: str = "x") -> list[dict[str, Any]]:
    return await run_query(tx, registry.get("Q-PROBE"), registry=registry, id=id)  # type: ignore[arg-type]


# DriverIdempotencyStore


async def test_the_idempotency_store_sends_the_bound_scope_on_get_and_put() -> None:
    fake = FakeDriver()
    store = DriverIdempotencyStore(cast(Any, fake))
    with bind_tenant("a1"):
        assert await store.get("key-1") is None
        await store.put("key-1", Role.REPORTER)
    assert fake.calls
    assert set(fake.tenants_sent()) == {"a1"}


async def test_the_idempotency_store_with_nothing_bound_is_refused_before_any_statement() -> None:
    # TEN-016 converted the replay statements: with no scope bound they refuse (fail closed), so
    # no statement reaches the driver, with or without a tenant.
    fake = FakeDriver()
    store = DriverIdempotencyStore(cast(Any, fake))
    with pytest.raises(TenantNotBound):
        await store.get("key-1")
    with pytest.raises(TenantNotBound):
        await store.put("key-1", Role.REPORTER)
    assert fake.tenants_sent() == []


async def test_the_idempotency_store_scope_is_the_one_at_the_start_when_the_driver_retries() -> (
    None
):
    fake = FakeDriver()
    store = DriverIdempotencyStore(cast(Any, fake))
    with bind_tenant("a1"), _rebinding_between_attempts(fake, "b1"):
        await store.get("key-1")
    assert fake.tenants_sent() == ["a1", "a1"]


async def test_a_put_keeps_the_scope_at_the_start_when_the_driver_retries_it() -> None:
    fake = FakeDriver()
    store = DriverIdempotencyStore(cast(Any, fake))
    with bind_tenant("a1"), _rebinding_between_attempts(fake, "b1"):
        await store.put("key-1", Role.REPORTER)
    # Three statements per attempt (read the head, create, link), and two attempts.
    assert fake.tenants_sent() == ["a1"] * 6


# ensure_audit_head


async def test_ensure_audit_head_sends_the_bound_scope_and_that_scopes_own_genesis() -> None:
    fake = FakeDriver()
    with bind_tenant("a1"):
        await ensure_audit_head(cast(Any, fake))
    assert [params for _, params in fake.calls] == [
        {"tenant": "a1", "genesis": genesis_hash_for("a1")}
    ]


async def test_ensure_audit_head_for_the_default_tenant_keeps_the_original_genesis() -> None:
    fake = FakeDriver()
    with bind_tenant(DEFAULT_TENANT_ID):
        await ensure_audit_head(cast(Any, fake))
    assert [params for _, params in fake.calls] == [
        {"tenant": DEFAULT_TENANT_ID, "genesis": GENESIS_HASH}
    ]


async def test_ensure_audit_head_with_nothing_bound_is_refused_before_any_statement() -> None:
    # TEN-017: the chain head is per scope, so there is no head to make without a scope (fail
    # closed): nothing is sent, and there is no default chain to fall back on.
    fake = FakeDriver()
    with pytest.raises(TenantNotBound):
        await ensure_audit_head(cast(Any, fake))
    assert fake.calls == []


async def test_ensure_audit_head_scope_is_the_one_at_the_start_when_the_driver_retries() -> None:
    fake = FakeDriver()
    with bind_tenant("a1"), _rebinding_between_attempts(fake, "b1"):
        await ensure_audit_head(cast(Any, fake))
    assert fake.tenants_sent() == ["a1", "a1"]


# The connection's scoped helpers


@pytest.fixture
async def connection(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = FakeDriver()
    monkeypatch.setattr(connection_module, "create_driver", lambda *a, **k: fake)
    conn = Neo4jConnection("bolt://localhost:1", "user", "password")
    await conn.open()
    conn.fake = fake  # type: ignore[attr-defined]
    return conn


@pytest.mark.parametrize("method", ["run_scoped_read", "run_scoped_write"])
async def test_a_scoped_helper_hands_the_work_a_scoped_transaction_carrying_the_bound_scope(
    connection: Neo4jConnection, method: str
) -> None:
    received: list[object] = []
    registry = _probe_registry()

    async def work(tx: ScopedTx) -> list[dict[str, Any]]:
        received.append(tx)
        return await _probe(tx, registry)

    with bind_tenant("a1"):
        await getattr(connection, method)(work)
    [tx] = received
    assert isinstance(tx, ScopedTx)
    assert tx.scope == A1
    assert cast(Any, connection).fake.tenants_sent() == ["a1"]
    assert connection.open_session_count == 0


@pytest.mark.parametrize("method", ["run_scoped_read", "run_scoped_write"])
async def test_a_scoped_helper_with_nothing_bound_refuses_and_opens_no_session(
    connection: Neo4jConnection, method: str
) -> None:
    received: list[ScopedTx] = []

    async def work(tx: ScopedTx) -> None:
        received.append(tx)

    with pytest.raises(TenantNotBound):
        await getattr(connection, method)(work)
    assert received == []
    assert connection.open_session_count == 0


@pytest.mark.parametrize("method", ["run_scoped_read", "run_scoped_write"])
async def test_a_scoped_helper_keeps_the_scope_it_captured_when_the_driver_retries(
    connection: Neo4jConnection, method: str
) -> None:
    registry = _probe_registry()
    fake = cast(Any, connection).fake

    async def work(tx: ScopedTx) -> None:
        await _probe(tx, registry)

    with bind_tenant("a1"), _rebinding_between_attempts(fake, "b1"):
        await getattr(connection, method)(work)
    assert fake.tenants_sent() == ["a1", "a1"]


@pytest.mark.parametrize("method", ["run_scoped_read", "run_scoped_write"])
async def test_a_scoped_helper_closes_its_session_when_the_work_fails(
    connection: Neo4jConnection, method: str
) -> None:
    async def work(tx: ScopedTx) -> None:
        raise ValueError("stop")

    with bind_tenant("a1"), pytest.raises(ValueError, match="stop"):
        await getattr(connection, method)(work)
    assert connection.open_session_count == 0


async def test_run_read_and_run_write_still_hand_the_work_a_raw_transaction(
    connection: Neo4jConnection,
) -> None:
    received: list[object] = []

    async def work(tx: object) -> None:
        received.append(tx)

    with bind_tenant("a1"):
        await connection.run_read(work)  # type: ignore[arg-type]
        await connection.run_write(work)  # type: ignore[arg-type]
    assert len(received) == 2
    assert not any(isinstance(tx, ScopedTx) for tx in received)


# Health stays on the global path


async def test_the_ping_is_a_global_statement_that_run_query_refuses() -> None:
    ping = REGISTRY.get(PING_QUERY_ID)
    assert ping.scope == "global"
    assert PING_QUERY_ID in GLOBAL_QUERY_IDS
    with bind_tenant("a1"), pytest.raises(GlobalStatementMisuse):
        await run_query(FakeTx([]), ping)  # type: ignore[arg-type]


@pytest.mark.parametrize("bound", [False, True])
async def test_the_health_ping_is_ok_and_carries_no_tenant_bound_or_not(
    connection: Neo4jConnection, bound: bool
) -> None:
    fake = cast(Any, connection).fake
    fake.rows = [{"ok": 1}]
    if bound:
        with bind_tenant("a1"):
            health = await neo4j_health(connection, timeout=5)
    else:
        health = await neo4j_health(connection, timeout=5)
    assert health.status is HealthStatus.OK
    assert [params for _, params in fake.calls] == [{}]


# The registry refuses a global id registered as a tenant statement


@pytest.mark.parametrize(
    "cypher",
    [PROBE_CYPHER, "RETURN 1 AS ok"],
    ids=["mentions the tenant", "does not"],
)
def test_the_global_ping_id_cannot_be_registered_as_a_tenant_statement(cypher: str) -> None:
    registry = QueryRegistry()
    with pytest.raises(ValueError, match=PING_QUERY_ID):
        registry.register(
            NamedQuery(
                id=PING_QUERY_ID,
                cypher=cypher,
                mode="read",
                scenario=Scenario("placeholder until TEN-004"),
            )
        )


def test_the_ping_registers_as_a_global_statement() -> None:
    registry = QueryRegistry()
    registry.register(
        NamedQuery(id=PING_QUERY_ID, cypher="RETURN 1 AS ok", mode="read", scope="global")
    )
    assert registry.get(PING_QUERY_ID).scope == "global"
