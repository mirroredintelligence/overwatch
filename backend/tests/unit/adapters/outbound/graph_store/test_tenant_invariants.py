"""The tenant invariant check of the graph store (TEN-031, DEC-134 item 11, audit A 3.3).

Neo4j Community cannot require `tenantId`, and a composite constraint ignores a node that has none,
so a node written without one is invisible to every tenant query. The check counts such nodes, and
the relationships that join two scopes, with two global statements (the allowlist and the digest
pin of DEC-163). It returns label names and counts only: never an id, a property value or a
tenant.

The connection is a stand-in that runs the callback on a recording transaction: no Neo4j. The
behaviour on a real graph is tests/integration/graph_store/test_tenant_invariants.py.
"""

from collections.abc import Awaitable, Callable
from typing import Any, cast

import pytest

from diucs.adapters.outbound.graph_store import invariants as invariants_module
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.health import HealthStatus, invariant_health
from diucs.adapters.outbound.graph_store.invariants import (
    CROSS_SCOPE_QUERY_ID,
    UNSTAMPED_QUERY_ID,
    Neo4jTenantInvariants,
)
from diucs.adapters.outbound.graph_store.migrations_tenant import (
    CROSS_SCOPE_RELATIONSHIPS_QUERY,
    REGISTRY_LABELS,
    UNSTAMPED_NODES_QUERY,
)
from diucs.adapters.outbound.graph_store.queries import GLOBAL_QUERY_IDS, REGISTRY
from diucs.application.ports.outbound.invariants import (
    CrossScope,
    InvariantReport,
    TenantInvariantViolated,
    UnstampedNodes,
)
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.tenant_invariants import InvariantMonitor


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def data(self) -> list[dict[str, Any]]:
        return self._rows


class _Tx:
    def __init__(self, by_text: dict[str, list[dict[str, Any]]]) -> None:
        self._by_text = by_text
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append((cypher, dict(parameters or {})))
        return _Result(self._by_text.get(cypher, []))


class _Connection:
    def __init__(self, tx: _Tx) -> None:
        self.tx = tx
        self.reads = 0

    async def run_read(self, work: Callable[[Any], Awaitable[Any]]) -> Any:
        self.reads += 1
        return await work(self.tx)


def _check(
    unstamped: list[dict[str, Any]] | None = None, crossing: list[dict[str, Any]] | None = None
) -> tuple[Neo4jTenantInvariants, _Tx, _Connection]:
    tx = _Tx(
        {
            UNSTAMPED_NODES_QUERY: unstamped or [],
            CROSS_SCOPE_RELATIONSHIPS_QUERY: crossing or [],
        }
    )
    connection = _Connection(tx)
    return Neo4jTenantInvariants(cast(Neo4jConnection, connection)), tx, connection


# The two statements


def test_the_two_statements_are_global_read_only_and_the_text_of_the_migration_queries() -> None:
    unstamped = REGISTRY.get(UNSTAMPED_QUERY_ID)
    crossing = REGISTRY.get(CROSS_SCOPE_QUERY_ID)
    assert (UNSTAMPED_QUERY_ID, CROSS_SCOPE_QUERY_ID) == (
        "Q-INVARIANT-UNSTAMPED",
        "Q-INVARIANT-CROSS-SCOPE",
    )
    for query in (unstamped, crossing):
        assert query.scope == "global" and query.mode == "read"
        assert query.id in GLOBAL_QUERY_IDS
    # One text for the check and for the migration helper: they cannot drift apart.
    assert unstamped.cypher == UNSTAMPED_NODES_QUERY
    assert crossing.cypher == CROSS_SCOPE_RELATIONSHIPS_QUERY


def test_the_registry_labels_the_check_leaves_out_are_the_ones_of_the_migrations() -> None:
    assert invariants_module.REGISTRY_LABELS == REGISTRY_LABELS
    assert set(REGISTRY_LABELS) >= {"Migration", "Tenant", "TenantNumber"}


# The check


async def test_a_clean_graph_gives_an_ok_report_with_two_reads_in_one_transaction() -> None:
    check, tx, connection = _check()
    report = await check.check()
    assert report == InvariantReport()
    assert report.ok
    assert connection.reads == 1
    assert [cypher for cypher, _ in tx.calls] == [
        UNSTAMPED_NODES_QUERY,
        CROSS_SCOPE_RELATIONSHIPS_QUERY,
    ]


