"""The network registry on a real Neo4j (TEN-051, DEC-541, DEC-134 item 9).

Written, not run, in build wave 5 (the owner's instruction: the whole integration suite runs once,
on the merged tip).

The registry nodes (`Network`, `NetworkMembership`, `Grant`, `Listing`) carry no `tenantId` and are
read and written by global statements only. The tests show what that means on a real graph: a
statement answers from registry nodes and from nothing else, whatever the graph also holds and
whatever scope is bound; a create is the only live row (a lock on the network, then a count); a save
matches the status it expects, so of two racing saves exactly one writes; a key taken is a
`Conflict`; and no write statement changes a node that is not a registry node.
"""

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_global_query
from diucs.adapters.outbound.graph_store.network_registry import Neo4jNetworkRegistry
from diucs.adapters.outbound.graph_store.queries import GLOBAL_WRITE_IDS, REGISTRY
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.domain.errors import Conflict
from diucs.domain.model.network import (
    GrantScope,
    GrantStatus,
    ListingStatus,
    MembershipStatus,
    NetworkStatus,
)
from diucs.domain.rules.grant import end_grant
from tests.support.neo4j import read_tx, write_tx
from tests.support.network_samples import (
    ACCOUNT_B,
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    NOW,
    OTHER_NETWORK_ID,
    OWNER,
    SETTINGS,
    make_grant,
    make_listing,
    make_member,
    make_network,
    make_owner_membership,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

REGISTRY_CLEAN = (
    "MATCH (n) WHERE n:Network OR n:NetworkMembership OR n:Grant OR n:Listing DETACH DELETE n"
)


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
async def _clean_registry(harness_driver: AsyncDriver) -> AsyncIterator[None]:
    """The registry carries no tenant, so the harness's tenant wipe does not touch it: these tests
    clear their own nodes, before and after."""
    await _run(harness_driver, REGISTRY_CLEAN)
    yield
    await _run(harness_driver, REGISTRY_CLEAN)


@pytest.fixture
def registry(connection: Neo4jConnection) -> Neo4jNetworkRegistry:
    return Neo4jNetworkRegistry(connection)


async def _run(driver: AsyncDriver, cypher: str, **params: Any) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(cypher, params)

    await write_tx(driver, work)


async def _rows(driver: AsyncDriver, cypher: str, **params: Any) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(cypher, params)).data()

    return await read_tx(driver, work)


async def _world(registry: Neo4jNetworkRegistry) -> None:
    await registry.create_network(make_network(), SETTINGS)
    await registry.create_membership(make_owner_membership())
    await registry.create_membership(make_member(MEMBER_B))
    await registry.create_membership(make_member(MEMBER_C))


# Round trips


async def test_a_network_its_members_a_grant_and_a_listing_round_trip(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)
    grant, listing = make_grant(), make_listing()
    await registry.create_grant(grant)
    await registry.create_listing(listing)
    found = await registry.get_network(NETWORK_ID)
    assert found is not None
    assert found.network == make_network()
    assert found.settings == SETTINGS
    assert {m.member_tenant_id for m in await registry.memberships(NETWORK_ID)} == {
        OWNER,
        MEMBER_B,
        MEMBER_C,
    }
    assert await registry.get_grant(grant.id) == grant
    assert await registry.grants(NETWORK_ID) == [grant]
    assert await registry.grants_of(MEMBER_B) == [grant]
    assert await registry.get_listing(listing.id) == listing
    assert await registry.listings_of(NETWORK_ID, MEMBER_B) == [listing]
    assert await registry.listings_of(NETWORK_ID, MEMBER_C) == []
    assert await registry.get_network(OTHER_NETWORK_ID) is None


async def test_the_membership_check_finds_the_active_row_and_never_a_closed_one(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)
    assert (await registry.active_membership(NETWORK_ID, MEMBER_B)) == make_member(MEMBER_B)
    assert await registry.active_membership(NETWORK_ID, "tenant-z") is None
    row = make_member(MEMBER_C)
    left = make_member(MEMBER_C, status=MembershipStatus.LEFT)
    await registry.save_membership(left, expected_status=row.status)
    assert await registry.active_membership(NETWORK_ID, MEMBER_C) is None
    assert [m.status for m in await registry.memberships_of(MEMBER_C)] == [MembershipStatus.LEFT]
    # A tenant that left rejoins as a new row; the closed row stays as history.
    again = replace(make_member(MEMBER_C), id="mem-tenant-c-again")
    await registry.create_membership(again)
    assert {m.status for m in await registry.memberships_of(MEMBER_C)} == {
        MembershipStatus.LEFT,
        MembershipStatus.ACTIVE,
    }


# The gate


