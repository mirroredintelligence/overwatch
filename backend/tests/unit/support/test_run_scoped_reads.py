"""The whole-graph scans of integration tests read the run's own scopes only (TEN-035).

On one shared Neo4j other runs hold data too, so a test that means "every node" means the nodes of
its own tenant, second tenant and network scope: `run_nodes` and `run_relationships` carry exactly
those ids, read from the environment the conftest sets, and refuse to run without them.
"""

import pytest

from tests.support.fake_neo4j import FakeTx
from tests.support.neo4j import RUN_NODES, run_nodes, run_relationships, run_scope_ids

IDS = ("tt-a1-b2-0001", "tt-a1-b2-0001-b", "net-a1-b2-0001")


@pytest.fixture
def run_ids(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, str]:
    for name, value in zip(
        ("DIUCS_TEST_TENANT", "DIUCS_TEST_OTHER_TENANT", "DIUCS_TEST_NETWORK"), IDS, strict=True
    ):
        monkeypatch.setenv(name, value)
    return IDS


def test_the_scope_ids_are_the_three_the_conftest_exported(run_ids: tuple[str, str, str]) -> None:
    assert run_scope_ids() == list(run_ids)


@pytest.mark.parametrize("missing", ["DIUCS_TEST_TENANT", "DIUCS_TEST_OTHER_TENANT"])
def test_a_missing_scope_id_stops_the_scan_rather_than_reading_everything(
    run_ids: tuple[str, str, str], monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)

    with pytest.raises(RuntimeError, match="scope ids"):
        run_scope_ids()


async def test_run_nodes_matches_only_nodes_carrying_a_scope_of_the_run(
    run_ids: tuple[str, str, str],
) -> None:
    log: list[tuple[str, dict[str, object]]] = []

    await run_nodes(FakeTx(log), "count(n) AS total")

    cypher, params = log[0]
    assert cypher.startswith(RUN_NODES) and cypher.endswith("RETURN count(n) AS total")
    assert "n.tenantId IN $scopes" in cypher
    assert params == {"scopes": list(run_ids)}
    assert "MATCH (n) RETURN" not in cypher


async def test_run_relationships_start_at_a_node_of_the_run(run_ids: tuple[str, str, str]) -> None:
    log: list[tuple[str, dict[str, object]]] = []

    await run_relationships(FakeTx(log), "properties(r) AS p")

    cypher, params = log[0]
    assert "a.tenantId IN $scopes" in cypher and cypher.endswith("RETURN properties(r) AS p")
    assert params == {"scopes": list(run_ids)}


# the transaction a test runs raw Cypher on


async def test_raw_cypher_in_a_test_gets_the_bound_tenant_as_a_parameter() -> None:
    from diucs.application.tenancy import bind_tenant
    from tests.support.scoped import scoped

    log: list[tuple[str, dict[str, object]]] = []
    with bind_tenant("tt-a1-b2-0001"):
        tx = scoped(FakeTx(log))
        await tx.run("MATCH (n {tenantId: $tenant}) RETURN n.id AS id", {"id": "x"}, other=1)

    assert log == [
        (
            "MATCH (n {tenantId: $tenant}) RETURN n.id AS id",
            {"id": "x", "other": 1, "tenant": "tt-a1-b2-0001"},
        )
    ]


async def test_a_tenant_the_caller_names_is_kept_so_another_tenants_nodes_can_be_read() -> None:
    from diucs.application.tenancy import bind_tenant
    from tests.support.scoped import scoped

    log: list[tuple[str, dict[str, object]]] = []
    with bind_tenant("tt-a1-b2-0001"):
        await scoped(FakeTx(log)).run(
            "MATCH (n {tenantId: $tenant}) RETURN n", tenant="tt-a1-b2-0001-b"
        )

    assert log[0][1] == {"tenant": "tt-a1-b2-0001-b"}
