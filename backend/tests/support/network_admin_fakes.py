"""Recording fakes for the unit tests of the network administration use cases (TEN-056, TEN-077,
TEN-078, TEN-079).

There is no in-memory store of records (DEC-004): these fakes hold only what the use cases read and
write, so a test shows the order of the steps (one shared `log`), what is written and what is
refused. The registry fake keeps the real registry's guards (a create refuses a second live row, a
save needs the status the caller expects), so a use case that forgets them fails here as it would on
the graph; what is stored on a real graph is proved by the integration tests.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Self

from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.network import ActiveGrant, RegisteredNetwork
from diucs.application.ports.outbound.projection import ProjectionEndReason, SourceState
from diucs.application.tenancy import ScopeId, ScopeKind, current_scope_or_none
from diucs.domain.errors import Conflict
from diucs.domain.model.network import (
    Grant,
    GrantScope,
    GrantStatus,
    Listing,
    ListingStatus,
    MembershipStatus,
    Network,
    NetworkMembership,
    NetworkStatus,
)
from diucs.domain.model.network_settings import NetworkSettings
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.grant import may_project
from tests.support.network_samples import SETTINGS

_LIVE_LISTING = (ListingStatus.PENDING, ListingStatus.ADMITTED, ListingStatus.SUSPENDED)


class MemoryRegistry:
    """The network registry port over dicts, with its guards."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.log: list[str] = [] if log is None else log
        self.networks: dict[str, tuple[Network, NetworkSettings]] = {}
        self.members: dict[str, NetworkMembership] = {}
        self.grant_rows: dict[str, Grant] = {}
        self.listing_rows: dict[str, Listing] = {}
        self.fail_on: set[str] = set()

    # ---- reads

    async def get_network(self, network_id: str) -> RegisteredNetwork | None:
        found = self.networks.get(network_id)
        return None if found is None else RegisteredNetwork(*found)

    async def memberships(self, network_id: str) -> Sequence[NetworkMembership]:
        return [m for m in self.members.values() if m.network_id == network_id]

    async def memberships_of(self, tenant_id: str) -> Sequence[NetworkMembership]:
        return [m for m in self.members.values() if m.member_tenant_id == tenant_id]

    async def active_membership(self, network_id: str, tenant_id: str) -> NetworkMembership | None:
        return next(
            (
                m
                for m in self.members.values()
                if m.network_id == network_id
                and m.member_tenant_id == tenant_id
                and m.status is MembershipStatus.ACTIVE
            ),
            None,
        )

    async def get_grant(self, grant_id: str) -> Grant | None:
        return self.grant_rows.get(grant_id)

    async def grants(self, network_id: str) -> Sequence[Grant]:
        return [g for g in self.grant_rows.values() if g.network_id == network_id]

    async def grants_of(self, tenant_id: str) -> Sequence[Grant]:
        return [g for g in self.grant_rows.values() if g.grantor_tenant_id == tenant_id]

    async def active_grants_for(
        self, tenant_id: str, scope: GrantScope, now: datetime
    ) -> Sequence[ActiveGrant]:
        found: list[ActiveGrant] = []
        for grant in self.grant_rows.values():
            if grant.grantor_tenant_id != tenant_id or grant.scope is not scope:
                continue
            registered = self.networks.get(grant.network_id)
            membership = await self.active_membership(grant.network_id, tenant_id)
            if (
                registered is None
                or registered[0].status is not NetworkStatus.ACTIVE
                or membership is None
                or not may_project(grant, membership, now)
            ):
                continue
            found.append(ActiveGrant(RegisteredNetwork(*registered), grant, membership))
        return found

    async def get_listing(self, listing_id: str) -> Listing | None:
        return self.listing_rows.get(listing_id)

    async def listings(self, network_id: str) -> Sequence[Listing]:
        return [x for x in self.listing_rows.values() if x.network_id == network_id]

    async def listings_of(self, network_id: str, tenant_id: str) -> Sequence[Listing]:
        return [
            x
            for x in self.listing_rows.values()
            if x.network_id == network_id and x.source_tenant_id == tenant_id
        ]

    # ---- writes

    def _write(self, name: str) -> None:
        self.log.append(f"registry:{name}")
        if name in self.fail_on:
            raise ConnectionError("the registry is down")

    async def create_network(self, network: Network, settings: NetworkSettings) -> None:
        self._write("create_network")
        if network.id in self.networks:
            raise Conflict("the registry row is not as expected, so nothing was written")
        self.networks[network.id] = (network, settings)

    async def save_network(
        self, network: Network, settings: NetworkSettings, *, expected_status: NetworkStatus
    ) -> None:
        self._write("save_network")
        held = self.networks.get(network.id)
        if held is None or held[0].status is not expected_status:
            raise Conflict("the registry row is not as expected, so nothing was written")
        self.networks[network.id] = (network, settings)

    async def create_membership(self, membership: NetworkMembership) -> None:
        self._write("create_membership")
        if membership.id in self.members or any(
            m.network_id == membership.network_id
            and m.member_tenant_id == membership.member_tenant_id
            and m.status in (MembershipStatus.INVITED, MembershipStatus.ACTIVE)
            for m in self.members.values()
        ):
            raise Conflict("the registry row is not as expected, so nothing was written")
        self.members[membership.id] = membership

    async def save_membership(
        self, membership: NetworkMembership, *, expected_status: MembershipStatus
    ) -> None:
        self._write("save_membership")
        held = self.members.get(membership.id)
        if held is None or held.status is not expected_status:
            raise Conflict("the registry row is not as expected, so nothing was written")
        self.members[membership.id] = membership

    async def create_grant(self, grant: Grant) -> None:
        self._write("create_grant")
        if grant.id in self.grant_rows or any(
            g.network_id == grant.network_id
            and g.grantor_tenant_id == grant.grantor_tenant_id
            and g.scope is grant.scope
            and g.version == grant.version
            for g in self.grant_rows.values()
        ):
            raise Conflict("the registry row is not as expected, so nothing was written")
        self.grant_rows[grant.id] = grant

    async def save_grant(self, grant: Grant, *, expected_status: GrantStatus) -> None:
        self._write("save_grant")
        held = self.grant_rows.get(grant.id)
        if held is None or held.status is not expected_status:
            raise Conflict("the registry row is not as expected, so nothing was written")
        self.grant_rows[grant.id] = grant

    async def create_listing(self, listing: Listing) -> None:
        self._write("create_listing")
        if listing.id in self.listing_rows or any(
            x.network_id == listing.network_id
            and x.source_tenant_id == listing.source_tenant_id
            and x.source_service_id == listing.source_service_id
            and x.status in _LIVE_LISTING
            for x in self.listing_rows.values()
        ):
            raise Conflict("the registry row is not as expected, so nothing was written")
        self.listing_rows[listing.id] = listing

    async def save_listing(self, listing: Listing, *, expected_status: ListingStatus) -> None:
        self._write("save_listing")
        held = self.listing_rows.get(listing.id)
        if held is None or held.status is not expected_status:
            raise Conflict("the registry row is not as expected, so nothing was written")
        self.listing_rows[listing.id] = listing

    # ---- seeding (no log)

    def seed(
        self,
        network: Network,
        *,
        members: Sequence[NetworkMembership] = (),
        grants: Sequence[Grant] = (),
        listings: Sequence[Listing] = (),
        settings: NetworkSettings = SETTINGS,
    ) -> Self:
        self.networks[network.id] = (network, settings)
        for member in members:
            self.members[member.id] = member
        for grant in grants:
            self.grant_rows[grant.id] = grant
        for listing in listings:
            self.listing_rows[listing.id] = listing
        return self


