"""The world of the network tests (TEN-060, DEC-544): an owner, three members, an outsider and the
network between them, built through the product's own ports, plus the invariants of a network
scope.

All values are invented. Every member holds one service with the same ids (`svc-1`, `rep-1`,
`crit-1`) and a name that tells it apart (`Service m1`), plus text in the fields a projection must
never carry (the service comment, the reporter role, the criteria change reason: the poison). The
owner has admitted each service and each member has granted all three scopes. `run_projector`
runs the producer in a member's scope and the apply step in the network's, in process, in two
units of work that are never nested, as the workers do.

It only builds and drives; it asserts nothing. The tests of `tests/integration/graph_store/
test_network_scope_isolation.py` look at the result.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.invariants import Neo4jTenantInvariants
from diucs.adapters.outbound.graph_store.network_registry import Neo4jNetworkRegistry
from diucs.adapters.outbound.graph_store.scope_labels import (
    NETWORK_ONLY_LABELS,
    SCOPE_GENERIC_LABELS,
)
from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork, neo4j_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.invariants import InvariantReport
from diucs.application.ports.outbound.projection import ProjectionEndReason
from diucs.application.projection import to_body
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.application.use_cases.apply_projection import ApplyProjection, ApplyResult
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.domain.events import ProjectionRequested
from diucs.domain.model.network import (
    Grant,
    GrantApprover,
    GrantPurpose,
    GrantScope,
    GrantStatus,
    Listing,
    MembershipEndReason,
    MembershipStatus,
    Network,
    NetworkStatus,
    accept_membership,
    activate_network,
    end_membership,
    invite_member,
    owner_membership,
)
from diucs.domain.rules.grant import (
    approve_grant,
    end_grant,
    lapse_grants_for_member,
    propose_grant,
)
from diucs.domain.rules.listing import admit_listing, request_listing
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION
from tests.support.network_samples import (
    ACCOUNT_B,
    ACCOUNT_OWNER,
    AGREEMENT,
    NOW,
    SETTINGS,
    T0,
)
from tests.support.projection_samples import (
    SERVICE_ID,
    sample_capacity_projection,
    sample_criteria,
    sample_profile,
    sample_report,
)
from tests.support.tenancy import RunIdentity

# Each check returns the offending rows (a label set or a relationship type and a count, never a
# value) and nothing when the scope is sound. Read-only text, written out in full.
NETWORK_INVARIANTS: Final[dict[str, str]] = {
    "projection-outside-a-network-scope": (
        "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'Projected' "
        "OR l IN ['ProjectionSource', 'ProjectionCursor']) "
        "AND (n.tenantId IS NULL OR NOT n.tenantId STARTS WITH 'net-') "
        "RETURN labels(n) AS labels, count(*) AS n"
    ),
    "source-tenant-on-a-tenant-node": (
        "MATCH (n) WHERE n.sourceTenantId IS NOT NULL AND NOT any(l IN labels(n) "
        "WHERE l STARTS WITH 'Projected' OR l IN ['ProjectionSource', 'ProjectionCursor', "
        "'Listing']) RETURN labels(n) AS labels, count(*) AS n"
    ),
    "tenant-data-in-a-network-scope": (
        "MATCH (n) WHERE n.tenantId STARTS WITH 'net-' "
        "AND NOT any(l IN labels(n) WHERE l IN $allowed) "
        "RETURN labels(n) AS labels, count(*) AS n"
    ),
    "relationship-between-scopes": (
        "MATCH (a)-[r]->(b) WHERE a.tenantId IS NOT NULL AND b.tenantId IS NOT NULL "
        "AND a.tenantId <> b.tenantId RETURN type(r) AS type, count(*) AS n"
    ),
    "source-tenant-is-not-a-tenant-id": (
        "MATCH (n) WHERE n.sourceTenantId IS NOT NULL AND n.sourceTenantId STARTS WITH 'net-' "
        "RETURN labels(n) AS labels, count(*) AS n"
    ),
}


@dataclass(frozen=True, slots=True)
class WorldIds:
    owner: str
    members: tuple[str, str, str]
    outsider: str
    network: str
    other_network: str


def world_ids(identity: RunIdentity) -> WorldIds:
    """Five tenant ids and two network ids derived from the run, so two runs never share one. The
    run tenant is the base: its suffixed forms are valid tenant ids that no sweeper owns, so the
    world cleans up after itself."""
    base = identity.tenant_id
    return WorldIds(
        owner=f"{base}-o",
        members=(f"{base}-m1", f"{base}-m2", f"{base}-m3"),
        outsider=f"{base}-x",
        network=identity.network_id,
        other_network=f"{identity.network_id}-b",
    )


class _Recorder:
    def __init__(self) -> None:
        self.sent: list[ProjectionRequested] = []

    async def publish(self, request: ProjectionRequested) -> None:
        self.sent.append(request)


class NetworkWorld:
    def __init__(self, driver: AsyncDriver, connection: Neo4jConnection, ids: WorldIds) -> None:
        self.driver = driver
        self.connection = connection
        self.ids = ids
        self.registry = Neo4jNetworkRegistry(connection)
        self.network = _network(ids)
        self.poison: dict[str, tuple[str, ...]] = {}
        self._message = 0
        self._recorder = _Recorder()
        self._producer = ProjectNetwork(
            neo4j_uow_factory(driver, read_only=True),
            self.registry,
            self._recorder,
            FixedClock(NOW),
        )
        self._apply = ApplyProjection(
            neo4j_uow_factory(driver), self.registry, FixedClock(NOW + timedelta(minutes=1))
        )

    # ---- building

    @classmethod
    async def build(
        cls, driver: AsyncDriver, connection: Neo4jConnection, ids: WorldIds
    ) -> NetworkWorld:
        world = cls(driver, connection, ids)
        await world.cleanup()
        await world.registry.create_network(world.network, SETTINGS)
        await world.registry.create_membership(owner_membership(world.network, "mem-owner", T0))
        for member in ids.members:
            invited = invite_member(world.network, [], id=f"mem-{member}", tenant_id=member, now=T0)
            await world.registry.create_membership(invited)
            await world.registry.save_membership(
                world._active_membership(member), expected_status=invited.status
            )
            for grant in world.grants_for(member, *GrantScope):
                await world.registry.create_grant(grant)
            await world.registry.create_listing(world._admitted_listing(member))
            await world._seed_member(member)
        with bind_network(ids.network):
            await ensure_audit_head(driver)
        return world

    def service_name(self, member: str) -> str:
        return f"Service {member.rsplit('-', 1)[1]}"

    def grants_for(self, member: str, *scopes: GrantScope, approved: bool = True) -> list[Grant]:
        """The grants a member gives for these scopes, approved by the member and by the owner (or
        only proposed), effective from two hours after the network was made."""
        grants = []
        for scope in scopes:
            grant = propose_grant(
                id=f"grant-{member}-{scope.value}",
                network_id=self.ids.network,
                grantor_tenant_id=member,
                scope=scope,
                purpose=GrantPurpose.NETWORK_CAPACITY_VIEW,
                effective_from=T0 + timedelta(hours=2),
                effective_to=None,
                agreement=AGREEMENT,
                allowlist_version=PROJECTION_ALLOWLIST_VERSION,
                proposed_by_account_ref=ACCOUNT_B,
                proposed_at=T0 + timedelta(hours=2),
            )
            if approved:
                grant = approve_grant(
                    grant,
                    approver=GrantApprover.GRANTOR,
                    approver_tenant_id=member,
                    network_owner_tenant_id=self.ids.owner,
                    account_ref=ACCOUNT_B,
                    now=T0 + timedelta(hours=3),
                )
                grant = approve_grant(
                    grant,
                    approver=GrantApprover.OWNER,
                    approver_tenant_id=self.ids.owner,
                    network_owner_tenant_id=self.ids.owner,
                    account_ref=ACCOUNT_OWNER,
                    now=T0 + timedelta(hours=4),
                )
            grants.append(grant)
        return grants

    def _active_membership(self, member: str) -> Any:
        invited = invite_member(self.network, [], id=f"mem-{member}", tenant_id=member, now=T0)
        return accept_membership(
            self.network,
            invited,
            agreement=AGREEMENT,
            account_ref="acct-accept-001",
            now=T0 + timedelta(hours=1),
        )

    def _admitted_listing(self, member: str) -> Listing:
        listing = request_listing(
            [],
            self._active_membership(member),
            id=f"lst-{member}",
            network_id=self.ids.network,
            source_service_id=SERVICE_ID,
            now=T0 + timedelta(hours=5),
        )
        return admit_listing(
            listing,
            by_tenant_id=self.ids.owner,
            owner_tenant_id=self.ids.owner,
            account_ref=ACCOUNT_OWNER,
            now=T0 + timedelta(hours=6),
        )

    async def _seed_member(self, member: str) -> None:
        marks = (f"poison-comment-{member}", f"poison-role-{member}", f"poison-reason-{member}")
        self.poison[member] = marks
        with bind_tenant(member):
            async with neo4j_uow_factory(self.driver)() as uow:
                await uow.services.save(
                    sample_profile(name=self.service_name(member), comment=marks[0])
                )
                await uow.capacity.add(sample_report(performer_role_id=marks[1]))
                await uow.criteria.add(sample_criteria(change_reason=marks[2]))
                await uow.commit()

    # ---- driving

    async def _deliver(self, request: ProjectionRequested) -> ApplyResult:
        self._message += 1
        with bind_network(self.ids.network):
            return await self._apply.execute(
                request,
                message_id=f"world-{self._message}",
                source_tenant_id=request.source_tenant_id,
            )

    async def produce_as(self, tenant: str) -> list[ProjectionRequested]:
        """What the producer publishes for one tenant's service, without applying it."""
        self._recorder.sent.clear()
        with bind_tenant(tenant):
            await self._producer.project_all(SERVICE_ID)
        return list(self._recorder.sent)

    async def run_projector(self, only: str | None = None) -> dict[str, list[ApplyResult]]:
        """Produce and apply for every member (or one): the producer in the member's scope, then
        each message in the network's, one unit of work at a time."""
        results: dict[str, list[ApplyResult]] = {}
        for member in self.ids.members if only is None else (only,):
            results[member] = [await self._deliver(r) for r in await self.produce_as(member)]
        return results

    async def forge_from(self, sender: str) -> ApplyResult:
        """A capacity message that names `sender` as its source and a grant it does not hold."""
        return await self._deliver(self._forged(sender, f"grant-{sender}-capacity"))

    async def forge_with_grant_of(self, *, sender: str, grant_owner: str) -> ApplyResult:
        return await self._deliver(self._forged(sender, f"grant-{grant_owner}-capacity"))

    def _forged(self, sender: str, grant_id: str) -> ProjectionRequested:
        capacity = sample_capacity_projection()
        return ProjectionRequested(
            network_id=self.ids.network,
            source_tenant_id=sender,
            grant_id=grant_id,
            grant_version=1,
            kind=GrantScope.CAPACITY,
            source_service_id=SERVICE_ID,
            source_version=capacity.source_version,
            allowlist_version=PROJECTION_ALLOWLIST_VERSION,
            body=to_body(capacity),
            at=NOW,
        )

    async def end_grant(self, member: str, scope: GrantScope) -> None:
        grant = await self.registry.get_grant(f"grant-{member}-{scope.value}")
        assert grant is not None
        ended = end_grant(grant, by_tenant_id=member, account_ref=ACCOUNT_B, now=NOW)
        await self.registry.save_grant(ended, expected_status=GrantStatus.APPROVED)

    async def leave(self, member: str) -> int:
        """The member leaves: its membership ends, its grants lapse, and in the network scope its
        sources end and its live rows are marked, with the leave date. Returns the rows marked."""
        row = await self.registry.active_membership(self.ids.network, member)
        assert row is not None
        left = end_membership(self.network, row, reason=MembershipEndReason.LEFT, now=NOW)
        await self.registry.save_membership(left, expected_status=MembershipStatus.ACTIVE)
        lapsed = lapse_grants_for_member(await self.registry.grants_of(member), row, now=NOW)
        for grant in lapsed:
            await self.registry.save_grant(grant, expected_status=GrantStatus.APPROVED)
        marked = 0
        with bind_network(self.ids.network):
            async with Neo4jUnitOfWork(self.driver) as uow:
                for kind in GrantScope:
                    await uow.projections.end_source(
                        member, kind, at=NOW, reason=ProjectionEndReason.LEFT
                    )
                    marked += await uow.projections.mark_ended(
                        member, kind, at=NOW, reason=ProjectionEndReason.LEFT
                    )
                await uow.commit()
        return marked

    # ---- looking

    async def view(self, *, live_only: bool = True) -> tuple[Any, Any, Any]:
        with bind_network(self.ids.network):
            async with Neo4jUnitOfWork(self.driver, read_only=True) as uow:
                return (
                    await uow.network_view.services(live_only=live_only),
                    await uow.network_view.capacities(live_only=live_only),
                    await uow.network_view.criteria(live_only=live_only),
                )

    @asynccontextmanager
    async def reader(self, member: str) -> AsyncIterator[Any]:
        with bind_tenant(member):
            async with Neo4jUnitOfWork(self.driver, read_only=True) as uow:
                yield uow

    async def invariants(self) -> dict[str, list[dict[str, Any]]]:
        allowed = sorted(NETWORK_ONLY_LABELS | SCOPE_GENERIC_LABELS)
        found: dict[str, list[dict[str, Any]]] = {}
        for name, cypher in NETWORK_INVARIANTS.items():

            async def read(tx: AsyncManagedTransaction, text: str = cypher) -> list[dict[str, Any]]:
                return await (await tx.run(text, allowed=allowed)).data()

            async with self.driver.session() as session:
                found[name] = await session.execute_read(read)
        return found

    async def global_invariants(self) -> InvariantReport:
        return await Neo4jTenantInvariants(self.connection).check()

    # ---- cleaning

    async def cleanup(self) -> None:
        scopes = [
            self.ids.network,
            self.ids.other_network,
            self.ids.owner,
            self.ids.outsider,
            *self.ids.members,
        ]

        async def work(tx: AsyncManagedTransaction) -> None:
            await tx.run("MATCH (n) WHERE n.tenantId IN $scopes DETACH DELETE n", scopes=scopes)
            await tx.run(
                "MATCH (n) WHERE n:Network OR n:NetworkMembership OR n:Grant OR n:Listing "
                "DETACH DELETE n"
            )

        async with self.driver.session() as session:
            await session.execute_write(work)


def _network(ids: WorldIds) -> Network:
    draft = Network(
        id=ids.network,
        name="Sample network",
        owner_tenant_id=ids.owner,
        status=NetworkStatus.DRAFT,
        agreement=None,
        created_at=T0,
        closed_at=None,
    )
    return activate_network(draft, AGREEMENT, T0)
