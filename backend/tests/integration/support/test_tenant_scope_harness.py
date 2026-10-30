"""The tenant-scoped harness against a real Neo4j (TEN-033, DEC-130 item 9).

`clean_graph` deletes only the nodes of this run's scopes and gives the run's tenants their audit
chain heads again. `count_nodes` and `node_props` read the tenant bound now. The orphan sweeper
removes the leftovers of a run whose owner is gone and nothing else. `seed_world` writes the same
sample graph for any tenant. Nodes of a tenant that is not this run's (a stand-in for another
run on a shared Neo4j) must survive all of it, and are removed here in a `finally`.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope
from tests.support.neo4j import (
    WipeRefused,
    count_nodes,
    count_nodes_all,
    node_props,
    throwaway_driver,
    tx_run,
    wipe_all,
    wipe_tenant,
    write_tx,
)
from tests.support.seed import seed_world
from tests.support.sweeper import sweep_orphan_tenants
from tests.support.tenancy import RunIdentity, as_tenant
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Another run's tenant on the same Neo4j, as far as this run is concerned: well-formed, owner dead.
DEAD_OWNER = RunIdentity(pid=4_194_303, started=1_800_000_000, nonce="0dea")
# And one whose owner is this very process: it must survive a sweep.
STRANGER = "tt-stranger-run"


async def _probe(tx: object, probe_id: str = "a") -> None:
    await tx_run(tx, "CREATE (:Probe {id: $id, tenantId: $tenant})", id=probe_id)  # type: ignore[arg-type]


async def _probe_in(driver: AsyncDriver, tenant: str, probe_id: str = "a") -> None:
    with bind_scope(ScopeId.parse(tenant)):  # a tenant, or a network scope
        await write_tx(driver, lambda tx: _probe(tx, probe_id))


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def stranger(neo4j_driver: AsyncDriver) -> AsyncIterator[str]:
    """A node of a tenant that is not this run's, written once before any test of the module and
    therefore before every `clean_graph` of it, and removed when the module is done."""
    await _probe_in(neo4j_driver, STRANGER, "stranger-1")
    try:
        yield STRANGER
    finally:
        await wipe_tenant(neo4j_driver, STRANGER)


# clean_graph


async def test_clean_graph_leaves_the_second_tenant_and_the_run_clean_before_a_test(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    # The previous test's probes are gone for the run tenant and for the second tenant.
    assert await count_nodes(neo4j_driver, "Probe") == 0
    assert await count_nodes(neo4j_driver, "Probe", tenant=other_tenant_id) == 0


async def test_clean_graph_gave_the_run_tenant_and_the_second_tenant_an_audit_chain_head(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    assert await count_nodes(neo4j_driver, "AuditHead") == 1
    assert await count_nodes(neo4j_driver, "AuditHead", tenant=other_tenant_id) == 1


async def test_a_wipe_between_tests_does_not_remove_another_runs_tenant(
    neo4j_driver: AsyncDriver, stranger: str
) -> None:
    # `stranger` was written before this test's clean_graph ran, and clean_graph wiped the run's
    # scopes only.
    assert await count_nodes(neo4j_driver, "Probe", tenant=stranger) == 1


async def test_clean_graph_removes_the_run_tenant_second_tenant_and_network_nodes(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str, network_id: str
) -> None:
    await _probe_in(neo4j_driver, tenant_id)
    await _probe_in(neo4j_driver, other_tenant_id)
    await _probe_in(neo4j_driver, network_id)

    await wipe_tenant(neo4j_driver, tenant_id, other_tenant_id, network_id)

    assert await count_nodes(neo4j_driver, "Probe") == 0
    assert await count_nodes(neo4j_driver, "Probe", tenant=other_tenant_id) == 0
    assert await count_nodes(neo4j_driver, "Probe", tenant=network_id) == 0


async def test_wipe_tenant_leaves_the_migration_record_and_other_scopes(
    neo4j_driver: AsyncDriver, tenant_id: str, stranger: str
) -> None:
    migrations = await count_nodes_all(neo4j_driver, "Migration")
    await _probe_in(neo4j_driver, tenant_id)

    await wipe_tenant(neo4j_driver, tenant_id)

    assert await count_nodes(neo4j_driver, "Probe") == 0
    assert await count_nodes(neo4j_driver, "Probe", tenant=stranger) == 1
    assert migrations > 0
    assert await count_nodes_all(neo4j_driver, "Migration") == migrations


async def test_wipe_tenant_removes_the_tenant_directory_record_of_the_scope(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    async def make(tx: object) -> None:
        await tx.run(  # type: ignore[attr-defined]
            "MERGE (t:Tenant {id: $id}) MERGE (t)-[:HAS_NUMBER]->(:TenantNumber {e164: $number})",
            id=tenant_id,
            number="+447700900123",
        )

    await write_tx(neo4j_driver, make)

    await wipe_tenant(neo4j_driver, tenant_id)

    assert await count_nodes_all(neo4j_driver, "Tenant") == await _others(neo4j_driver, "Tenant")
    assert (
        await _present(neo4j_driver, "MATCH (t:Tenant {id: $id}) RETURN count(t) AS n", tenant_id)
        == 0
    )
    assert (
        await _present(
            neo4j_driver,
            "MATCH (n:TenantNumber {e164: '+447700900123'}) RETURN count(n) AS n",
            None,
        )
        == 0
    )


async def _present(driver: AsyncDriver, cypher: str, tenant: str | None) -> int:
    async def work(tx: object) -> int:
        params = {} if tenant is None else {"id": tenant}
        rows = await (await tx.run(cypher, **params)).data()  # type: ignore[attr-defined]
        return int(rows[0]["n"])

    return await write_tx(driver, work)


async def _others(driver: AsyncDriver, label: str) -> int:
    return await count_nodes_all(driver, label)


# count_nodes and node_props


async def test_count_nodes_counts_only_the_bound_tenant(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    await _probe_in(neo4j_driver, other_tenant_id)

    assert await count_nodes(neo4j_driver, "Probe") == 0
    with as_tenant(other_tenant_id):
        assert await count_nodes(neo4j_driver, "Probe") == 1


async def test_count_nodes_with_an_explicit_tenant_ignores_the_bound_one(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _probe_in(neo4j_driver, tenant_id, "a")
    await _probe_in(neo4j_driver, tenant_id, "b")
    await _probe_in(neo4j_driver, other_tenant_id, "c")

    assert await count_nodes(neo4j_driver, "Probe") == 2
    assert await count_nodes(neo4j_driver, "Probe", tenant=other_tenant_id) == 1


async def test_count_nodes_all_counts_every_tenant_and_a_node_with_none(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    before = await count_nodes_all(neo4j_driver, "Probe")
    await _probe_in(neo4j_driver, tenant_id)
    await _probe_in(neo4j_driver, other_tenant_id)

    assert await count_nodes_all(neo4j_driver, "Probe") == before + 2


@pytest.mark.no_tenant
async def test_count_nodes_with_nothing_bound_is_refused(neo4j_driver: AsyncDriver) -> None:
    with pytest.raises(TenantNotBound):
        await count_nodes(neo4j_driver, "Probe")


async def test_node_props_finds_the_node_of_the_bound_tenant_not_another_tenants_twin(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    await _probe_in(neo4j_driver, other_tenant_id, "same")
    await _probe_in(neo4j_driver, "tt-twin-owner", "same")
    try:
        with as_tenant(other_tenant_id):
            props = await node_props(neo4j_driver, "Probe", id="same")
        assert props == {"id": "same", "tenantId": other_tenant_id}
        with pytest.raises(AssertionError, match="found 0"):
            await node_props(neo4j_driver, "Probe", id="same")
    finally:
        await wipe_tenant(neo4j_driver, "tt-twin-owner")


async def test_tx_run_runs_raw_cypher_in_the_bound_tenant(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    async def count(tx: object) -> int:
        result = await tx_run(tx, "MATCH (n:Probe {tenantId: $tenant}) RETURN count(n) AS n")  # type: ignore[arg-type]
        return int((await result.data())[0]["n"])

    await write_tx(neo4j_driver, _probe)

    assert await write_tx(neo4j_driver, count) == 1


# wipe_all


async def test_wipe_all_is_refused_on_a_database_the_run_did_not_start(
    neo4j_driver: AsyncDriver, stranger: str
) -> None:
    """A driver that was never marked as owned is refused whatever it points at, and nothing of
    another run's is touched. (Whether the harness driver itself is owned depends on the mode.)"""

    class Unmarked:
        def session(self, **_: object) -> None:  # pragma: no cover - never reached
            raise AssertionError("a refused wipe must not open a session")

    with pytest.raises(WipeRefused):
        await wipe_all(Unmarked())  # type: ignore[arg-type]
    assert await count_nodes(neo4j_driver, "Probe", tenant=stranger) == 1


