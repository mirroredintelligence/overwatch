"""The tenant invariant check on a real Neo4j (TEN-031, DEC-134 item 11).

Neo4j Community cannot require `tenantId`, so a node written without one is invisible to every
tenant query: a service that vanishes from the board reads as "not listed". The check counts such
nodes (outside the registry labels), and the relationships that join two scopes, with two global
statements. It reads the whole graph and returns label names and counts, never a value: the data
carries a marker text that must not appear in any report. Registry nodes are seeded with raw
Cypher (test code). The start-up refusal is shown end to end on a container.
"""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import set_query_observer
from diucs.adapters.outbound.graph_store.invariants import Neo4jTenantInvariants
from diucs.adapters.outbound.graph_store.migrations_tenant import REGISTRY_LABELS
from diucs.application.ports.outbound.invariants import (
    CrossScope,
    TenantInvariantViolated,
    UnstampedNodes,
)
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.container import build_for_tests
from tests.support.neo4j import count_nodes, wipe, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

A, B = "alpha-icb", "bravo-trust"
MARKER = "DATA-MARKER-must-never-leave-the-graph"


@pytest_asyncio.fixture(loop_scope="session")
async def connection(harness_driver: AsyncDriver) -> AsyncIterator[Neo4jConnection]:
    conn = Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )
    await conn.open()
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _empty_graph(clean_graph: None, harness_driver: AsyncDriver) -> AsyncIterator[None]:
    yield
    await wipe(harness_driver)


async def _run(driver: AsyncDriver, cypher: str, **params: Any) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(cypher, params)

    await write_tx(driver, work)


async def test_an_empty_graph_holds_the_invariants(
    connection: Neo4jConnection,
) -> None:
    report = await Neo4jTenantInvariants(connection).check()
    assert report.ok
    assert (report.unstamped_total, report.cross_scope_total) == (0, 0)


