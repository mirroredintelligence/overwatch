"""The rig of the network administration integration tests (TEN-077, TEN-078, TEN-061, TEN-074):
the product's own use cases over a real Neo4j, driven the way the workers drive them.

An owner and three members (the world of TEN-060, `network_world.py`) hold tenant data (one service
with the same ids, a figure, criteria, and poison in the fields a projection must never carry) but
nothing is shared and no network exists until a test makes one through `CreateNetwork`. The rig has
one clock that a test moves, the use cases wired to the real registry, the real units of both kinds
and a tenant directory of the five organisations, and the two workers' halves: `deliver_events`
reads each acting tenant's outbox and hands every governance event to the projector's handler
(`NetworkGovernance`), and `project` runs the producer for a member and the apply step for what it
published. Nothing is sent anywhere: the publisher records.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.network_registry import Neo4jNetworkRegistry
from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork, neo4j_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.tenancy import (
    ScopeId,
    bind_network,
    bind_scope,
    bind_tenant,
    current_scope_or_none,
)
from diucs.application.use_cases.apply_projection import ApplyProjection, ApplyResult
from diucs.application.use_cases.grants import (
    ApproveGrant,
    DeclineGrant,
    EndGrant,
    ProposeGrant,
    QueryGrants,
    ReviseGrant,
    SupersedeDueGrants,
)
from diucs.application.use_cases.listing_admission import (
    DecideListing,
    QueryListings,
    RequestListing,
)
from diucs.application.use_cases.membership import (
    AcceptMembership,
    InviteMember,
    LeaveNetwork,
    RemoveMember,
)
from diucs.application.use_cases.network_admin import (
    CreateNetwork,
    GovernanceRecorder,
    QueryNetworkAdmin,
    RecordAgreement,
)
from diucs.application.use_cases.network_governance import GovernanceOutcome, NetworkGovernance
from diucs.application.use_cases.network_leave import EndProjections
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.application.use_cases.projection_boundaries import RunProjectionHeartbeat
from diucs.application.use_cases.projection_reconcile import ReconcileProjection
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.domain.codes import Role
from diucs.domain.events import ProjectionRequested
from diucs.domain.model.network import GrantScope
from tests.support.network_admin_fakes import MemoryDirectory, active_tenant, person
from tests.support.network_world import NetworkWorld, WorldIds
from tests.support.uow import ensure_audit_heads

START = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)


class _Recorder:
    def __init__(self) -> None:
        self.sent: list[ProjectionRequested] = []

    async def publish(self, request: ProjectionRequested) -> None:
        self.sent.append(request)


class RunIds:
    """Record ids no other run shares: the run's token and a counter."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"{self._token}-{self._n:04d}"


@dataclass(frozen=True, slots=True)
class People:
    """Actors of the five organisations, one person for each role a test needs."""

    owner_admin: Actor
    owner_second: Actor
    operator: Actor
    admins: tuple[Actor, ...]  # tenant administrators of the three members
    leads: tuple[Actor, ...]
    outsider_admin: Actor


