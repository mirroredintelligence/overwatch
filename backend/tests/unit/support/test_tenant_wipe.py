"""The tenant-scoped wipe and the contextual helpers of the Neo4j harness (TEN-033, DEC-130 item 9).

On a Neo4j that other runs share, the wipe between tests may delete only what this run owns. These
tests show, against the recording fake driver, exactly what is sent: the scope list the delete is
limited to, the refusal of a global wipe on a database this process does not own, the tenant that
`count_nodes` and `node_props` add from the bound tenant, and `tx_run`. The real server is exercised
by `tests/integration/support/test_tenant_scope_harness.py`.
"""

from typing import Any

import pytest

from diucs.application.tenancy import (
    ScopeId,
    ScopeInvalid,
    TenantNotBound,
    TenantParameterRefused,
    bind_tenant,
)
from tests.support.fake_neo4j import FakeDriver, FakeTx
from tests.support.neo4j import (
    WipeRefused,
    count_nodes,
    count_nodes_all,
    forget_owned,
    mark_owned,
    node_props,
    tx_run,
    wipe_all,
    wipe_tenant,
)

TENANT = "tt-a1-b2-0001"
OTHER = "tt-a1-b2-0001-b"


@pytest.fixture
def driver() -> FakeDriver:
    fake = FakeDriver()
    fake.rows = [{"deleted": 0, "total": 3}]
    return fake


def _statements(driver: FakeDriver) -> list[str]:
    return [cypher for cypher, _ in driver.calls]


# wipe_tenant


async def test_wipe_tenant_deletes_only_nodes_that_carry_one_of_the_named_scopes(
    driver: FakeDriver,
) -> None:
    await wipe_tenant(driver, TENANT, OTHER)  # type: ignore[arg-type]

    deletes = [(c, p) for c, p in driver.calls if "DELETE" in c]
    assert deletes, "nothing was deleted"
    for cypher, params in deletes:
        assert "tenantId" in cypher
        assert params["scopes"] == [TENANT, OTHER]
    # No statement may delete by anything but a scope (a bare `MATCH (n)` delete is the old wipe).
    assert not any("MATCH (n) WHERE NOT n:Migration" in c for c in _statements(driver))


async def test_wipe_tenant_never_names_the_migration_record(driver: FakeDriver) -> None:
    await wipe_tenant(driver, TENANT)  # type: ignore[arg-type]

    assert all("Migration" not in c for c in _statements(driver))


async def test_wipe_tenant_repeats_a_batch_until_nothing_is_left_to_delete(
    driver: FakeDriver,
) -> None:
    counts = iter([10_000, 10_000, 17, 0])

    class Counting(FakeDriver):
        def session(self, **kwargs: Any) -> Any:
            session = super().session(**kwargs)
            driver_self = self

            async def run_batches(work: Any) -> Any:
                tx = FakeTx(driver_self.calls, [{"deleted": next(counts)}])
                driver_self.transactions.append(tx)
                return await work(tx)

            session.execute_write = run_batches
            return session

    counting = Counting()
    await wipe_tenant(counting, TENANT)  # type: ignore[arg-type]

    assert len([c for c in _statements(counting) if "DELETE" in c]) >= 4


async def test_wipe_tenant_accepts_scope_ids_and_network_scopes(driver: FakeDriver) -> None:
    await wipe_tenant(driver, ScopeId.tenant(TENANT), ScopeId.network("net-a1-b2-0001"))  # type: ignore[arg-type]

    scopes = {tuple(p["scopes"]) for c, p in driver.calls if "DELETE" in c}
    assert scopes == {(TENANT, "net-a1-b2-0001")}


@pytest.mark.parametrize("bad", ["", "has space", "a" * 40, "x:y"])
async def test_wipe_tenant_refuses_an_invalid_scope_before_sending_anything(
    driver: FakeDriver, bad: str
) -> None:
    with pytest.raises(ScopeInvalid):
        await wipe_tenant(driver, TENANT, bad)  # type: ignore[arg-type]

    assert driver.calls == []


async def test_wipe_tenant_with_no_scope_is_refused(driver: FakeDriver) -> None:
    with pytest.raises(ValueError, match="at least one"):
        await wipe_tenant(driver)  # type: ignore[arg-type]

    assert driver.calls == []


async def test_wipe_tenant_also_removes_the_registry_records_of_the_scopes(
    driver: FakeDriver,
) -> None:
    """A tenant directory record has no tenantId (it is the registry's): matched by id."""
    await wipe_tenant(driver, TENANT)  # type: ignore[arg-type]

    registry = [c for c in _statements(driver) if "DELETE" in c and ":Tenant" in c]
    assert registry, "the Tenant registry node of a scope is not removed"


# wipe_all


async def test_wipe_all_refuses_a_database_this_process_does_not_own(driver: FakeDriver) -> None:
    with pytest.raises(WipeRefused):
        await wipe_all(driver)  # type: ignore[arg-type]

    assert driver.calls == []


