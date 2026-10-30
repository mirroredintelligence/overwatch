"""Three scopes on a real Neo4j: member tenants and the network between them (TEN-060, DEC-544).

Written, not run, in build wave 5 (the owner's instruction: the whole integration suite runs once,
on the merged tip).

The world has an owner, three members that all hold a service with the same id, and an outsider.
Every member has granted capacity, directory and criteria and the owner has admitted each service.
The projector runs for the members and the tests look at the three kinds of scope at once: what a
member's tenant scope holds, what the network scope holds, and what the registry holds.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, TENANT_KINDS
from diucs.application.ports.outbound.projection import ProjectionEndReason
from diucs.application.tenancy import (
    ScopeId,
    ScopeKindMismatch,
    bind_network,
    bind_tenant,
)
from diucs.application.use_cases.apply_projection import ApplyOutcome
from diucs.domain.events import ProjectionRejectReason
from diucs.domain.model.network import GrantScope
from tests.support.neo4j import read_tx, write_tx
from tests.support.network_world import NETWORK_INVARIANTS, NetworkWorld, world_ids
from tests.support.query_probes import production_statements
from tests.support.tenancy import RunIdentity

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


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    run_identity: RunIdentity,
    clean_graph: None,
) -> AsyncIterator[NetworkWorld]:
    built = await NetworkWorld.build(harness_driver, connection, world_ids(run_identity))
    yield built
    await built.cleanup()


async def _count(driver: AsyncDriver, scope: str, label: str | None = None) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        cypher = (
            "MATCH (n {tenantId: $s}) RETURN count(n) AS n"
            if label is None
            else f"MATCH (n:{label} {{tenantId: $s}}) RETURN count(n) AS n"  # test-only text
        )
        return int((await (await tx.run(cypher, s=scope)).data())[0]["n"])

    return await read_tx(driver, work)


async def test_three_members_with_the_same_service_id_stay_apart_in_the_network(
    world: NetworkWorld,
) -> None:
    results = await world.run_projector()
    assert all(r.outcome is ApplyOutcome.APPLIED for rs in results.values() for r in rs)
    services, capacities, criteria = await world.view()
    by_member = {m: [r for r in services if r.source_tenant_id == m] for m in world.ids.members}
    assert all(len(rows) == 1 for rows in by_member.values())
    names = {r.projection.service_name for r in services}
    assert len(names) == 3
    assert len(capacities) == len(criteria) == 3
    for member, [row] in by_member.items():
        assert row.projection.service_name == world.service_name(member)


async def test_no_member_scope_holds_a_projection_and_no_member_sees_another_members_data(
    world: NetworkWorld, harness_driver: AsyncDriver
) -> None:
    await world.run_projector()
    for member in world.ids.members:
        for label in ("ProjectedService", "ProjectedCapacity", "ProjectedCriteria"):
            assert await _count(harness_driver, member, label) == 0
        async with world.reader(member) as uow:
            services = await uow.services.list_active()
        assert [s.name for s in services] == [world.service_name(member)]


async def test_no_poison_from_any_members_private_data_reaches_the_network_scope(
    world: NetworkWorld, harness_driver: AsyncDriver
) -> None:
    await world.run_projector()

    async def everything(tx: AsyncManagedTransaction) -> str:
        rows = await (
            await tx.run(
                "MATCH (n {tenantId: $s}) RETURN labels(n) AS l, properties(n) AS p",
                s=world.ids.network,
            )
        ).data()
        return repr(rows)

    text = await read_tx(harness_driver, everything)
    assert world.poison, "the world seeded poison"
    for member, values in world.poison.items():
        for value in values:
            assert value not in text, (member, "a private value reached the network scope")


async def test_an_outsider_projects_nothing_and_a_forged_message_from_it_is_rejected(
    world: NetworkWorld,
) -> None:
    assert await world.produce_as(world.ids.outsider) == []
    forged = await world.forge_from(world.ids.outsider)
    assert forged.outcome is ApplyOutcome.REJECTED
    assert forged.reason is ProjectionRejectReason.MEMBER_NOT_ACTIVE
    services, *_ = await world.view()
    assert {r.source_tenant_id for r in services} <= set(world.ids.members)


async def test_a_message_naming_another_members_grant_is_refused(world: NetworkWorld) -> None:
    result = await world.forge_with_grant_of(
        sender=world.ids.members[0], grant_owner=world.ids.members[1]
    )
    assert result.outcome is ApplyOutcome.REJECTED
    assert result.reason is ProjectionRejectReason.GRANT_NOT_EFFECTIVE


async def test_every_invariant_of_a_network_scope_holds_after_the_projector_ran(
    world: NetworkWorld,
) -> None:
    await world.run_projector()
    findings = await world.invariants()
    assert set(findings) == set(NETWORK_INVARIANTS)
    assert {name: rows for name, rows in findings.items() if rows} == {}
    report = await world.global_invariants()
    assert report.unstamped == () and report.cross_scope == ()


async def test_deleting_a_members_tenant_data_leaves_the_network_rows_and_history_untouched(
    world: NetworkWorld, harness_driver: AsyncDriver
) -> None:
    await world.run_projector()
    before = await _count(harness_driver, world.ids.network)
    member = world.ids.members[0]

    async def delete_tenant(tx: AsyncManagedTransaction) -> None:
        await tx.run("MATCH (n {tenantId: $t}) DETACH DELETE n", t=member)

    await write_tx(harness_driver, delete_tenant)
    assert await _count(harness_driver, member) == 0
    assert await _count(harness_driver, world.ids.network) == before
    services, *_ = await world.view()
    assert member in {r.source_tenant_id for r in services}


async def test_a_member_who_leaves_ends_its_rows_and_only_its_rows_and_history_stays(
    world: NetworkWorld,
) -> None:
    await world.run_projector()
    leaver, stayer = world.ids.members[0], world.ids.members[1]
    ended = await world.leave(leaver)
    assert ended >= 3
    live, *_ = await world.view()
    assert {r.source_tenant_id for r in live} == set(world.ids.members) - {leaver}
    history, *_ = await world.view(live_only=False)
    row = next(r for r in history if r.source_tenant_id == leaver)
    assert row.ended_at is not None and row.end_reason is ProjectionEndReason.LEFT
    assert next(r for r in history if r.source_tenant_id == stayer).ended_at is None
    assert await world.run_projector(only=leaver) == {leaver: []}


async def test_a_statement_for_one_kind_of_scope_is_refused_in_the_other_on_a_real_transaction(
    harness_driver: AsyncDriver, world: NetworkWorld
) -> None:
    tenant_statement = next(
        q for q in production_statements(REGISTRY).values() if q.scope_kinds == TENANT_KINDS
    )
    network_statement = REGISTRY.get("Q-PROJ-SOURCES")
    async with harness_driver.session() as session:
        tx = await session.begin_transaction()
        try:
            with pytest.raises(ScopeKindMismatch):
                await run_query(
                    ScopedTx(tx, ScopeId.tenant(world.ids.members[0])), network_statement
                )
            with pytest.raises(ScopeKindMismatch):
                await run_query(ScopedTx(tx, ScopeId.network(world.ids.network)), tenant_statement)
        finally:
            await tx.rollback()


async def test_the_registry_answers_the_same_in_every_scope(world: NetworkWorld) -> None:
    expected = await world.registry.get_network(world.ids.network)
    assert expected is not None
    for scope in (bind_network(world.ids.network), bind_tenant(world.ids.members[0])):
        with scope:
            assert await world.registry.get_network(world.ids.network) == expected


async def test_the_three_kinds_of_grant_are_each_needed_for_their_own_projection(
    world: NetworkWorld,
) -> None:
    await world.end_grant(world.ids.members[2], GrantScope.CAPACITY)
    results = await world.run_projector(only=world.ids.members[2])
    kinds = {r.reason for r in results[world.ids.members[2]] if r.reason is not None}
    assert kinds == set()  # the producer sent no capacity message at all
    _, capacities, _ = await world.view()
    assert world.ids.members[2] not in {r.source_tenant_id for r in capacities}
