"""The one execution point (TEN-001, DEC-142): `run_query` takes a registered NamedQuery and
nothing else, binds the tenant from the context, and refuses before any Cypher is sent.

The reused behaviour (the tenant parameter, the refusal of a caller-supplied `tenant` and of
`parameters`) comes from the verified earlier branch; each of those tests was run against this
code. The transaction is a recording stub: no Neo4j.
"""

import logging
from types import MappingProxyType
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store import driver as driver_module
from diucs.adapters.outbound.graph_store import queries as queries_module
from diucs.adapters.outbound.graph_store.driver import (
    create_driver,
    run_global_query,
    run_query,
    set_query_observer,
)
from diucs.adapters.outbound.graph_store.queries import (
    BOTH_KINDS as BOTH,
)
from diucs.adapters.outbound.graph_store.queries import (
    NamedQuery,
    QueryRegistry,
    Scenario,
    statement_digest,
)
from diucs.application.tenancy import (
    GLOBAL_STATEMENT_MESSAGE,
    QUERY_NOT_REGISTERED_MESSAGE,
    RAW_TRANSACTION_MESSAGE,
    TENANT_PARAMETER_MESSAGE,
    GlobalStatementMisuse,
    QueryNotRegistered,
    RawTransactionRefused,
    ScopeId,
    TenantParameterRefused,
    bind_scope,
    bind_tenant,
)
from tests.support.scoped import OpenTx

SECRET_CYPHER = (
    "MATCH (n:Observation {tenantId: $tenant}) WHERE n.marker = 'secret-cypher-marker' RETURN n"
)
SCOPED_CYPHER = "MATCH (n:Observation {id: $id, tenantId: $tenant}) RETURN n.id AS id"
OTHER_CYPHER = (
    "MATCH (n:Observation {id: $id, marker: 'secret-cypher-marker', tenantId: $tenant}) "
    "RETURN n.id AS id"
)
GLOBAL_CYPHER = "RETURN 1 AS ok"
SECRET_PARAM = "secret-param-marker"
SECRET_TENANT = "secret-tenant-marker"
SCENARIO = Scenario("placeholder until TEN-004")

# A well-formed statement that no registry knows.
_UNKNOWN = NamedQuery(id="Q-UNKNOWN", cypher=SCOPED_CYPHER, mode="read", scenario=SCENARIO)


class _StubResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def data(self) -> list[dict[str, Any]]:
        return self._rows


class _StubTx:
    """Stands in for AsyncManagedTransaction: records what it was asked to run."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(
        self, cypher: str, parameters: dict[str, Any] | None = None, **kwparameters: Any
    ) -> _StubResult:
        # What the real driver does: neo4j 6.4.1 builds dict(parameters or {}, **kwparameters).
        self.calls.append((cypher, dict(parameters or {}, **kwparameters)))
        return _StubResult(self._rows)


class _RawTx:
    """Records exactly how run was called, to show that the parameters travel as one dict."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def run(self, *args: Any, **kwargs: Any) -> _StubResult:
        self.calls.append((args, kwargs))
        return _StubResult([{"id": "r1"}])


def _new_registry() -> QueryRegistry:
    """Two tenant statements and the global ping."""
    registry = QueryRegistry()
    registry.register(
        NamedQuery(id="Q-SCOPED", cypher=SCOPED_CYPHER, mode="read", scenario=SCENARIO)
    )
    registry.register(NamedQuery(id="Q-X", cypher=OTHER_CYPHER, mode="read", scenario=SCENARIO))
    registry.register(
        NamedQuery(id="Q-NEO4J-PING", cypher=GLOBAL_CYPHER, mode="read", scope="global")
    )
    return registry


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> QueryRegistry:
    """run_query looks queries up in REGISTRY; point it at a registry owned by this test."""
    new = _new_registry()
    monkeypatch.setattr(driver_module, "REGISTRY", new)
    return new


def _q(registry: QueryRegistry, query_id: str) -> NamedQuery:
    return registry.get(query_id)