# ---------------------------------------------------------------- units of work


@dataclass(slots=True)
class UnitWorld:
    """What the units of both kinds recorded: one log, so the order across scopes is visible."""

    log: list[str]
    audits: list[tuple[str, AuditEntry]] = field(default_factory=list)  # (scope, entry)
    outbox: list[tuple[str, Any]] = field(default_factory=list)  # (scope, OutboxMessage)
    marked: set[tuple[str, str]] = field(default_factory=set)  # (scope, key) processed
    scheduled: list[Any] = field(default_factory=list)
    sources: list[SourceState] = field(default_factory=list)
    live_rows: dict[tuple[str, GrantScope], int] = field(default_factory=dict)
    ended_calls: list[tuple[str, str, GrantScope, ProjectionEndReason, datetime]] = field(
        default_factory=list
    )
    services: dict[str, Any] = field(default_factory=dict)
    commits: int = 0
    opened: int = 0
    open_now: int = 0
    max_open: int = 0
    fail_commit: str | None = None  # "tenant" or "network": that unit's commit raises


class _Audit:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def append(self, entry: AuditEntry) -> None:
        self._unit.world.log.append(f"{self._unit.kind}:audit:{entry.use_case}")
        self._unit.world.audits.append((str(self._unit.unit_scope), entry))


class _Outbox:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def add(self, message: Any) -> None:
        self._unit.world.log.append(f"{self._unit.kind}:outbox:{message.event_type}")
        self._unit.world.outbox.append((str(self._unit.unit_scope), message))


class _Processed:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def mark_if_new(self, key: str, consumer: str) -> bool:
        scope = str(self._unit.unit_scope)
        if (scope, f"{consumer}:{key}") in self._unit.world.marked:
            return False
        self._unit.pending_marks.add((scope, f"{consumer}:{key}"))
        return True


class _Scheduled:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def add(self, work: Any) -> None:
        self._unit.world.log.append(f"{self._unit.kind}:schedule:{work.kind.value}")
        if any(w.id == work.id for w in self._unit.world.scheduled):
            raise Conflict("this work already exists")
        self._unit.pending_work.append(work)

    async def for_about(self, about_id: str, kind: Any = None) -> list[Any]:
        return [
            w
            for w in self._unit.world.scheduled
            if w.about_id == about_id and (kind is None or w.kind is kind)
        ]


