"""Purging a tenant (TEN-074, DEC-136 item 10, audit F section 2.4, hazards H-T18 and H-T29).

The last step of a tenant's life: every node of its scope is deleted, its cache names are removed
and its record becomes `purged`. It is the one irreversible act of the platform, so it is guarded
as such:

- **two different named operators** (the first runs it, the second confirms: the same person twice
  is no second operator) and **the tenant's id typed exactly** (`purge_blockers`);
- the tenant is **offboarded** and its **retention hold** has passed (`purge_blockers`);
- a **dry run** answers what would be deleted, by label set, and changes nothing: it is what the
  operators review before they confirm.

**Scoped by construction.** The deletion is `tenantId = <the bound tenant>` and nothing else
(`graph_store/tenant_purge.py`), in batches of its own transactions, so another tenant's data, the
network scope and the registry (the tenant's own record, its numbers, the networks and their
memberships, which carry no `tenantId`) are out of its reach: a purge of tenant A leaves tenant B
exactly as it was (the integration test shows it).

**Audit kept per the retention decision** (DEC-271 item 6: the audit chain is kept until the tenant
is purged). The chain goes last, so a purge that stops half way still has the record of what the
tenant did; and before anything is deleted the platform's chain records the tombstone: who
purged (both operators' opaque references), the head of the tenant's audit chain (its last hash
and sequence number: proof that the chain existed and what it ended on, without keeping it) and the
count of nodes by label set. If that record cannot be written, nothing is deleted. When the
deletion is done a second platform entry records what was deleted and what was left (nothing). The
platform chain's graph adapter does not exist yet (DEC-529), so today both entries go to the port's
recording fake: a known gap, recorded in the fragment.

**Order, and a purge that stopped.** The tombstone entry, the registry record (`purged`, by compare
and set: from then on nothing can reopen the tenant), the data in batches until none is left, the
cache names, the audit chain in batches, a check that nothing is left, the completion entry. Each
step is repeatable: run the same purge again on a `purged` tenant and it deletes what remains.
[ASSUMED] batches of 1000 nodes. Backups expire by their own schedule (information governance's to
accept, H-T29): nothing here reaches them.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.platform_audit import PlatformAudit, PlatformAuditEntry
from diucs.application.ports.outbound.tenant_export import (
    ScopeCachePurger,
    TenantDataReader,
    TenantPurger,
)
from diucs.application.ports.outbound.tenant_registry import TenantRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.application.use_cases.tenant_admin import MOVED, NO_TENANT, check_operator
from diucs.domain.errors import Conflict, NotAllowed, NotFound
from diucs.domain.model.tenant import TenantStatus
from diucs.domain.rules.tenant_lifecycle import purge_blockers, purge_tenant

BATCH_SIZE: Final = 1000
MAX_BATCHES: Final = 100_000
NOT_PURGEABLE: Final = "Purge is unavailable until: "
INCOMPLETE: Final = "the purge did not remove every node of the tenant"

TenantChanged = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class PurgeTenantCommand:
    actor: Actor
    second_actor: Actor
    typed_slug: str
    dry_run: bool = False
    export_manifest_hash: str | None = None
    """The manifest hash of the package the tenant received, written into the tombstone."""


@dataclass(frozen=True, slots=True)
class PurgeResult:
    dry_run: bool
    counts: dict[str, int]
    """Nodes by label set (`A+B`) found before anything was deleted."""
    nodes_deleted: int
    cache_names_removed: int
    resumed: bool
    """True when the record was already purged and this run deleted what was left."""


def _key(labels: tuple[str, ...]) -> str:
    return "+".join(labels)


class PurgeTenant:
    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        reader: TenantDataReader,
        purger: TenantPurger,
        cache: ScopeCachePurger,
        platform_audit: PlatformAudit,
        clock: Clock,
        on_changed: tuple[TenantChanged, ...] = (),
    ) -> None:
        self._tenants = tenants
        self._registry = registry
        self._reader = reader
        self._purger = purger
        self._cache = cache
        self._platform_audit = platform_audit
        self._clock = clock
        self._on_changed = on_changed

    async def execute(self, command: PurgeTenantCommand) -> PurgeResult:
        first = check_operator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        scope = current_scope()
        if scope.kind is not ScopeKind.TENANT:
            raise TenantNotBound
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        if command.dry_run:
            if tenant.status not in (TenantStatus.OFFBOARDED, TenantStatus.PURGED):
                raise NotAllowed(NOT_PURGEABLE + "Tenant is offboarded")
            counts = await self._counts()
            return PurgeResult(True, counts, 0, 0, resumed=False)
        second = check_operator(command.second_actor)
        require_actor_in_bound_tenant(command.second_actor)
        now = self._clock.now()
        resumed = tenant.status is TenantStatus.PURGED
        if not resumed:
            blockers = purge_blockers(tenant, now, [first, second], command.typed_slug)
            if blockers:
                raise NotAllowed(NOT_PURGEABLE + "; ".join(blockers))
        elif command.typed_slug != tenant.id or first == second:
            raise NotAllowed(NOT_PURGEABLE + "the tenant id and two operators are needed")
        counts = await self._counts()
        head = await self._reader.audit_head()
        # 1. the tombstone: if the platform cannot record it, nothing is deleted
        await self._platform_audit.append(
            PlatformAuditEntry(
                action="PurgeTenant",
                principal_ref=first,
                tenant_id=scope.value,
                access_id=None,
                snapshot={
                    "second_principal_ref": second,
                    "counts": dict(counts),
                    "final_audit_hash": None if head is None else head.last_hash,
                    "final_audit_seq": None if head is None else head.last_seq,
                    "export_manifest_hash": command.export_manifest_hash,
                    "resumed": resumed,
                },
                at=now,
            )
        )
        # 2. the record: from here nothing reopens the tenant
        if not resumed:
            purged = purge_tenant(tenant, now)
            if not await self._registry.save(
                purged, expected_epoch=tenant.epoch, expected_status=TenantStatus.OFFBOARDED
            ):
                raise Conflict(MOVED)
            for changed in self._on_changed:
                changed(scope.value)
        # 3. the data, then the cache, then the audit chain last
        deleted = await self._delete_all(self._purger.delete_data_batch)
        removed = await self._cache.purge_scope(ScopeId.tenant(scope.value))
        deleted += await self._delete_all(self._purger.delete_audit_batch)
        # 4. nothing may be left
        if await self._reader.node_counts():
            raise ConnectionError(INCOMPLETE)
        await self._platform_audit.append(
            PlatformAuditEntry(
                action="PurgeTenantCompleted",
                principal_ref=first,
                tenant_id=scope.value,
                access_id=None,
                snapshot={"nodes_deleted": deleted, "cache_names_removed": removed},
                at=self._clock.now(),
            )
        )
        return PurgeResult(False, counts, deleted, removed, resumed)

    async def _counts(self) -> dict[str, int]:
        return {_key(item.labels): item.count for item in await self._reader.node_counts()}

    @staticmethod
    async def _delete_all(batch: Callable[[int], Awaitable[int]]) -> int:
        total = 0
        for _ in range(MAX_BATCHES):
            done = await batch(BATCH_SIZE)
            if not done:
                return total
            total += done
        raise ConnectionError(INCOMPLETE)
