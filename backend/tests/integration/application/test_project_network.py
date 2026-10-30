"""The network projector end to end on a real Neo4j (TEN-054, DEC-543, DEC-132 item 4).

Written, not run, in build wave 5 (the owner's instruction: the whole integration suite runs once,
on the merged tip).

A member (the run tenant) holds a service, a report and criteria. The owner (the other run tenant)
and the member are in one network; the member has granted capacity, directory and criteria, and the
owner has admitted the service. The producer reads in the member's scope and publishes; the apply
step writes in the network scope. The tests show: the projection arrives and reads back; nothing
arrives without a grant, an admitted listing or an active membership; a grant ended by its grantor,
or a member who left, stops it; a replay and an older message change nothing; the network scope
holds only allowlisted properties; and a second member's data never reaches the first's view.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.network_registry import Neo4jNetworkRegistry
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.application.use_cases.apply_projection import ApplyOutcome, ApplyProjection
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.domain.events import ProjectionRejectReason, ProjectionRequested
from diucs.domain.model.network import (
    GrantScope,
    GrantStatus,
    ListingStatus,
    MembershipStatus,
)
from diucs.domain.rules import projection as allowlist
from diucs.domain.rules.grant import end_grant
from tests.support.neo4j import read_tx, wipe_tenant
from tests.support.network_samples import (
    ACCOUNT_B,
    SETTINGS,
    make_grant,
    make_listing,
    make_member,
    make_network,
    make_owner_membership,
)
from tests.support.projection_samples import sample_criteria, sample_profile, sample_report

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
SERVICE = "svc-1"


class _Recorder:
    def __init__(self) -> None:
        self.sent: list[ProjectionRequested] = []

    async def publish(self, request: ProjectionRequested) -> None:
        self.sent.append(request)


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


async def _clean(driver: AsyncDriver, network: str) -> None:
    """The network scope's nodes and the registry records of the network, and no other run's."""
    await wipe_tenant(driver, network)


class World:
    """One network, its owner, one member holding the service, and the use cases."""

    def __init__(
        self,
        driver: AsyncDriver,
        connection: Neo4jConnection,
        tenant: str,
        owner: str,
        network: str,
    ) -> None:
        self.driver = driver
        self.tenant, self.owner, self.network = tenant, owner, network
        self.registry = Neo4jNetworkRegistry(connection)
        self.recorder = _Recorder()
        tenant_reader = neo4j_uow_factory(driver, read_only=True)
        self.producer = ProjectNetwork(tenant_reader, self.registry, self.recorder, FixedClock(NOW))
        self.apply = ApplyProjection(
            neo4j_uow_factory(driver), self.registry, FixedClock(NOW + timedelta(minutes=1))
        )

    async def build(self) -> None:
        net = make_network(id=self.network, owner=self.owner)
        await self.registry.create_network(net, SETTINGS)
        await self.registry.create_membership(make_owner_membership(net))
        await self.registry.create_membership(make_member(self.tenant, network=net))
        for scope in GrantScope:
            grant = make_grant(
                id=f"grant-{scope.value}", tenant=self.tenant, scope=scope, network_id=self.network
            )
            await self.registry.create_grant(grant)
        with bind_network(self.network):
            await ensure_audit_head(self.driver)

    async def admit(self) -> None:
        listing = make_listing(tenant=self.tenant)
        await self.registry.create_listing(replace(listing, network_id=self.network))

    async def seed_service(self) -> None:
        factory = neo4j_uow_factory(self.driver)
        async with factory() as uow:
            await uow.services.save(sample_profile())
            await uow.capacity.add(sample_report())
            await uow.criteria.add(sample_criteria(supersedes_id=None))
            await uow.commit()

    async def project(self) -> list[Any]:
        self.recorder.sent.clear()
        with bind_tenant(self.tenant):
            await self.producer.project_all(SERVICE)
        return list(self.recorder.sent)

    async def deliver(self, request: ProjectionRequested, message_id: str = "m-1") -> Any:
        with bind_network(self.network):
            return await self.apply.execute(
                request, message_id=message_id, source_tenant_id=request.source_tenant_id
            )

    async def view(self) -> tuple[Any, Any, Any]:
        factory = neo4j_uow_factory(self.driver, read_only=True)
        with bind_network(self.network):
            async with factory() as uow:
                return (
                    await uow.network_view.services(),
                    await uow.network_view.capacities(),
                    await uow.network_view.criteria(),
                )


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    other_tenant_id: str,
    network_id: str,
    clean_graph: None,
) -> AsyncIterator[World]:
    await _clean(harness_driver, network_id)
    built = World(harness_driver, connection, tenant_id, other_tenant_id, network_id)
    await built.build()
    await built.seed_service()
    yield built
    await _clean(harness_driver, network_id)


async def test_a_granted_and_admitted_service_arrives_and_reads_back(world: World) -> None:
    await world.admit()
    requests = await world.project()
    assert {r.kind for r in requests} == set(GrantScope)
    for number, request in enumerate(requests):
        result = await world.deliver(request, f"m-{number}")
        assert result.outcome is ApplyOutcome.APPLIED
    services, capacities, criteria = await world.view()
    assert [r.projection.service_name for r in services] == [sample_profile().name]
    assert [r.projection.value for r in capacities] == [sample_report().value]
    assert [r.projection.version for r in criteria] == [sample_criteria().version]
    assert {r.source_tenant_id for r in (*services, *capacities, *criteria)} == {world.tenant}


async def test_nothing_is_produced_before_the_owner_admits_the_service(world: World) -> None:
    assert await world.project() == []
    assert await world.view() == ([], [], [])


async def test_a_message_for_a_service_that_is_not_admitted_is_rejected_by_the_apply_step(
    world: World,
) -> None:
    await world.admit()
    [first, *_] = await world.project()
    other = replace(first, source_service_id="svc-unlisted")
    result = await world.deliver(other)
    assert result.reason in (
        ProjectionRejectReason.LISTING_NOT_ADMITTED,
        ProjectionRejectReason.INVALID_BODY,
    )
    assert await world.view() == ([], [], [])


async def test_a_replay_and_an_older_version_change_nothing(world: World) -> None:
    await world.admit()
    requests = {r.kind: r for r in await world.project()}
    capacity = requests[GrantScope.CAPACITY]
    assert (await world.deliver(capacity, "m-1")).outcome is ApplyOutcome.APPLIED
    assert (await world.deliver(capacity, "m-1")).outcome is ApplyOutcome.DUPLICATE
    again = await world.deliver(capacity, "m-2")
    assert again.outcome is ApplyOutcome.APPLIED  # an equal version is a replay: same row
    _, capacities, _ = await world.view()
    assert len(capacities) == 1


async def test_a_grant_ended_by_its_grantor_stops_the_next_projection(world: World) -> None:
    await world.admit()
    requests = {r.kind: r for r in await world.project()}
    grant = await world.registry.get_grant("grant-capacity")
    assert grant is not None
    ended = end_grant(grant, by_tenant_id=world.tenant, account_ref=ACCOUNT_B, now=NOW)
    await world.registry.save_grant(ended, expected_status=GrantStatus.APPROVED)
    result = await world.deliver(requests[GrantScope.CAPACITY])
    assert result.reason is ProjectionRejectReason.GRANT_NOT_EFFECTIVE
    assert [r for r in await world.project() if r.kind is GrantScope.CAPACITY] == []


async def test_a_member_who_left_projects_nothing_and_is_rejected(world: World) -> None:
    await world.admit()
    requests = await world.project()
    left = replace(
        make_member(world.tenant, status=MembershipStatus.LEFT), network_id=world.network
    )
    await world.registry.save_membership(left, expected_status=MembershipStatus.ACTIVE)
    assert (await world.deliver(requests[0])).reason is ProjectionRejectReason.MEMBER_NOT_ACTIVE
    assert await world.project() == []


async def test_a_suspended_listing_stops_new_projections(world: World) -> None:
    await world.admit()
    assert await world.project()
    listing = (await world.registry.listings_of(world.network, world.tenant))[0]
    from diucs.domain.model.network import ListingReason
    from diucs.domain.rules.listing import suspend_listing

    suspended = suspend_listing(
        listing,
        by_tenant_id=world.owner,
        owner_tenant_id=world.owner,
        reason=ListingReason.SAFETY_CONCERN,
        account_ref="acct-owner-0001",
        now=NOW,
    )
    await world.registry.save_listing(suspended, expected_status=ListingStatus.ADMITTED)
    assert await world.project() == []


async def test_the_network_scope_holds_only_allowlisted_properties_and_no_tenant_data(
    world: World, harness_driver: AsyncDriver
) -> None:
    await world.admit()
    for number, request in enumerate(await world.project()):
        await world.deliver(request, f"m-{number}")

    async def nodes(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (
            await tx.run(
                "MATCH (n {tenantId: $net}) RETURN labels(n) AS labels, properties(n) AS props",
                net=world.network,
            )
        ).data()

    rows = await read_tx(harness_driver, nodes)
    generic = {"AuditHead", "AuditEvent", "ChainLink", "Snapshot", "AuditRef", "Processed"}
    for row in rows:
        labels = set(row["labels"])
        if labels & generic:
            continue
        [label] = row["labels"]
        permitted = {s.prop for s in allowlist.ALLOWLIST.get(label, ())}
        assert set(row["props"]) <= permitted | allowlist.SYSTEM_PROPERTIES[label], label
    text = repr(rows)
    for poison in ("Both women only", "role-1", "role-2", "Added frailty"):
        assert poison not in text


async def test_the_audit_chain_of_the_network_records_each_write_by_id_only(
    world: World, harness_driver: AsyncDriver
) -> None:
    await world.admit()
    for number, request in enumerate(await world.project()):
        await world.deliver(request, f"m-{number}")

    async def entries(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (
            await tx.run(
                "MATCH (e:AuditEvent {tenantId: $net}) "
                "RETURN e.useCase AS use, e.entryJson AS json",
                net=world.network,
            )
        ).data()

    rows = await read_tx(harness_driver, entries)
    assert len(rows) == 3
    assert {r["use"] for r in rows} == {"ApplyProjection"}
    assert "UCR West" not in repr(rows)


async def test_a_tenant_scope_has_no_projected_rows_and_the_member_scope_is_untouched(
    world: World, harness_driver: AsyncDriver
) -> None:
    await world.admit()
    for number, request in enumerate(await world.project()):
        await world.deliver(request, f"m-{number}")

    async def count(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (
            await tx.run(
                "MATCH (n) WHERE n.tenantId = $t "
                "AND any(l IN labels(n) WHERE l STARTS WITH 'Projected') "
                "RETURN count(n) AS n",
                t=world.tenant,
            )
        ).data()

    assert (await read_tx(harness_driver, count))[0]["n"] == 0
