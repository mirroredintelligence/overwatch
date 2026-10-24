from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store import driver as driver_module
from diucs.adapters.outbound.graph_store.driver import (
    create_driver,
    run_query,
    set_query_observer,
)
from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry

SECRET_CYPHER = "MATCH (n:Observation) WHERE n.marker = 'secret-cypher-marker' RETURN n"


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

    async def run(self, cypher: str, **params: Any) -> _StubResult:
        self.calls.append((cypher, params))
        return _StubResult(self._rows)


@pytest.fixture
def local_registry(monkeypatch: pytest.MonkeyPatch) -> QueryRegistry:
    """run_query looks queries up in REGISTRY; point it at a registry owned by this test."""
    registry = QueryRegistry()
    monkeypatch.setattr(driver_module, "REGISTRY", registry)
    return registry


@pytest.fixture(autouse=True)
def _no_observer() -> Any:
    set_query_observer(None)
    yield
    set_query_observer(None)


async def test_observer_receives_id_mode_row_count_and_a_non_negative_duration(
    local_registry: QueryRegistry,
) -> None:
    local_registry.register(NamedQuery(id="Q-OBS", cypher=SECRET_CYPHER, mode="read"))
    seen: list[tuple[str, str, int, float]] = []
    set_query_observer(lambda q_id, mode, rows, ms: seen.append((q_id, mode, rows, ms)))

    tx = _StubTx(rows=[{"n": 1}, {"n": 2}])
    await run_query(tx, "Q-OBS", marker="x")

    assert len(seen) == 1
    q_id, mode, rows, duration_ms = seen[0]
    assert (q_id, mode, rows) == ("Q-OBS", "read", 2)
    assert isinstance(duration_ms, float)
    assert duration_ms >= 0


async def test_observer_sees_no_cypher_text(local_registry: QueryRegistry) -> None:
    local_registry.register(NamedQuery(id="Q-NO-TEXT", cypher=SECRET_CYPHER, mode="read"))
    seen: list[tuple[object, ...]] = []
    set_query_observer(lambda *args: seen.append(args))

    await run_query(_StubTx(rows=[]), "Q-NO-TEXT", marker="secret-cypher-marker")

    assert len(seen) == 1
    assert all(not (isinstance(arg, str) and "secret-cypher-marker" in arg) for arg in seen[0]), (
        "the observer must receive the query id, never the Cypher text or parameters"
    )


async def test_run_query_returns_records_as_dicts_and_passes_parameters(
    local_registry: QueryRegistry,
) -> None:
    local_registry.register(NamedQuery(id="Q-ECHO", cypher="RETURN $x AS x", mode="read"))
    tx = _StubTx(rows=[{"x": 1}])

    rows = await run_query(tx, "Q-ECHO", x=1)

    assert rows == [{"x": 1}]
    assert tx.calls == [("RETURN $x AS x", {"x": 1})]


async def test_run_query_with_an_unknown_id_raises_key_error(
    local_registry: QueryRegistry,
) -> None:
    with pytest.raises(KeyError, match="Q-UNKNOWN"):
        await run_query(_StubTx(rows=[]), "Q-UNKNOWN")


async def test_observer_is_not_called_once_cleared(local_registry: QueryRegistry) -> None:
    local_registry.register(NamedQuery(id="Q-CLEAR", cypher="RETURN 1", mode="read"))
    seen: list[tuple[object, ...]] = []
    set_query_observer(lambda *args: seen.append(args))
    set_query_observer(None)

    await run_query(_StubTx(rows=[]), "Q-CLEAR")

    assert seen == []


async def test_create_driver_returns_an_async_driver_without_connecting() -> None:
    # Creating a driver opens no socket; the first session does. Closing it must succeed.
    created = create_driver("bolt://localhost:1", "neo4j", "not-a-real-password")
    try:
        assert isinstance(created, AsyncDriver)
    finally:
        await created.close()