class AdminRig:
    def __init__(self, driver: AsyncDriver, connection: Neo4jConnection, ids: WorldIds) -> None:
        self.driver = driver
        self.connection = connection
        self.ids = ids
        self.world = NetworkWorld(driver, connection, ids)
        self.registry = Neo4jNetworkRegistry(connection)
        self.clock = FixedClock(START)
        self.token = ids.network.removeprefix("net-")
        self.directory = MemoryDirectory(
            active_tenant(ids.owner, "Owner Org"),
            *(active_tenant(m, f"Member {i + 1} Org") for i, m in enumerate(ids.members)),
            active_tenant(ids.outsider, "Outsider Org"),
        )
        self.published = _Recorder()
        tenant_factory = neo4j_uow_factory(driver, clock=self.clock)
        network_factory = neo4j_uow_factory(driver, clock=self.clock)
        network_read = neo4j_uow_factory(driver, clock=self.clock, read_only=True)
        self.tenant_factory = tenant_factory
        self.network_factory = network_factory
        self.ids_gen = RunIds(self.token)
        self.recorder = GovernanceRecorder(
            tenant_factory, network_factory, self.ids_gen, self.clock
        )
        reg: Any = self.registry
        directory: Any = self.directory
        self.heads = _Heads(driver)
        self.create_network = CreateNetwork(
            reg, directory, self.heads, self.recorder, RunIds(self.token + "m"), self.clock
        )
        self.record_agreement = RecordAgreement(reg, self.recorder, self.clock)
        self.ends = EndProjections(network_factory, reg, self.clock)
        self.reconcile = ReconcileProjection(network_read, self.ends, reg, self.clock)
        self.invite = InviteMember(
            reg, directory, self.recorder, RunIds(self.token + "i"), self.clock
        )
        self.accept = AcceptMembership(reg, self.recorder, self.clock)
        self.leave = LeaveNetwork(reg, self.ends, self.recorder, self.clock)
        self.remove = RemoveMember(reg, self.ends, self.recorder, self.clock)
        self.request_listing = RequestListing(
            reg, tenant_factory, self.recorder, RunIds(self.token + "l"), self.clock
        )
        self.decide_listing = DecideListing(reg, self.recorder, self.clock)
        self.propose = ProposeGrant(reg, self.recorder, RunIds(self.token + "g"), self.clock)
        self.revise = ReviseGrant(reg, self.recorder, RunIds(self.token + "r"), self.clock)
        self.approve = ApproveGrant(reg, self.recorder, self.clock)
        self.decline = DeclineGrant(reg, self.recorder, self.clock)
        self.end_grant = EndGrant(reg, self.ends, self.recorder, self.clock)
        self.supersede = SupersedeDueGrants(reg, self.recorder, self.clock)
        self.admin_query = QueryNetworkAdmin(reg, directory, network_read)
        self.grant_query = QueryGrants(reg, directory, self.clock)
        self.listing_query = QueryListings(reg, directory)
        self.producer = ProjectNetwork(
            neo4j_uow_factory(driver, clock=self.clock, read_only=True),
            reg,
            self.published,
            self.clock,
        )
        self.apply = ApplyProjection(network_factory, reg, self.clock)
        self.governance = NetworkGovernance(
            reg, self.ends, self.producer, tenant_factory, self.ids_gen, self.clock, directory
        )
        self.heartbeat = RunProjectionHeartbeat(
            tenant_factory, self.ids_gen, self.clock, reg, self.producer, self.reconcile
        )
        self.access = NetworkAccess(reg, directory)
        self.board = QueryNetworkBoard(network_read, self.access, self.clock)
        self._message = 0
        self._reports = 0
        self.people = self._people()

    # ---- people

    def _people(self) -> People:
        ids = self.ids
        return People(
            owner_admin=person(ids.owner, Role.NETWORK_ADMIN, "owner-admin"),
            owner_second=person(ids.owner, Role.NETWORK_ADMIN, "owner-second"),
            operator=person(ids.owner, Role.PLATFORM_OPERATOR, "operator"),
            admins=tuple(person(m, Role.TENANT_ADMIN, "admin") for m in ids.members),
            leads=tuple(person(m, Role.LEAD, "lead") for m in ids.members),
            outsider_admin=person(ids.outsider, Role.TENANT_ADMIN, "admin"),
        )

    def viewer(self, member: str, role: Role = Role.ADVISOR) -> Actor:
        return person(member, role, "viewer")

    # ---- building

    @classmethod
    async def build(
        cls, driver: AsyncDriver, connection: Neo4jConnection, ids: WorldIds
    ) -> AdminRig:
        rig = cls(driver, connection, ids)
        await rig.world.cleanup()
        await ensure_audit_heads(driver, ids.owner, *ids.members, ids.outsider)
        for member in ids.members:
            await rig.world._seed_member(member)
        return rig

    async def cleanup(self) -> None:
        await self.world.cleanup()

    # ---- as a tenant

    @asynccontextmanager
    async def as_tenant(self, tenant: str) -> AsyncIterator[None]:
        with bind_tenant(tenant):
            yield

    async def make_network(self, *, agreement_version: int = 1) -> str:
        with bind_tenant(self.ids.owner):
            from diucs.application.use_cases.network_admin import CreateNetworkCommand

            await self.create_network.execute(
                CreateNetworkCommand(
                    actor=self.people.operator,
                    network_id=self.ids.network,
                    name="Sample network",
                    agreement_reference="DSA-2026-1",
                    agreement_version=agreement_version,
                    system_name="Sample capacity board",
                    pathway_name="Sample urgent pathway",
                )
            )
        return self.ids.network

    async def join(self, member: str, admin: Actor) -> str:
        """Invite and accept: the member is active in the network. Returns the membership id."""
        from diucs.application.use_cases.membership import (
            AcceptMembershipCommand,
            InviteMemberCommand,
        )

        with bind_tenant(self.ids.owner):
            invited = await self.invite.execute(
                InviteMemberCommand(self.people.owner_admin, self.ids.network, member)
            )
        with bind_tenant(member):
            await self.accept.execute(AcceptMembershipCommand(admin, invited.membership_id, 1))
        return invited.membership_id

    async def share(
        self,
        member: str,
        admin: Actor,
        *scopes: GrantScope,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
    ) -> list[str]:
        """Propose, approve on both sides and (when a service is listed) leave it ready to project:
        the grants of these scopes are effective."""
        from diucs.application.use_cases.grants import ApproveGrantCommand, ProposeGrantCommand

        ids = []
        for scope in scopes:
            with bind_tenant(member):
                gid = await self.propose.execute(
                    ProposeGrantCommand(
                        admin, self.ids.network, scope, effective_from, effective_to
                    )
                )
                await self.approve.execute(ApproveGrantCommand(admin, gid))
            with bind_tenant(self.ids.owner):
                await self.approve.execute(ApproveGrantCommand(self.people.owner_admin, gid))
            ids.append(gid)
        return ids

    async def list_service(self, member: str, admin: Actor, service_id: str = "svc-1") -> str:
        from diucs.application.use_cases.listing_admission import (
            DecideListingCommand,
            ListingDecision,
            RequestListingCommand,
        )

        with bind_tenant(member):
            lid = await self.request_listing.execute(
                RequestListingCommand(admin, self.ids.network, service_id)
            )
        with bind_tenant(self.ids.owner):
            await self.decide_listing.execute(
                DecideListingCommand(
                    self.people.owner_admin, self.ids.network, lid, ListingDecision.ADMIT
                )
            )
        return lid

    async def add_report(self, member: str, at: datetime, *, value: int = 4) -> None:
        """A fresh figure from the member's reporter, in the member's own scope."""
        from tests.support.projection_samples import sample_report

        self._reports += 1
        with bind_tenant(member):
            async with self.tenant_factory() as uow:
                await uow.capacity.add(
                    sample_report(id=f"rep-fresh-{self._reports}", effective_at=at, value=value)
                )
                await uow.commit()

    # ---- the workers' halves

    async def deliver_events(self) -> list[tuple[str, str, GovernanceOutcome]]:
        """What the relay and the projector's governance subscription do: every pending outbox
        message of every organisation that is a governance event goes to the handler, and is marked
        published. Returns (acting tenant, event type, outcome)."""
        done: list[tuple[str, str, GovernanceOutcome]] = []
        for tenant in (self.ids.owner, *self.ids.members, self.ids.outsider):
            pending = await self.pending_outbox(tenant)
            for message in pending:
                if message.topic == "network.events":
                    with bind_tenant(tenant):  # the relay's binding: the message's tenant
                        outcome = await self.governance.handle(
                            message.event_type, message.payload, bus_tenant=tenant
                        )
                    done.append((tenant, message.event_type, outcome))
            with bind_tenant(tenant):
                async with self.tenant_factory() as uow:
                    for message in pending:
                        await uow.outbox.mark_published(message.id, self.clock.now())
                    await uow.commit()
        return done

    async def apply_pending(self) -> list[ApplyResult]:
        """Apply, in the network's scope and one unit at a time, every projection message the
        producer has published since the last time (what the projection queue's consumer does)."""
        results: list[ApplyResult] = []
        for request in list(self.published.sent):
            self._message += 1
            with bind_network(self.ids.network):
                results.append(
                    await self.apply.execute(
                        request,
                        message_id=f"rig-{self.token}-{self._message}",
                        source_tenant_id=request.source_tenant_id,
                    )
                )
        self.published.sent.clear()
        return results

    async def project(self, member: str, service_id: str = "svc-1") -> list[ApplyResult]:
        """The producer in the member's scope, then each message it published applied in the
        network's."""
        self.published.sent.clear()
        with bind_tenant(member):
            await self.producer.project_all(service_id)
        return await self.apply_pending()

    async def beat(self, member: str, work_id: str) -> Any:
        """One run of the member's projection heartbeat, and the messages it published applied."""
        from diucs.application.use_cases.projection_boundaries import RunProjectionHeartbeatCommand

        self.published.sent.clear()
        with bind_tenant(member):
            result = await self.heartbeat.execute(RunProjectionHeartbeatCommand(work_id))
        await self.apply_pending()
        return result

    async def verify_chain(self, scope: str) -> bool:
        """True when every link of the scope's audit chain is intact: contiguous numbers, each link
        hashed over the one before it (the scope's own genesis first), and the head at the last
        link. Read here, link by link, because the audit port verifies a tenant's chain only and a
        network chain has no tenant to parse its entries under (a known issue)."""
        from diucs.adapters.outbound.audit_neo4j.audit_log import chain_hash_over, genesis_hash_for
        from tests.support.neo4j import read_tx, tx_run

        async def links(tx: AsyncManagedTransaction) -> tuple[list[dict[str, Any]], list[Any]]:
            chain = await tx_run(
                tx,
                "MATCH (e:AuditEvent:ChainLink {tenantId: $tenant}) RETURN e.seq AS seq, "
                "e.previousHash AS previousHash, e.chainHash AS chainHash, "
                "e.entryJson AS entryJson ORDER BY e.seq",
            )
            head = await tx_run(
                tx,
                "MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) "
                "RETURN h.lastHash AS lastHash, h.lastSeq AS lastSeq",
            )
            return await chain.data(), await head.data()

        with bind_scope(ScopeId.parse(scope)):
            rows, heads = await read_tx(self.driver, links)
        previous = genesis_hash_for(scope)
        for index, row in enumerate(rows, start=1):
            if row["seq"] != index or row["previousHash"] != previous:
                return False
            if chain_hash_over(previous, str(row["entryJson"])) != row["chainHash"]:
                return False
            previous = str(row["chainHash"])
        return bool(heads) and heads[0]["lastHash"] == previous and heads[0]["lastSeq"] == len(rows)

    # ---- looking

    def reader(self, member: str) -> Any:
        """A read-only unit of a member's own scope."""
        return self.world.reader(member)

    async def view(self, *, live_only: bool = True) -> tuple[Any, Any, Any]:
        return await self.world.view(live_only=live_only)

    def rows_of(self, member: str, rows: Any) -> list[Any]:
        return [r for r in rows if r.source_tenant_id == member]

    async def count(self, scope: str, label: str) -> int:
        from tests.support.neo4j import read_tx

        async def work(tx: AsyncManagedTransaction) -> int:
            cypher = f"MATCH (n:{label} {{tenantId: $s}}) RETURN count(n) AS n"  # test-only text
            return int((await (await tx.run(cypher, s=scope)).data())[0]["n"])

        return await read_tx(self.driver, work)

    async def audit_use_cases(self, scope: str) -> list[str]:
        """The use cases of the audit entries of a scope, oldest first (the chain's own order)."""
        from tests.support.neo4j import read_tx

        async def work(tx: AsyncManagedTransaction) -> list[str]:
            rows = await (
                await tx.run(
                    "MATCH (e:AuditEvent {tenantId: $s}) RETURN e.useCase AS u ORDER BY e.seq",
                    s=scope,
                )
            ).data()
            return [r["u"] for r in rows]

        return await read_tx(self.driver, work)

    async def pending_outbox(self, tenant: str) -> list[Any]:
        with bind_tenant(tenant):
            async with Neo4jUnitOfWork(self.driver, read_only=True) as uow:
                return list(await uow.outbox.pending(500))

    def tick(self, delta: timedelta) -> None:
        self.clock.advance(delta)


class _Heads:
    """The scope provisioner on the real chain: the head of whatever scope is bound."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    async def ensure_audit_head(self) -> None:
        assert current_scope_or_none() is not None
        await ensure_audit_head(self._driver)