class _Services:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def get(self, service_id: str) -> Any:
        found = self._unit.world.services.get((str(self._unit.unit_scope), service_id))
        if found is None:
            from diucs.domain.errors import NotFound

            raise NotFound("service not found")
        return found


class _Projections:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def end_source(
        self,
        source: str,
        kind: GrantScope,
        *,
        at: datetime,
        reason: ProjectionEndReason,
    ) -> bool:
        world = self._unit.world
        world.log.append(f"network:end_source:{kind.value}")
        network = str(self._unit.unit_scope)
        world.ended_calls.append((network, source, kind, reason, at))
        active = [
            s
            for s in world.sources
            if s.source_tenant_id == source and s.kind is kind and s.status.value == "active"
        ]
        for state in active:
            world.sources.remove(state)
            from dataclasses import replace

            from diucs.application.ports.outbound.projection import SourceStatus

            world.sources.append(
                replace(state, status=SourceStatus.ENDED, ended_at=at, end_reason=reason)
            )
        return bool(active)

    async def mark_ended(
        self,
        source: str,
        kind: GrantScope,
        *,
        at: datetime,
        reason: ProjectionEndReason,
    ) -> int:
        self._unit.world.log.append(f"network:mark_ended:{kind.value}")
        return self._unit.world.live_rows.pop((source, kind), 0)


class _View:
    def __init__(self, unit: _Unit) -> None:
        self._unit = unit

    async def sources(self) -> Sequence[SourceState]:
        return list(self._unit.world.sources)

    async def source(self, source: str, kind: GrantScope) -> SourceState | None:
        return next(
            (
                s
                for s in self._unit.world.sources
                if s.source_tenant_id == source and s.kind is kind
            ),
            None,
        )


class _Unit:
    def __init__(self, world: UnitWorld, kind: str, read_only: bool) -> None:
        self.world = world
        self.kind = kind
        self.read_only = read_only
        self.unit_scope: ScopeId | None = current_scope_or_none()
        self.audit = _Audit(self)
        self.outbox = _Outbox(self)
        self.processed = _Processed(self)
        self.scheduled_work = _Scheduled(self)
        self.services = _Services(self)
        self.projections = _Projections(self)
        self.network_view = _View(self)
        self.pending_marks: set[tuple[str, str]] = set()
        self.pending_work: list[Any] = []
        self.scope = SimpleNamespace(ensure_list=self._ensure_list)
        self.committed = False

    async def _ensure_list(self) -> None:
        self.world.log.append(f"{self.kind}:scope-list")

    async def __aenter__(self) -> Self:
        scope = self.unit_scope
        expected = ScopeKind.NETWORK if self.kind == "network" else ScopeKind.TENANT
        assert scope is not None and scope.kind is expected, "the unit opened under the wrong scope"
        self.world.opened += 1
        self.world.open_now += 1
        self.world.max_open = max(self.world.max_open, self.world.open_now)
        self.world.log.append(f"{self.kind}:open")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.world.open_now -= 1
        self.world.log.append(f"{self.kind}:close")

    async def commit(self) -> None:
        if self.world.fail_commit == self.kind:
            raise ConnectionError("the commit failed")
        self.committed = True
        self.world.commits += 1
        self.world.log.append(f"{self.kind}:commit")
        self.world.marked |= self.pending_marks
        self.world.scheduled.extend(self.pending_work)

    async def rollback(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work was touched: {name}")


class UnitFactories:
    def __init__(self, world: UnitWorld) -> None:
        self.world = world

    def tenant(self) -> _Unit:
        return _Unit(self.world, "tenant", read_only=False)

    def network(self) -> _Unit:
        return _Unit(self.world, "network", read_only=False)

    def network_read_only(self) -> _Unit:
        return _Unit(self.world, "network", read_only=True)

    def tenant_read_only(self) -> _Unit:
        return _Unit(self.world, "tenant", read_only=True)


class MemoryDirectory:
    """The tenant directory: `get` and the active ids."""

    def __init__(self, *tenants: Tenant) -> None:
        self.tenants = {t.id: t for t in tenants}

    async def get(self, tenant_id: str) -> Tenant | None:
        return self.tenants.get(tenant_id)

    async def active_tenant_ids(self) -> Sequence[str]:
        return [t.id for t in self.tenants.values() if t.status.value == "active"]


class Heads:
    """The scope provisioner: the audit chain head of the bound scope."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.scopes: list[ScopeId | None] = []

    async def ensure_audit_head(self) -> None:
        scope = current_scope_or_none()
        self.scopes.append(scope)
        self.log.append(f"audit-head:{scope}")


class Ids:
    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._n = 0

    def new_id(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n:03d}"