async def test_the_gate_returns_the_grants_that_may_project_and_only_those(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)
    good = make_grant(id="grant-good")
    unapproved = make_grant(id="grant-unapproved", scope=GrantScope.DIRECTORY, approved=False)
    other_scope = make_grant(id="grant-criteria", scope=GrantScope.CRITERIA)
    for grant in (good, unapproved, other_scope):
        await registry.create_grant(grant)
    active = await registry.active_grants_for(MEMBER_B, GrantScope.CAPACITY, NOW)
    assert [a.grant.id for a in active] == ["grant-good"]
    assert active[0].network.settings == SETTINGS
    assert active[0].membership.member_tenant_id == MEMBER_B
    assert await registry.active_grants_for(MEMBER_B, GrantScope.DIRECTORY, NOW) == []
    assert await registry.active_grants_for(MEMBER_C, GrantScope.CAPACITY, NOW) == []
    # Ended by its grantor, it stops at once.
    ended = end_grant(good, by_tenant_id=MEMBER_B, account_ref=ACCOUNT_B, now=NOW)
    await registry.save_grant(ended, expected_status=GrantStatus.APPROVED)
    assert await registry.active_grants_for(MEMBER_B, GrantScope.CAPACITY, NOW) == []


async def test_a_member_who_left_or_a_suspended_network_closes_the_gate(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)
    await registry.create_grant(make_grant())
    assert await registry.active_grants_for(MEMBER_B, GrantScope.CAPACITY, NOW)
    await registry.save_network(
        make_network(NetworkStatus.SUSPENDED), SETTINGS, expected_status=NetworkStatus.ACTIVE
    )
    assert await registry.active_grants_for(MEMBER_B, GrantScope.CAPACITY, NOW) == []
    await registry.save_network(make_network(), SETTINGS, expected_status=NetworkStatus.SUSPENDED)
    await registry.save_membership(
        make_member(MEMBER_B, status=MembershipStatus.LEFT),
        expected_status=MembershipStatus.ACTIVE,
    )
    assert await registry.active_grants_for(MEMBER_B, GrantScope.CAPACITY, NOW) == []


# Guards and races


async def test_a_key_that_is_taken_is_a_conflict(registry: Neo4jNetworkRegistry) -> None:
    await _world(registry)
    await registry.create_grant(make_grant())
    await registry.create_listing(make_listing())
    with pytest.raises(Conflict):
        await registry.create_network(make_network(), SETTINGS)
    with pytest.raises(Conflict):
        await registry.create_grant(make_grant())
    with pytest.raises(Conflict):
        await registry.create_listing(replace(make_listing(), status=ListingStatus.ADMITTED))


async def test_a_second_live_membership_or_listing_for_the_same_key_is_a_conflict(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)
    with pytest.raises(Conflict):
        await registry.create_membership(replace(make_member(MEMBER_B), id="mem-other-id"))
    await registry.create_listing(make_listing(id="lst-1", service="svc-1", admitted=False))
    with pytest.raises(Conflict):
        await registry.create_listing(make_listing(id="lst-2", service="svc-1", admitted=False))
    await registry.create_listing(make_listing(id="lst-3", service="svc-2", admitted=False))


async def test_a_save_that_expects_another_status_writes_nothing(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)
    grant = make_grant()
    await registry.create_grant(grant)
    ended = end_grant(grant, by_tenant_id=MEMBER_B, account_ref=ACCOUNT_B, now=NOW)
    with pytest.raises(Conflict):
        await registry.save_grant(ended, expected_status=GrantStatus.PROPOSED)
    assert await registry.get_grant(grant.id) == grant


async def test_of_two_racing_saves_of_one_grant_exactly_one_writes(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)
    grant = make_grant()
    await registry.create_grant(grant)
    ended = end_grant(grant, by_tenant_id=MEMBER_B, account_ref=ACCOUNT_B, now=NOW)

    async def save() -> bool:
        try:
            await registry.save_grant(ended, expected_status=GrantStatus.APPROVED)
        except Conflict:
            return False
        return True

    results = await asyncio.gather(*(save() for _ in range(8)))
    assert results.count(True) == 1
    assert await registry.get_grant(grant.id) == ended


async def test_of_racing_creates_of_one_listing_or_membership_exactly_one_is_written(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)

    async def create_listing(n: int) -> bool:
        try:
            await registry.create_listing(
                make_listing(id=f"lst-race-{n}", service="svc-race", admitted=False)
            )
        except Conflict:
            return False
        return True

    async def create_member(n: int) -> bool:
        try:
            await registry.create_membership(replace(make_member("tenant-d"), id=f"mem-race-{n}"))
        except Conflict:
            return False
        return True

    listings = await asyncio.gather(*(create_listing(n) for n in range(8)))
    members = await asyncio.gather(*(create_member(n) for n in range(8)))
    assert listings.count(True) == 1
    assert members.count(True) == 1
    assert len(await registry.listings_of(NETWORK_ID, MEMBER_B)) == 1
    assert (
        len([m for m in await registry.memberships(NETWORK_ID) if m.member_tenant_id == "tenant-d"])
        == 1
    )