async def test_stamped_nodes_of_two_tenants_hold_the_invariants(
    connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    await _run(
        harness_driver,
        "CREATE (a:Observation {id: 'o-1', tenantId: $a, note: $m}), "
        "(b:Observation {id: 'o-1', tenantId: $b, note: $m}), "
        "(a)-[:NEXT]->(:Person {tenantId: $a})",
        a=A,
        b=B,
        m=MARKER,
    )
    assert (await Neo4jTenantInvariants(connection).check()).ok


@pytest.mark.parametrize("label", REGISTRY_LABELS)
async def test_a_registry_node_with_no_tenant_is_not_a_violation(
    connection: Neo4jConnection, harness_driver: AsyncDriver, label: str
) -> None:
    await _run(harness_driver, f"CREATE (:`{label}` {{id: 'registry-1', note: $m}})", m=MARKER)
    try:
        assert (await Neo4jTenantInvariants(connection).check()).ok
    finally:
        # The clean-graph wipe keeps every :Migration node, so a probe of that label would count
        # as a recorded migration for every later test on the shared harness.
        await _run(harness_driver, "MATCH (n:Migration {id: 'registry-1'}) DETACH DELETE n")


async def test_a_node_with_no_tenant_is_counted_by_its_labels_and_leaks_no_value(
    connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    await _run(
        harness_driver,
        "CREATE (:Observation:Resource {id: 'o-1', note: $m}), "
        "(:Observation:Resource {id: 'o-2', note: $m}), (:Person {id: 'p-1', note: $m}), "
        "(:Observation {id: 'o-3', tenantId: $a, note: $m})",
        a=A,
        m=MARKER,
    )

    report = await Neo4jTenantInvariants(connection).check()

    assert not report.ok
    assert report.unstamped_total == 3
    assert set(report.unstamped) == {
        UnstampedNodes(("Observation", "Resource"), 2),
        UnstampedNodes(("Person",), 1),
    }
    for text in (report.summary(), repr(report), str(TenantInvariantViolated(report))):
        assert MARKER not in text
        assert "o-1" not in text and "p-1" not in text


async def test_a_node_whose_tenant_was_erased_is_found(
    connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    """`SET n = props` erases `tenantId`: the case old code can still cause."""
    await _run(harness_driver, "CREATE (:Observation {id: 'o-1', tenantId: $a})", a=A)
    assert (await Neo4jTenantInvariants(connection).check()).ok
    await _run(harness_driver, "MATCH (n:Observation {id: 'o-1'}) SET n = {id: 'o-1'}")
    report = await Neo4jTenantInvariants(connection).check()
    assert report.unstamped == (UnstampedNodes(("Observation",), 1),)


async def test_a_relationship_between_two_tenants_is_counted_by_its_type(
    connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    await _run(
        harness_driver,
        "CREATE (a:Observation {id: 'o-1', tenantId: $a})-[:ABOUT]->"
        "(b:Observation {id: 'o-1', tenantId: $b}), (a)-[:NEXT]->(:Person {tenantId: $a})",
        a=A,
        b=B,
    )
    report = await Neo4jTenantInvariants(connection).check()
    assert report.cross_scope == (CrossScope("ABOUT", 1),)
    assert report.unstamped_total == 0


async def test_a_relationship_to_a_registry_node_is_not_a_crossing(
    connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    await _run(
        harness_driver,
        "CREATE (:Tenant {id: $a})-[:HAS_NUMBER]->(:TenantNumber {e164: '+447700900101'}), "
        "(:Observation {id: 'o-1', tenantId: $a})",
        a=A,
    )
    assert (await Neo4jTenantInvariants(connection).check()).ok


@pytest.mark.parametrize("bound", [False, True])
async def test_the_check_is_the_same_with_no_tenant_bound_or_any_tenant_bound(
    connection: Neo4jConnection, harness_driver: AsyncDriver, bound: bool
) -> None:
    await _run(harness_driver, "CREATE (:Person {id: 'p-1'})")
    check = Neo4jTenantInvariants(connection)
    if bound:
        with bind_tenant(A):
            report = await check.check()
    else:
        report = await check.check()
    assert report.unstamped == (UnstampedNodes(("Person",), 1),)


async def test_the_check_changes_nothing_and_runs_only_the_two_registered_statements(
    connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    await _run(
        harness_driver, "CREATE (:Person {id: 'p-1'}), (:Person {id: 'p-2', tenantId: $a})", a=A
    )
    seen: list[tuple[str, str]] = []
    set_query_observer(lambda query_id, mode, rows, ms: seen.append((query_id, mode)))
    try:
        await Neo4jTenantInvariants(connection).check()
    finally:
        set_query_observer(None)

    assert seen == [("Q-INVARIANT-UNSTAMPED", "read"), ("Q-INVARIANT-CROSS-SCOPE", "read")]
    assert await count_nodes(harness_driver, "Person") == 2


async def test_the_check_does_not_scan_less_than_the_whole_graph(
    connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    """A thousand stamped nodes and one that is not: the one is found."""
    await _run(
        harness_driver,
        "UNWIND range(1, 1000) AS i CREATE (:Observation {id: toString(i), tenantId: $a})",
        a=A,
    )
    await _run(harness_driver, "CREATE (:Observation {id: 'lost'})")
    report = await Neo4jTenantInvariants(connection).check()
    assert report.unstamped == (UnstampedNodes(("Observation",), 1),)


# The start-up, end to end


async def _startup_connection() -> Neo4jConnection:
    return Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )


async def test_the_start_up_refuses_to_start_while_a_node_has_no_tenant_and_starts_after_the_repair(
    harness_driver: AsyncDriver,
) -> None:
    await _run(harness_driver, "CREATE (:Observation {id: 'lost', note: $m})", m=MARKER)

    refused = build_for_tests(neo4j=await _startup_connection())
    with pytest.raises(TenantInvariantViolated) as raised:
        await refused.startup()
    assert refused.invariant_monitor.raised is True
    assert MARKER not in str(raised.value)
    assert "Observation" in str(raised.value)

    await _run(harness_driver, "MATCH (n:Observation {id: 'lost'}) SET n.tenantId = $a", a=A)
    started = build_for_tests(neo4j=await _startup_connection())
    try:
        await started.startup()
        assert started.invariant_monitor.raised is False
    finally:
        await started.neo4j.close()


async def test_both_counts_come_from_one_read_transaction(
    connection: Neo4jConnection,
) -> None:
    reads: list[int] = []
    original = connection.run_read

    async def counting(work: Any) -> Any:
        reads.append(1)
        return await original(work)

    connection.run_read = counting  # type: ignore[method-assign]
    await Neo4jTenantInvariants(connection).check()
    assert reads == [1]