async def test_the_unstamped_count_is_sent_the_registry_labels_and_nothing_else() -> None:
    check, tx, _ = _check()
    await check.check()
    assert tx.calls[0][1] == {"registryLabels": list(REGISTRY_LABELS)}
    assert tx.calls[1][1] == {}
    for _, parameters in tx.calls:
        assert "tenant" not in parameters


@pytest.mark.parametrize("bound", [False, True])
async def test_the_check_is_the_same_with_no_tenant_bound_or_any_tenant_bound(bound: bool) -> None:
    check, tx, _ = _check(unstamped=[{"labels": ["Observation"], "n": 2}])
    if bound:
        with bind_tenant("tenant-a"):
            report = await check.check()
    else:
        report = await check.check()
    assert report.unstamped == (UnstampedNodes(("Observation",), 2),)
    assert all("tenant" not in parameters for _, parameters in tx.calls)


async def test_unstamped_nodes_and_crossing_relationships_are_counted_by_label_and_type() -> None:
    check, _, _ = _check(
        unstamped=[
            {"labels": ["Resource", "Observation"], "n": 2},
            {"labels": ["Person"], "n": 1},
        ],
        crossing=[{"type": "ABOUT", "n": 3}],
    )
    report = await check.check()
    assert not report.ok
    assert report.unstamped_total == 3
    assert report.cross_scope_total == 3
    assert report.unstamped == (
        UnstampedNodes(("Observation", "Resource"), 2),
        UnstampedNodes(("Person",), 1),
    )
    assert report.cross_scope == (CrossScope("ABOUT", 3),)


async def test_a_row_the_graph_gave_with_an_unexpected_shape_is_not_swallowed() -> None:
    check, _, _ = _check(unstamped=[{"labels": ["X"]}])
    with pytest.raises(KeyError):
        await check.check()


# The report and its words


def test_the_summary_names_labels_types_and_counts_and_nothing_else() -> None:
    report = InvariantReport(
        unstamped=(UnstampedNodes(("Observation", "Resource"), 2), UnstampedNodes(("Person",), 1)),
        cross_scope=(CrossScope("ABOUT", 3),),
    )
    summary = report.summary()
    assert "3 node" in summary and "Observation" in summary and "Resource" in summary
    assert "ABOUT" in summary and "3 relationship" in summary


def test_a_clean_summary_says_so() -> None:
    assert "no node" in InvariantReport().summary().lower() or "hold" in InvariantReport().summary()


def test_the_violation_error_carries_the_report_and_its_summary() -> None:
    report = InvariantReport(unstamped=(UnstampedNodes(("Person",), 1),))
    error = TenantInvariantViolated(report)
    assert error.report is report
    assert report.summary() in str(error)
    assert isinstance(error, RuntimeError)


def test_an_ok_report_has_zero_totals() -> None:
    report = InvariantReport()
    assert (report.unstamped_total, report.cross_scope_total) == (0, 0)


# The flag a process holds


def test_a_new_monitor_has_seen_nothing_and_flags_nothing() -> None:
    monitor = InvariantMonitor()
    assert monitor.raised is False
    assert monitor.report is None


def test_a_violation_raises_the_flag_and_a_clean_check_clears_it() -> None:
    monitor = InvariantMonitor()
    monitor.record(InvariantReport(unstamped=(UnstampedNodes(("Person",), 1),)))
    assert monitor.raised is True
    monitor.record(InvariantReport())
    assert monitor.raised is False


def test_health_is_ok_until_a_check_finds_a_violation_and_names_only_counts() -> None:
    monitor = InvariantMonitor()
    assert invariant_health(monitor).status is HealthStatus.OK
    report = InvariantReport(unstamped=(UnstampedNodes(("Person",), 4),))
    monitor.record(report)
    health = invariant_health(monitor)
    assert health.status is HealthStatus.DEGRADED
    assert "4" in health.reason and "Person" in health.reason
    monitor.record(InvariantReport())
    assert invariant_health(monitor).status is HealthStatus.OK