# What the statements can reach


async def test_a_registry_statement_answers_the_same_whatever_scope_is_bound(
    registry: Neo4jNetworkRegistry,
) -> None:
    await _world(registry)
    expected = await registry.get_network(NETWORK_ID)
    assert expected is not None
    with bind_tenant("tenant-b"):
        assert await registry.get_network(NETWORK_ID) == expected
    with bind_network(NETWORK_ID):
        assert await registry.get_network(NETWORK_ID) == expected


async def test_a_read_returns_registry_nodes_only_when_the_graph_holds_lookalike_data(
    registry: Neo4jNetworkRegistry, harness_driver: AsyncDriver
) -> None:
    """A tenant's node with the same id and properties as a registry node is not read."""
    await _world(registry)
    await registry.create_grant(make_grant())
    await _run(
        harness_driver,
        "CREATE (:Observation {id: $id, status: 'approved', networkId: $net, "
        "grantorTenantId: $tenant, scope: 'capacity', tenantId: 'tenant-b'})",
        id="grant-b-capacity",
        net=NETWORK_ID,
        tenant=MEMBER_B,
    )
    try:
        assert [g.id for g in await registry.grants(NETWORK_ID)] == ["grant-b-capacity"]
        assert len(await registry.active_grants_for(MEMBER_B, GrantScope.CAPACITY, NOW)) == 1
    finally:
        await _run(harness_driver, "MATCH (n:Observation {id: 'grant-b-capacity'}) DETACH DELETE n")


@pytest.mark.parametrize("query_id", sorted(GLOBAL_WRITE_IDS))
async def test_a_write_statement_changes_no_node_that_is_not_a_registry_node(
    query_id: str, registry: Neo4jNetworkRegistry, harness_driver: AsyncDriver
) -> None:
    """Run each write against a graph that also holds a lookalike tenant node: the lookalike is
    untouched, whatever the statement matched or created."""
    await _world(registry)
    await _run(
        harness_driver,
        "CREATE (:Observation {id: 'lookalike', networkId: $net, memberTenantId: $m, "
        "status: 'invited', tenantId: 'tenant-b'})",
        net=NETWORK_ID,
        m=MEMBER_B,
    )
    before = await _rows(
        harness_driver, "MATCH (n:Observation {id: 'lookalike'}) RETURN properties(n) AS p"
    )
    try:
        grant = make_grant(id="grant-extra")
        calls = {
            "Q-NETWORK-CREATE": lambda: registry.create_network(
                make_network(id="net-extra"), SETTINGS
            ),
            "Q-NETWORK-SAVE": lambda: registry.save_network(
                make_network(), SETTINGS, expected_status=NetworkStatus.ACTIVE
            ),
            "Q-NETWORK-MEMBER-CREATE": lambda: registry.create_membership(make_member("tenant-e")),
            "Q-NETWORK-MEMBER-SAVE": lambda: registry.save_membership(
                make_member(MEMBER_B), expected_status=MembershipStatus.ACTIVE
            ),
            "Q-NETWORK-GRANT-CREATE": lambda: registry.create_grant(grant),
            "Q-NETWORK-GRANT-SAVE": lambda: registry.save_grant(
                grant, expected_status=GrantStatus.APPROVED
            ),
            "Q-NETWORK-LISTING-CREATE": lambda: registry.create_listing(make_listing()),
            "Q-NETWORK-LISTING-SAVE": lambda: registry.save_listing(
                make_listing(), expected_status=ListingStatus.ADMITTED
            ),
        }
        # A save with no row to match is a Conflict: it still must change nothing else.
        with contextlib.suppress(Conflict):
            await calls[query_id]()
    finally:
        after = await _rows(
            harness_driver, "MATCH (n:Observation {id: 'lookalike'}) RETURN properties(n) AS p"
        )
        await _run(harness_driver, "MATCH (n:Observation {id: 'lookalike'}) DETACH DELETE n")
    assert before == after


async def test_no_registry_node_is_counted_unstamped_by_the_invariant_check(
    registry: Neo4jNetworkRegistry, connection: Neo4jConnection
) -> None:
    from diucs.adapters.outbound.graph_store.invariants import Neo4jTenantInvariants

    await _world(registry)
    await registry.create_grant(make_grant())
    await registry.create_listing(make_listing())
    report = await Neo4jTenantInvariants(connection).check()
    labels = {label for group in report.unstamped for label in group.labels}
    assert not labels & {"Network", "NetworkMembership", "Grant", "Listing"}


async def test_the_registry_statements_run_only_through_the_global_runner(
    harness_driver: AsyncDriver,
) -> None:
    query = REGISTRY.get("Q-NETWORK-GET")

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await run_global_query(tx, query, id=NETWORK_ID)

    assert await read_tx(harness_driver, work) == []