def _raw(rows: list[dict[str, Any]] | None = None) -> _StubTx:
    """A raw transaction: `run_query` refuses it (TEN-030)."""
    return _StubTx(rows=[{"id": "r1"}] if rows is None else rows)


def _stub(
    rows: list[dict[str, Any]] | None = None, scope: ScopeId | str = "a1", raw: Any = None
) -> Any:
    """The transaction a unit of work hands a repository: a ScopedTx for `scope` (a tenant id or a
    scope id) that also gives the test the stub's `calls`."""
    where = scope if isinstance(scope, ScopeId) else ScopeId.tenant(scope)
    return OpenTx(_raw(rows) if raw is None else raw, where)


@pytest.fixture(autouse=True)
def _no_observer() -> Any:
    set_query_observer(None)
    yield
    set_query_observer(None)


# The observer and the logs never see the Cypher text, a parameter or the scope


async def test_observer_receives_id_mode_row_count_and_a_non_negative_duration(
    registry: QueryRegistry,
) -> None:
    registry.register(NamedQuery(id="Q-OBS", cypher=SECRET_CYPHER, mode="read", scenario=SCENARIO))
    seen: list[tuple[str, str, int, float]] = []
    set_query_observer(lambda q_id, mode, rows, ms: seen.append((q_id, mode, rows, ms)))

    tx = _stub([{"n": 1}, {"n": 2}])
    await run_query(tx, _q(registry, "Q-OBS"), marker="x")

    assert len(seen) == 1
    q_id, mode, rows, duration_ms = seen[0]
    assert (q_id, mode, rows) == ("Q-OBS", "read", 2)
    assert isinstance(duration_ms, float)
    assert duration_ms >= 0


async def test_observer_sees_no_cypher_text_parameter_or_scope(registry: QueryRegistry) -> None:
    registry.register(
        NamedQuery(id="Q-NO-TEXT", cypher=SECRET_CYPHER, mode="read", scenario=SCENARIO)
    )
    seen: list[tuple[object, ...]] = []
    set_query_observer(lambda *args: seen.append(args))

    with bind_tenant(SECRET_TENANT):
        await run_query(
            _stub([]),
            _q(registry, "Q-NO-TEXT"),
            marker="secret-cypher-marker",
            p=SECRET_PARAM,
        )
        await run_query(_stub([]), _q(registry, "Q-SCOPED"), id=SECRET_PARAM)

    assert len(seen) == 2
    for args in seen:
        for forbidden in ("secret-cypher-marker", SECRET_PARAM, SECRET_TENANT, "Observation"):
            assert all(not (isinstance(arg, str) and forbidden in arg) for arg in args), (
                "the observer must receive the query id, never the Cypher text or parameters"
            )