@pytest.mark.schema
async def test_wipe_all_on_a_private_container_removes_every_tenant_and_keeps_the_schema() -> None:
    async with throwaway_driver() as (_container, driver):
        from diucs.adapters.outbound.graph_store.migrations import apply_migrations

        await apply_migrations(driver)
        await _probe_in(driver, "tt-one-owner")
        await _probe_in(driver, "tt-two-owner")

        await wipe_all(driver)

        assert await count_nodes_all(driver, "Probe") == 0
        assert await count_nodes_all(driver, "Migration") > 0


# the orphan sweeper


async def test_the_sweeper_removes_a_dead_runs_tenants_and_keeps_the_live_ones(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str, stranger: str
) -> None:
    await _probe_in(neo4j_driver, tenant_id)
    await _probe_in(neo4j_driver, DEAD_OWNER.tenant_id)
    await _probe_in(neo4j_driver, DEAD_OWNER.other_tenant_id)
    await _probe_in(neo4j_driver, DEAD_OWNER.network_id)

    swept = await sweep_orphan_tenants(neo4j_driver)

    assert DEAD_OWNER in swept
    for scope in (DEAD_OWNER.tenant_id, DEAD_OWNER.other_tenant_id, DEAD_OWNER.network_id):
        assert await count_nodes(neo4j_driver, "Probe", tenant=scope) == 0
    # This run (its pid is alive and started before its identity), and a tenant that is no run id.
    assert await count_nodes(neo4j_driver, "Probe") == 1
    assert await count_nodes(neo4j_driver, "Probe", tenant=stranger) == 1