async def test_wipe_all_on_an_owned_database_deletes_everything_but_the_migration_record(
    driver: FakeDriver,
) -> None:
    mark_owned(driver)  # type: ignore[arg-type]
    try:
        await wipe_all(driver)  # type: ignore[arg-type]
    finally:
        forget_owned(driver)  # type: ignore[arg-type]

    deletes = [c for c in _statements(driver) if "DELETE" in c]
    assert deletes
    assert all("NOT n:Migration" in c for c in deletes)


async def test_forgetting_an_owned_database_makes_wipe_all_refuse_again(
    driver: FakeDriver,
) -> None:
    mark_owned(driver)  # type: ignore[arg-type]
    forget_owned(driver)  # type: ignore[arg-type]

    with pytest.raises(WipeRefused):
        await wipe_all(driver)  # type: ignore[arg-type]


# the contextual helpers


async def test_count_nodes_counts_the_bound_tenant_only(driver: FakeDriver) -> None:
    with bind_tenant(TENANT):
        total = await count_nodes(driver, "Observation")  # type: ignore[arg-type]

    assert total == 3
    ((cypher, params),) = driver.calls
    assert "tenantId: $tenant" in cypher
    assert params["tenant"] == TENANT


async def test_count_nodes_follows_the_tenant_bound_now(driver: FakeDriver) -> None:
    with bind_tenant(TENANT):
        await count_nodes(driver, "Observation")  # type: ignore[arg-type]
    with bind_tenant(OTHER):
        await count_nodes(driver, "Observation")  # type: ignore[arg-type]

    assert driver.tenants_sent() == [TENANT, OTHER]


async def test_count_nodes_takes_an_explicit_tenant_over_the_bound_one(
    driver: FakeDriver,
) -> None:
    with bind_tenant(TENANT):
        await count_nodes(driver, "Observation", tenant=OTHER)  # type: ignore[arg-type]

    assert driver.tenants_sent() == [OTHER]


async def test_count_nodes_with_no_tenant_bound_and_none_given_is_refused(
    driver: FakeDriver,
) -> None:
    with pytest.raises(TenantNotBound):
        await count_nodes(driver, "Observation")  # type: ignore[arg-type]

    assert driver.calls == []


async def test_count_nodes_refuses_a_label_that_is_not_a_plain_name(driver: FakeDriver) -> None:
    with bind_tenant(TENANT), pytest.raises(ValueError, match="safe"):
        await count_nodes(driver, "Probe) DETACH DELETE (n")  # type: ignore[arg-type]

    assert driver.calls == []


async def test_count_nodes_all_counts_with_no_tenant_at_all(driver: FakeDriver) -> None:
    total = await count_nodes_all(driver, "Migration")  # type: ignore[arg-type]

    assert total == 3
    ((cypher, params),) = driver.calls
    assert "tenantId" not in cypher
    assert "tenant" not in params


async def test_node_props_reads_the_bound_tenant_only(driver: FakeDriver) -> None:
    driver.rows = [{"props": {"id": "a"}}]

    with bind_tenant(TENANT):
        props = await node_props(driver, "Probe", id="a")  # type: ignore[arg-type]

    assert props == {"id": "a"}
    ((cypher, params),) = driver.calls
    assert "n.tenantId = $tenant" in cypher
    assert params == {"id": "a", "tenant": TENANT}


async def test_node_props_with_no_tenant_is_refused(driver: FakeDriver) -> None:
    with pytest.raises(TenantNotBound):
        await node_props(driver, "Probe", id="a")  # type: ignore[arg-type]


async def test_node_props_takes_an_explicit_scope(driver: FakeDriver) -> None:
    driver.rows = [{"props": {"id": "a"}}]

    await node_props(driver, "Probe", scope=OTHER, id="a")  # type: ignore[arg-type]

    assert driver.tenants_sent() == [OTHER]


# tx_run


async def test_tx_run_adds_the_bound_tenant_to_the_parameters() -> None:
    log: list[tuple[str, dict[str, Any]]] = []
    tx = FakeTx(log)

    with bind_tenant(TENANT):
        await tx_run(tx, "MATCH (n {tenantId: $tenant, id: $id}) RETURN n", id="x")  # type: ignore[arg-type]

    assert log == [
        ("MATCH (n {tenantId: $tenant, id: $id}) RETURN n", {"id": "x", "tenant": TENANT})
    ]


async def test_tx_run_refuses_a_tenant_parameter_from_the_caller() -> None:
    tx = FakeTx([])

    with bind_tenant(TENANT), pytest.raises(TenantParameterRefused):
        await tx_run(tx, "RETURN $tenant", tenant="x")  # type: ignore[arg-type]

    assert tx.calls == []


async def test_tx_run_with_no_tenant_bound_is_refused() -> None:
    tx = FakeTx([])

    with pytest.raises(TenantNotBound):
        await tx_run(tx, "RETURN $tenant")  # type: ignore[arg-type]

    assert tx.calls == []