async def test_run_query_logs_no_cypher_text_parameter_or_scope(
    registry: QueryRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    registry.register(NamedQuery(id="Q-LOG", cypher=SECRET_CYPHER, mode="read", scenario=SCENARIO))

    await run_query(_stub([{"n": 1}]), _q(registry, "Q-LOG"), marker="secret-cypher-marker")
    with bind_tenant(SECRET_TENANT):
        await run_query(_stub([{"n": 1}]), _q(registry, "Q-SCOPED"), id=SECRET_PARAM)

    for forbidden in ("secret-cypher-marker", "Observation", SECRET_PARAM, SECRET_TENANT):
        assert forbidden not in caplog.text


async def test_the_observer_is_called_for_a_global_statement_too(registry: QueryRegistry) -> None:
    seen: list[tuple[object, ...]] = []
    set_query_observer(lambda *args: seen.append(args))
    await run_global_query(_stub([{"ok": 1}]), _q(registry, "Q-NEO4J-PING"))
    assert [args[:3] for args in seen] == [("Q-NEO4J-PING", "read", 1)]


async def test_observer_is_not_called_once_cleared(registry: QueryRegistry) -> None:
    registry.register(
        NamedQuery(id="Q-CLEAR", cypher=SECRET_CYPHER, mode="read", scenario=SCENARIO)
    )
    seen: list[tuple[object, ...]] = []
    set_query_observer(lambda *args: seen.append(args))
    set_query_observer(None)

    await run_query(_stub([]), _q(registry, "Q-CLEAR"))

    assert seen == []


async def test_a_refused_call_does_not_reach_the_observer(registry: QueryRegistry) -> None:
    seen: list[tuple[object, ...]] = []
    set_query_observer(lambda *args: seen.append(args))
    with pytest.raises(RawTransactionRefused):
        await run_query(_raw(), _q(registry, "Q-SCOPED"), id="1")
    with pytest.raises(QueryNotRegistered):
        await run_query(_stub(), "Q-SCOPED", id="1")  # type: ignore[arg-type]
    assert seen == []


# A string or a statement that is not in the registry is refused before the driver is touched


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("query_id", ["Q-SCOPED", "Q-X", "Q-NEO4J-PING", "Q-UNKNOWN"])
async def test_a_string_is_refused_before_the_transaction_is_touched(
    registry: QueryRegistry, query_id: str, bound: bool
) -> None:
    tx = _stub()
    for call in (run_query, run_global_query):
        if bound:
            with bind_tenant("a1"), pytest.raises(QueryNotRegistered) as raised:
                await call(tx, query_id, id="1")  # type: ignore[operator]
        else:
            with pytest.raises(QueryNotRegistered) as raised:
                await call(tx, query_id, id="1")  # type: ignore[operator]
        assert str(raised.value) == QUERY_NOT_REGISTERED_MESSAGE
    assert tx.calls == []


@pytest.mark.parametrize("not_a_query", [SCOPED_CYPHER, None, 3, {"id": "Q-SCOPED"}, ("Q-SCOPED",)])
async def test_anything_that_is_not_a_named_query_is_refused(
    registry: QueryRegistry, not_a_query: object
) -> None:
    tx = _stub()
    with bind_tenant("a1"):
        with pytest.raises(QueryNotRegistered):
            await run_query(tx, not_a_query, id="1")  # type: ignore[arg-type]
        with pytest.raises(QueryNotRegistered):
            await run_global_query(tx, not_a_query, id="1")  # type: ignore[arg-type]
    assert tx.calls == []


async def test_a_query_object_that_was_never_registered_is_refused(registry: QueryRegistry) -> None:
    tx = _stub()
    with bind_tenant("a1"), pytest.raises(QueryNotRegistered):
        await run_query(tx, _UNKNOWN, id="1")
    assert tx.calls == []


async def test_an_object_with_a_registered_id_but_other_text_is_refused(
    registry: QueryRegistry,
) -> None:
    """The text that runs must be the text that was registered: an id is not enough."""
    tx = _stub()
    forged = NamedQuery(
        id="Q-SCOPED",
        cypher="MATCH (n) DETACH DELETE n // $tenant",
        mode="write",
        scenario=SCENARIO,
    )
    with bind_tenant("a1"), pytest.raises(QueryNotRegistered):
        await run_query(tx, forged, id="1")
    assert tx.calls == []


async def test_a_statement_registered_in_another_registry_is_refused_here(
    registry: QueryRegistry,
) -> None:
    other = _new_registry()
    other.register(
        NamedQuery(id="Q-ONLY-THERE", cypher=SCOPED_CYPHER, mode="read", scenario=SCENARIO)
    )
    tx = _stub()
    with bind_tenant("a1"), pytest.raises(QueryNotRegistered):
        await run_query(tx, other.get("Q-ONLY-THERE"), id="1")
    assert tx.calls == []


async def test_the_default_registry_is_the_module_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = QueryRegistry()
    monkeypatch.setattr(driver_module, "REGISTRY", empty)
    tx = _stub()
    with bind_tenant("a1"), pytest.raises(QueryNotRegistered):
        await run_query(tx, _UNKNOWN, id="1")
    assert tx.calls == []


async def test_run_query_uses_the_given_registry_instead(registry: QueryRegistry) -> None:
    other = _new_registry()
    other.register(
        NamedQuery(id="Q-ONLY-HERE", cypher=SCOPED_CYPHER, mode="read", scenario=SCENARIO)
    )
    tx = _stub()
    with bind_tenant("a1"):
        await run_query(tx, other.get("Q-ONLY-HERE"), registry=other, id="1")
        with pytest.raises(QueryNotRegistered):
            await run_query(tx, other.get("Q-ONLY-HERE"), id="1")
    assert len(tx.calls) == 1


# A raw transaction is refused before any Cypher is sent, bound or not


@pytest.mark.parametrize("bound", [False, True])
@pytest.mark.parametrize("query_id", ["Q-SCOPED", "Q-X"])
async def test_a_raw_transaction_is_refused_before_any_cypher_bound_or_not(
    registry: QueryRegistry, query_id: str, bound: bool
) -> None:
    tx = _raw()
    if bound:
        with bind_tenant("a1"), pytest.raises(RawTransactionRefused) as raised:
            await run_query(tx, _q(registry, query_id), id="x")  # type: ignore[arg-type]
    else:
        with pytest.raises(RawTransactionRefused) as raised:
            await run_query(tx, _q(registry, query_id), id="x")  # type: ignore[arg-type]
    assert str(raised.value) == RAW_TRANSACTION_MESSAGE
    assert tx.calls == []


async def test_the_scope_a_transaction_carries_wins_over_the_ambient_scope(
    registry: QueryRegistry,
) -> None:
    tx = _stub(scope="a1")
    with bind_tenant("b1"):
        await run_query(tx, _q(registry, "Q-SCOPED"), id="x")
    assert tx.calls == [(SCOPED_CYPHER, {"tenant": "a1", "id": "x"})]


async def test_a_network_binding_is_a_binding_for_the_execution_point(
    registry: QueryRegistry,
) -> None:
    # A statement for both kinds of scope (TEN-037): a tenant statement is refused in a network one.
    generic = "MATCH (h:AuditHead {id: $id, tenantId: $tenant}) RETURN h.id AS id"
    registry.register(
        NamedQuery(id="Q-GENERIC", cypher=generic, mode="read", scenario=SCENARIO, scope_kinds=BOTH)
    )
    tx = _stub(scope=ScopeId.network("net-pilot"))
    with bind_scope(ScopeId.network("net-pilot")):
        await run_query(tx, _q(registry, "Q-GENERIC"), id="x")
    assert tx.calls == [(generic, {"tenant": "net-pilot", "id": "x"})]


# Bound: the tenant is added from the bound scope and nothing else changes


async def test_a_bound_call_passes_the_unchanged_text_the_tenant_and_the_callers_parameters(
    registry: QueryRegistry,
) -> None:
    tx = _stub([{"id": "r1"}, {"id": "r2"}])
    with bind_tenant("a1"):
        rows = await run_query(tx, _q(registry, "Q-SCOPED"), id="x", other=2)
    assert rows == [{"id": "r1"}, {"id": "r2"}]
    assert tx.calls == [(SCOPED_CYPHER, {"tenant": "a1", "id": "x", "other": 2})]


async def test_the_bound_value_is_what_is_passed_not_a_constant(registry: QueryRegistry) -> None:
    seen: list[object] = []
    for tenant in ("a1", "b2", "ucr-west-1"):
        tx = _stub(scope=tenant)
        with bind_tenant(tenant):
            await run_query(tx, _q(registry, "Q-SCOPED"), id="x")
        seen.append(tx.calls[0][1].get("tenant"))
    assert seen == ["a1", "b2", "ucr-west-1"]


async def test_the_parameters_travel_as_one_dict_after_the_text(registry: QueryRegistry) -> None:
    """neo4j's own `run(query, parameters=None, **kwparameters)` merges a `parameters` keyword with
    the other keywords, so the execution point passes one dict positionally."""
    tx = _stub(raw=_RawTx())
    with bind_tenant("a1"):
        await run_query(tx, _q(registry, "Q-SCOPED"), id="x")
    assert tx.calls == [((SCOPED_CYPHER, {"tenant": "a1", "id": "x"}), {})]


async def test_a_parameter_named_like_a_tenant_but_not_exactly_tenant_is_allowed(
    registry: QueryRegistry,
) -> None:
    tx = _stub()
    with bind_tenant("a1"):
        await run_query(
            tx, _q(registry, "Q-SCOPED"), id="x", tenant_id="t", tenantId="u", Tenant="v"
        )
    assert tx.calls == [
        (
            SCOPED_CYPHER,
            {"tenant": "a1", "id": "x", "tenant_id": "t", "tenantId": "u", "Tenant": "v"},
        )
    ]


# A caller-supplied tenant is refused in every state


@pytest.mark.parametrize("query_id", ["Q-SCOPED", "Q-X", "Q-NEO4J-PING"])
@pytest.mark.parametrize("bound", [False, True])
async def test_a_tenant_parameter_is_refused_bound_or_not_for_every_kind_of_statement(
    registry: QueryRegistry, bound: bool, query_id: str
) -> None:
    tx = _stub()
    query = _q(registry, query_id)
    for call in (run_query, run_global_query):
        if bound:
            with bind_tenant("a1"), pytest.raises(TenantParameterRefused) as raised:
                await call(tx, query, id="x", tenant="evil")
        else:
            with pytest.raises(TenantParameterRefused) as raised:
                await call(tx, query, id="x", tenant="evil")
        assert str(raised.value) == TENANT_PARAMETER_MESSAGE
    assert tx.calls == []


@pytest.mark.parametrize("value", ["evil", "a1", "", None, 0, {"k": "v"}])
async def test_the_refusal_does_not_depend_on_the_value_given(
    registry: QueryRegistry, value: object
) -> None:
    tx = _stub()
    with bind_tenant("a1"), pytest.raises(TenantParameterRefused):
        await run_query(tx, _q(registry, "Q-SCOPED"), id="x", tenant=value)
    assert tx.calls == []


@pytest.mark.parametrize("value", [{"tenant": "evil"}, None, {}, "x"])
async def test_a_parameters_keyword_is_refused_because_it_is_a_second_way_to_pass_a_tenant(
    registry: QueryRegistry, value: object
) -> None:
    tx = _stub()
    with bind_tenant("a1"):
        with pytest.raises(TenantParameterRefused):
            await run_query(tx, _q(registry, "Q-SCOPED"), id="x", parameters=value)
        with pytest.raises(TenantParameterRefused):
            await run_global_query(tx, _q(registry, "Q-NEO4J-PING"), parameters=value)
    assert tx.calls == []


_PARAM_KEYS = st.sampled_from(
    ["id", "tenant", "parameters", "x", "tenant_id", "tenantId", "Tenant", "limit"]
)


@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.dictionaries(_PARAM_KEYS, st.one_of(st.integers(), st.text(max_size=8)), max_size=6))
async def test_for_any_parameters_a_tenant_key_is_refused_and_otherwise_the_bound_value_wins(
    registry: QueryRegistry, params: dict[str, object]
) -> None:
    tx = _stub()
    with bind_tenant("a1"):
        if "tenant" in params or "parameters" in params:
            with pytest.raises(TenantParameterRefused):
                await run_query(tx, _q(registry, "Q-SCOPED"), **params)
            assert tx.calls == []
        else:
            await run_query(tx, _q(registry, "Q-SCOPED"), **params)
            assert tx.calls == [(SCOPED_CYPHER, {"tenant": "a1", **params})]
            assert tx.calls[0][1]["tenant"] == "a1"


