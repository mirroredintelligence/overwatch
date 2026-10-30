"""Stand-ins for the unit tests of the support-access ticket flow (TEN-075, TEN-084).

There is no in-memory store of records (DEC-004): `MemoryTickets` holds only the tickets one test
creates, with the compare and set the real store gives (a move writes only when the stored ticket
names the tenant and is still in the state the caller read), so a test shows the order of the steps
and what each side may see. What is stored on a real graph is proved by the integration tests.

The guard is the real `CrossTenantGuard` over a unit of work that records each tenant's chain, the
in-memory cache (which qualifies every name by the bound tenant like Redis does), the recording
platform audit and a tenant directory of the tenants a test names.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.recording_platform_audit import RecordingPlatformAudit
from diucs.application.actor import Actor
from diucs.application.cross_tenant_guard import CrossTenantGuard, PlatformPrincipal
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.identity import TenantKeyedSecrets
from diucs.application.tenancy import ScopeId, bind_tenant, current_scope_or_none
from diucs.application.use_cases.cross_tenant_tickets import (
    ApproveSupportTicket,
    CancelSupportTicket,
    DecideTicketCommand,
    EndTicketAccess,
    ListSupportTickets,
    OpenTicketAccess,
    ReadSupportTicket,
    RefuseSupportTicket,
    RequestSupportTicket,
    RevokeSupportTicket,
    UseTicketAccess,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.support import SUPPORT_CODE_SECRET
from diucs.domain.rules.support_ticket import SupportTicket, TicketState
from tests.support.tenant_samples import make_tenant

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
KEY = b"synthetic-platform-key-for-the-ticket-unit-tests-01"
REF = "ref-support-person-0123456789"
OTHER_REF = "ref-another-support-9876543210"
PRINCIPAL = PlatformPrincipal(account_ref=REF, role=Role.SUPPORT)
OTHER_PRINCIPAL = PlatformPrincipal(account_ref=OTHER_REF, role=Role.SUPPORT)
REASON = "A reporter cannot sign in on the tenant host."


class MemoryTickets:
    def __init__(self) -> None:
        self.rows: dict[str, SupportTicket] = {}
        self.fail_next_move = False
        self.moves: list[tuple[str, TicketState]] = []

    async def add(self, ticket: SupportTicket) -> None:
        if ticket.id in self.rows:
            raise Conflict("a ticket with this id already exists")
        self.rows[ticket.id] = ticket

    async def for_tenant(self, tenant_id: str, ticket_id: str) -> SupportTicket | None:
        found = self.rows.get(ticket_id)
        return found if found is not None and found.tenant_id == tenant_id else None

    async def for_principal(self, principal_ref: str, ticket_id: str) -> SupportTicket | None:
        found = self.rows.get(ticket_id)
        return found if found is not None and found.requested_by_ref == principal_ref else None

    async def of_tenant(self, tenant_id: str, limit: int) -> list[SupportTicket]:
        found = [t for t in self.rows.values() if t.tenant_id == tenant_id]
        return sorted(found, key=lambda t: t.requested_at, reverse=True)[:limit]

    async def of_principal(self, principal_ref: str, limit: int) -> list[SupportTicket]:
        found = [t for t in self.rows.values() if t.requested_by_ref == principal_ref]
        return sorted(found, key=lambda t: t.requested_at, reverse=True)[:limit]

    async def move(self, ticket: SupportTicket, expected: TicketState) -> bool:
        if self.fail_next_move:
            self.fail_next_move = False
            return False
        stored = self.rows.get(ticket.id)
        if stored is None or stored.tenant_id != ticket.tenant_id or stored.state is not expected:
            return False
        self.rows[ticket.id] = ticket
        self.moves.append((ticket.id, ticket.state))
        return True


class _Audit:
    def __init__(self, world: World) -> None:
        self._world = world

    async def append(self, entry: AuditEntry) -> None:
        if self._world.fail_tenant_audit_on and entry.action in self._world.fail_tenant_audit_on:
            raise ConnectionError("audit store down")
        self._world.pending.append(entry)


class _Uow:
    def __init__(self, world: World) -> None:
        self.audit = _Audit(world)
        self._world = world
        self._scope = current_scope_or_none()

    @property
    def unit_scope(self) -> ScopeId | None:
        return self._scope

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._world.pending.clear()

    async def commit(self) -> None:
        assert self._scope is not None
        self._world.chains.setdefault(self._scope.value, []).extend(self._world.pending)
        self._world.pending.clear()


class _Directory:
    def __init__(self, tenants: dict[str, Tenant]) -> None:
        self.tenants = tenants

    async def get(self, tenant_id: str) -> Tenant | None:
        return self.tenants.get(tenant_id)


@dataclass
class World:
    chains: dict[str, list[AuditEntry]] = field(default_factory=dict)
    pending: list[AuditEntry] = field(default_factory=list)
    fail_tenant_audit_on: frozenset[str] = frozenset()

    def factory(self) -> _Uow:
        return _Uow(self)

    def chain(self, tenant: str) -> list[AuditEntry]:
        return self.chains.get(tenant, [])

    def actions(self, tenant: str) -> list[str]:
        return [entry.action for entry in self.chain(tenant)]


def admin(
    tenant: str = "tenant-a", ref: str = "admin-ref-0001", role: Role = Role.TENANT_ADMIN
) -> Actor:
    return Actor(
        role=role,
        practitioner_id=ref,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


@dataclass
class Rig:
    clock: FixedClock
    world: World
    cache: InMemoryCache
    platform: RecordingPlatformAudit
    directory: _Directory
    tickets: MemoryTickets
    guard: CrossTenantGuard
    ids: SequentialIds

    @property
    def request(self) -> RequestSupportTicket:
        return RequestSupportTicket(
            self.tickets,
            self.guard,
            self.directory,
            self.clock,
            self.ids,  # type: ignore[arg-type]
        )

    @property
    def listing(self) -> ListSupportTickets:
        return ListSupportTickets(self.tickets, self.guard, self.clock)

    @property
    def reading(self) -> ReadSupportTicket:
        return ReadSupportTicket(self.tickets, self.guard, self.clock)

    @property
    def cancelling(self) -> CancelSupportTicket:
        return CancelSupportTicket(self.tickets, self.guard, self.clock)

    @property
    def opening(self) -> OpenTicketAccess:
        return OpenTicketAccess(self.tickets, self.guard, self.clock)

    @property
    def using(self) -> UseTicketAccess:
        return UseTicketAccess(self.tickets, self.guard, self.clock)

    @property
    def ending(self) -> EndTicketAccess:
        return EndTicketAccess(self.tickets, self.guard, self.clock)

    @property
    def approving(self) -> ApproveSupportTicket:
        return ApproveSupportTicket(self.tickets, self.guard, self.clock)

    @property
    def refusing(self) -> RefuseSupportTicket:
        return RefuseSupportTicket(self.tickets, self.guard, self.clock)

    @property
    def revoking(self) -> RevokeSupportTicket:
        return RevokeSupportTicket(self.tickets, self.guard, self.clock)

    async def approve(self, ticket_id: str, tenant: str = "tenant-a") -> Any:
        with bind_tenant(tenant):
            return await self.approving.execute(
                DecideTicketCommand(actor=admin(tenant), ticket_id=ticket_id)
            )

    def cache_names(self, tenant: str) -> frozenset[str]:
        with bind_tenant(tenant):
            return self.cache.keys()


def rig(tenants: dict[str, Tenant] | None = None) -> Rig:
    clock = FixedClock(NOW)
    world = World()
    cache = InMemoryCache(clock)
    platform = RecordingPlatformAudit()
    directory = _Directory(
        tenants or {"tenant-a": make_tenant(id="tenant-a"), "tenant-b": make_tenant(id="tenant-b")}
    )
    guard = CrossTenantGuard(
        world.factory,  # type: ignore[arg-type]
        cache,
        clock,
        SequentialIds("access"),
        TenantKeyedSecrets(FixedSecretStore({SUPPORT_CODE_SECRET: KEY})),
        directory,  # type: ignore[arg-type]
        platform,
    )
    return Rig(
        clock, world, cache, platform, directory, MemoryTickets(), guard, SequentialIds("st")
    )