async def test_the_sweeper_leaves_a_real_tenants_data_alone(neo4j_driver: AsyncDriver) -> None:
    await _probe_in(neo4j_driver, "example-icb")
    try:
        await sweep_orphan_tenants(neo4j_driver)

        assert await count_nodes(neo4j_driver, "Probe", tenant="example-icb") == 1
    finally:
        await wipe_tenant(neo4j_driver, "example-icb")


async def test_the_sweeper_removes_a_dead_runs_directory_record_too(
    neo4j_driver: AsyncDriver,
) -> None:
    async def make(tx: object) -> None:
        await tx.run("MERGE (:Tenant {id: $id})", id=DEAD_OWNER.tenant_id)  # type: ignore[attr-defined]

    await write_tx(neo4j_driver, make)

    swept = await sweep_orphan_tenants(neo4j_driver)

    assert DEAD_OWNER in swept
    assert (
        await _present(
            neo4j_driver, "MATCH (t:Tenant {id: $id}) RETURN count(t) AS n", DEAD_OWNER.tenant_id
        )
        == 0
    )


async def test_the_sweeper_with_nothing_to_sweep_changes_nothing(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _probe_in(neo4j_driver, tenant_id)

    assert await sweep_orphan_tenants(neo4j_driver) == []
    assert await count_nodes(neo4j_driver, "Probe") == 1


# the seed layer


async def test_seed_world_writes_the_same_sample_graph_for_any_tenant(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    first = await seed_world(neo4j_driver, tenant_id)
    second = await seed_world(neo4j_driver, other_tenant_id)

    assert first.service_ids == second.service_ids
    assert len(first.service_ids) >= 2
    for tenant in (tenant_id, other_tenant_id):
        assert await count_nodes(neo4j_driver, "HealthcareService", tenant=tenant) == len(
            first.service_ids
        )


async def test_seed_world_is_idempotent_for_one_tenant(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await seed_world(neo4j_driver, tenant_id)
    count = await count_nodes(neo4j_driver, "HealthcareService")

    await seed_world(neo4j_driver, tenant_id)

    assert await count_nodes(neo4j_driver, "HealthcareService") == count


async def test_seed_world_gives_the_tenant_its_audit_head_and_changes_no_other_tenant(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await seed_world(neo4j_driver, other_tenant_id)

    assert await count_nodes(neo4j_driver, "AuditHead", tenant=other_tenant_id) == 1
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0


async def test_seed_world_works_after_the_graph_was_wiped_by_the_test_itself(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await wipe_tenant(neo4j_driver, tenant_id, other_tenant_id)
    await ensure_audit_heads(neo4j_driver, tenant_id)

    world = await seed_world(neo4j_driver, tenant_id)

    assert await count_nodes(neo4j_driver, "HealthcareService") == len(world.service_ids)