# Global statements


async def test_run_query_refuses_a_global_statement_bound_or_not(registry: QueryRegistry) -> None:
    tx = _stub()
    with pytest.raises(GlobalStatementMisuse) as raised:
        await run_query(tx, _q(registry, "Q-NEO4J-PING"))
    with bind_tenant("a1"), pytest.raises(GlobalStatementMisuse):
        await run_query(tx, _q(registry, "Q-NEO4J-PING"))
    assert str(raised.value) == GLOBAL_STATEMENT_MESSAGE
    assert tx.calls == []


@pytest.mark.parametrize("query_id", ["Q-SCOPED", "Q-X"])
async def test_run_global_query_refuses_a_tenant_statement(
    registry: QueryRegistry, query_id: str
) -> None:
    tx = _stub()
    with pytest.raises(GlobalStatementMisuse) as raised:
        await run_global_query(tx, _q(registry, query_id), id="1")
    assert str(raised.value) == GLOBAL_STATEMENT_MESSAGE
    assert tx.calls == []


async def test_run_global_query_runs_a_global_statement_with_no_tenant_parameter(
    registry: QueryRegistry,
) -> None:
    tx = _stub([{"ok": 1}])
    ping = _q(registry, "Q-NEO4J-PING")
    assert await run_global_query(tx, ping) == [{"ok": 1}]
    with bind_tenant("a1"):
        assert await run_global_query(tx, ping, extra=3) == [{"ok": 1}]
    assert tx.calls == [(GLOBAL_CYPHER, {}), (GLOBAL_CYPHER, {"extra": 3})]


