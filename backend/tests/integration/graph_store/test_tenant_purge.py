"""A tenant's data on a real Neo4j: the counts, the export reads and the purge (TEN-074, DEC-136
item 10, audit F 2.4, hazard H-T18).

Two tenants of the run hold the same ids and kinds of data (services, reports, criteria, an audit
chain) and tenant B also holds a node nobody should ever lose. Purging tenant A deletes every node
that carries its id and nothing else: tenant B's data, the registry's records and the network scope
are exactly as they were. The audit chain goes last and only when nothing else is left.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_purge import AUDIT_LABELS, Neo4jTenantData
from diucs.application.actor import wall_actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeKindMismatch, bind_network, bind_tenant
from diucs.domain.errors import ValidationFailed
from tests.support.neo4j import read_tx, tx_run
from tests.support.projection_samples import (
    sample_criteria,
    sample_profile,
    sample_report,
)
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")


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


async def _seed(factory: UnitOfWorkFactory, tenant: str, marker: str) -> None:
    with bind_tenant(tenant):
        async with factory() as uow:
            await uow.services.save(sample_profile(name=f"Service {marker}"))
            await uow.capacity.add(sample_report(performer_role_id=f"role-{marker}"))
            await uow.criteria.add(
                sample_criteria(change_reason=f"reason {marker}", supersedes_id=None)
            )
            for n in range(3):
                await uow.audit.append(
                    AuditEntry(
                        action="C",
                        use_case="Seed",
                        actor=wall_actor(tenant),
                        entity_ids=(f"ent-{n}",),
                        snapshot={"n": n},
                        at=__import__("datetime").datetime(
                            2026, 10, 30, 9, n, tzinfo=__import__("datetime").UTC
                        ),
                    )
                )
            await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def two(
    harness_driver: AsyncDriver,
    clean_graph: None,
    tenant_id: str,
    other_tenant_id: str,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
) -> tuple[str, str]:
    await ensure_audit_heads(harness_driver, tenant_id, other_tenant_id)
    await _seed(uow_factory_a, tenant_id, "A")
    await _seed(uow_factory_b, other_tenant_id, "B")
    return tenant_id, other_tenant_id


async def _all(driver: AsyncDriver, tenant: str) -> int:
    """Every node that carries this tenant's id, whatever its label."""

    async def work(tx: AsyncManagedTransaction) -> int:
        with bind_tenant(tenant):
            result = await tx_run(tx, "MATCH (n {tenantId: $tenant}) RETURN count(n) AS n")
            return int((await result.data())[0]["n"])

    return await read_tx(driver, work)


async def test_the_counts_are_by_label_set_for_the_bound_tenant_only(
    two: tuple[str, str], connection: Neo4jConnection
) -> None:
    a, b = two
    data = Neo4jTenantData(connection)
    with bind_tenant(a):
        counts_a = {c.labels: c.count for c in await data.node_counts()}
    with bind_tenant(b):
        counts_b = {c.labels: c.count for c in await data.node_counts()}
    assert counts_a == counts_b  # the same kinds and numbers: the two seeds are alike
    assert counts_a[("HealthcareService", "Resource")] == 1
    assert counts_a[("AuditEvent", "ChainLink")] == 3
    assert sum(counts_a.values()) > 8


async def test_the_export_reads_page_by_page_and_carries_no_tenant_id(
    two: tuple[str, str], connection: Neo4jConnection
) -> None:
    a, b = two
    data = Neo4jTenantData(connection)
    with bind_tenant(a):
        first = await data.nodes(("Resource", "Observation"), after=None, limit=1)
        assert len(first) == 1
        assert "tenantId" not in first[0].properties and a not in repr(first[0].properties)
        again = await data.nodes(("Resource", "Observation"), after=first[0].ref, limit=10)
        assert again == []
        everything = await data.nodes(("Resource", "HealthcareService"), after=None, limit=10)
        assert [n.properties["name"] for n in everything] == ["Service A"]  # never B's
        rels = await data.relationships(after=None, limit=100)
    assert rels and all(a not in repr(r.properties) for r in rels)
    ends = {r.start for r in rels} | {r.end for r in rels}
    with bind_tenant(b):
        b_refs = {
            n.ref for n in await data.nodes(("Resource", "HealthcareService"), after=None, limit=10)
        }
    assert not ends & b_refs  # a relationship joins nodes of one tenant


async def test_the_audit_head_is_the_tenants_own(
    two: tuple[str, str], connection: Neo4jConnection
) -> None:
    a, b = two
    data = Neo4jTenantData(connection)
    with bind_tenant(a):
        head_a = await data.audit_head()
    with bind_tenant(b):
        head_b = await data.audit_head()
    assert head_a is not None and head_b is not None
    assert head_a.last_seq == head_b.last_seq == 3 and head_a.last_hash != head_b.last_hash


async def test_purging_one_tenant_leaves_the_other_exactly_as_it_was(
    two: tuple[str, str], connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    a, b = two
    data = Neo4jTenantData(connection)
    before_b = await _all(harness_driver, b)
    assert before_b > 8 and await _all(harness_driver, a) == before_b
    with bind_tenant(a):
        total = 0
        while batch := await data.delete_data_batch(5):
            total += batch
        # the audit chain is still there: it goes last
        left = {labels for c in await data.node_counts() for labels in c.labels}
        assert left <= set(AUDIT_LABELS)  # nothing but the chain (links, head, snapshots, refs)
        assert ("AuditEvent" in left) and await data.audit_head() is not None
        while batch := await data.delete_audit_batch(2):
            total += batch
        assert await data.node_counts() == []
    assert total == before_b
    assert await _all(harness_driver, a) == 0
    assert await _all(harness_driver, b) == before_b
    with bind_tenant(b):
        counts = {c.labels: c.count for c in await data.node_counts()}
        assert counts[("HealthcareService", "Resource")] == 1


async def test_the_audit_chain_is_not_touched_while_any_data_is_left(
    two: tuple[str, str], connection: Neo4jConnection, harness_driver: AsyncDriver
) -> None:
    a, _ = two
    data = Neo4jTenantData(connection)
    with bind_tenant(a):
        assert await data.delete_audit_batch(100) == 0
        assert await data.audit_head() is not None
    assert await _all(harness_driver, a) > 4


async def test_a_batch_size_that_is_not_a_small_whole_number_is_refused(
    two: tuple[str, str], connection: Neo4jConnection
) -> None:
    a, _ = two
    data = Neo4jTenantData(connection)
    with bind_tenant(a):
        for bad in (0, -1, 5001, 1.5, "10", True):
            with pytest.raises(ValidationFailed):
                await data.delete_data_batch(bad)  # type: ignore[arg-type]
        with pytest.raises(ValidationFailed):
            await data.nodes(("Resource",), after=None, limit=0)


async def test_the_statements_are_refused_in_a_network_scope(
    two: tuple[str, str], connection: Neo4jConnection
) -> None:
    """A purge is a tenant's: bound to a network scope the statements do not run."""
    data = Neo4jTenantData(connection)
    with bind_network("net-purge-check"):
        with pytest.raises(ScopeKindMismatch):
            await data.node_counts()
        with pytest.raises(ScopeKindMismatch):
            await data.delete_data_batch(10)