async def test_run_global_query_uses_the_given_registry(
    registry: QueryRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A global statement registers only when it is pinned (TEN-007 round 2), so this test pins an
    # id of its own, which the module registry does not hold.
    text = "RETURN 2 AS ok"
    monkeypatch.setattr(
        queries_module,
        "GLOBAL_QUERY_IDS",
        MappingProxyType({**queries_module.GLOBAL_QUERY_IDS, "Q-TEST-OTHER": "x" * 30}),
    )
    monkeypatch.setattr(
        queries_module,
        "GLOBAL_STATEMENTS",
        MappingProxyType(
            {**queries_module.GLOBAL_STATEMENTS, "Q-TEST-OTHER": statement_digest(text)}
        ),
    )
    other = QueryRegistry()
    other.register(NamedQuery(id="Q-TEST-OTHER", cypher=text, mode="read", scope="global"))
    tx = _stub()
    await run_global_query(tx, other.get("Q-TEST-OTHER"), registry=other)
    assert tx.calls == [(text, {})]
    with pytest.raises(QueryNotRegistered):
        await run_global_query(tx, other.get("Q-TEST-OTHER"))
    assert len(tx.calls) == 1


async def test_create_driver_returns_an_async_driver_without_connecting() -> None:
    # Creating a driver opens no socket; the first session does. Closing it must succeed.
    created = create_driver("bolt://localhost:1", "neo4j", "not-a-real-password")
    try:
        assert isinstance(created, AsyncDriver)
    finally:
        await created.close()


async def test_create_driver_sets_the_dec_012_pool_options() -> None:
    created = create_driver("bolt://localhost:1", "neo4j", "not-a-real-password")
    try:
        pool = created._pool.pool_config
        assert pool.max_connection_lifetime == 1800.0
        assert pool.liveness_check_timeout == 30.0
        assert pool.max_connection_pool_size == 50
        assert created._default_workspace_config.connection_acquisition_timeout == 30.0
    finally:
        await created.close()


async def test_create_driver_passes_its_pool_arguments_through() -> None:
    created = create_driver(
        "bolt://localhost:1",
        "neo4j",
        "not-a-real-password",
        max_connection_lifetime=600.0,
        liveness_check_timeout=5.0,
        connection_acquisition_timeout=2.0,
        max_connection_pool_size=7,
    )
    try:
        pool = created._pool.pool_config
        assert pool.max_connection_lifetime == 600.0
        assert pool.liveness_check_timeout == 5.0
        assert pool.max_connection_pool_size == 7
        assert created._default_workspace_config.connection_acquisition_timeout == 2.0
    finally:
        await created.close()
