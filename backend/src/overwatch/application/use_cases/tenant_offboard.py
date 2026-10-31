"""Offboarding a tenant: start, export, complete (TEN-074, DEC-136 item 10, audit F section 2.4,
DEC-960 to DEC-966).

A tenant that leaves is first **offboarding** (the notice period, 30 days), then **offboarded**,
and only then may it be purged (`tenant_purge.py`). The platform operator runs all three, for the
one tenant its call is bound to, as it runs the rest of the lifecycle (`tenant_admin.py`: the
operator is named, has no data access of its own, and writes the tenant's own audit chain so the
tenant sees what was done); free text is never a reason.

- **OffboardTenant.** The tenant ends every network membership (`LeaveAllNetworks`: the registry,
  the network scope, the records; its sharing stops at once and its history stays), then the
  registry record moves to `offboarding` through TEN-075's `StartTenantOffboarding` (compare and
  set, the edge told, the audit entry, the typed tenant id). The memberships come first on purpose:
  while the tenant is still active its outbox is relayed, so the `MemberRemoved` events reach the
  network, and a start that stopped half way is run again (what ended is not met twice). A tenant
  that owns a network is refused: the owner cannot leave its own network (transfer or close it
  first). From the moment the record moves, the edge refuses the tenant's people and the workers
  skip it (a tenant that is not active has no sign-in, no prompts and no relay); the tenant's
  administrator therefore does not read anything while offboarding: the export is the operator's,
  and is handed over, which is the stricter reading of "read-only" (DEC-960 item 2).
- **ExportTenant.** The package: one file for each label set of the tenant's scope, grouped by data
  class, one file of the relationships between its own nodes, and a manifest with the row count and
  SHA-256 of each file (the storage's own hash, not the writer's claim), what was held back or left
  out and the head of the audit chain. The package goes to the export storage port. A kind of data
  that has no class is refused (`UnclassifiedData`): nothing is quietly left out. The protected
  stores (staff phone numbers, the text of safety concerns) are included only when the operator says
  the tenant asked. Exporting is repeatable and each run is its own package.
- **CompleteOffboarding.** Needs the export delivered (the manifest hash of a package this tenant
  has in the storage) or the tenant's written waiver of it, and the notice period over or the
  tenant's written waiver of that (`complete_offboarding`). The record moves to `offboarded` first
  (by compare and set); then each active number is quarantined for 90 days
  (`number_quarantine_until`: it is not given to another tenant before) and the tenant's chain is
  written. A completion that stopped after the record is run again: the numbers that are already
  quarantined are left. Closing the Twilio subaccount is a human step the audit names.

The audit snapshots hold ids, counts, hashes and codes, never a value of the tenant's data.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tenant_export import (
    ExportedNode,
    ExportStorage,
    TenantDataReader,
)
from diucs.application.ports.outbound.tenant_registry import TenantRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.membership import LeaveAllNetworks
from diucs.application.use_cases.tenant_admin import (
    AUDIT_UPDATE,
    MOVED,
    NO_TENANT,
    OperatorUseCase,
    _audit,
    _unit_scope,
)
from diucs.application.use_cases.tenant_offboarding import (
    CONFIRM_MESSAGE,
    StartOffboardingCommand,
    StartOffboardingResult,
    StartTenantOffboarding,
)
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.tenant import NumberStatus, TenantStatus
from diucs.domain.rules.tenant_export import (
    MANIFEST_FILE,
    RELATIONSHIPS_FILE,
    ExportClass,
    FileEntry,
    Handling,
    classify,
    file_name,
    jsonl,
    manifest_bytes,
    sha256_hex,
)
from diucs.domain.rules.tenant_lifecycle import (
    complete_offboarding,
    number_quarantine_until,
    offboarding_may_complete_at,
    start_offboarding,
)

PAGE_SIZE: Final = 1000
"""[ASSUMED] rows read from the graph at a time for the export."""
OWNS_NETWORK: Final = "the tenant owns a network: transfer or close it first"
EXPORT_NOT_DELIVERED: Final = "the export has not been delivered or waived"
NOT_OFFBOARDING: Final = "the tenant is not being offboarded"
NOT_EXPORTABLE: Final = "only a tenant that is being offboarded is exported"
MANIFEST_MISMATCH: Final = "the export storage holds other bytes than were sent"

TenantChanged = Callable[[str], None]


# ---------------------------------------------------------------- start


@dataclass(frozen=True, slots=True)
class OffboardTenantResult(StartOffboardingResult):
    memberships_ended: int
    resumed: bool
    """True when the record was already offboarding and only what was left was finished."""


class OffboardTenant(OperatorUseCase):
    """Ends the tenant's network memberships and then starts its notice period, which is
    `StartTenantOffboarding` (TEN-075: the record move by compare and set, the edge told, the
    audit entry). This adds only what that left for TEN-074: the memberships come first. It takes
    TEN-075's command and answers with the same fields and two more, so the operator's route and
    the script both run it (`bootstrap/lifecycle_operations.py: build_offboard`)."""

    def __init__(
        self,
        tenants: TenantDirectory,
        leave: LeaveAllNetworks,
        start: StartTenantOffboarding,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._leave = leave
        self._start = start

    async def execute(self, command: StartOffboardingCommand) -> OffboardTenantResult:
        _, scope = self._begin(command.actor)
        if type(command.confirm_tenant_id) is not str or command.confirm_tenant_id != scope.value:
            raise ValidationFailed("confirm_tenant_id", CONFIRM_MESSAGE)
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        resumed = tenant.status is TenantStatus.OFFBOARDING
        if not resumed:
            # Only an active or suspended tenant starts (InvalidTransition otherwise, nothing
            # written): the move is checked before anything else changes.
            start_offboarding(tenant, self._clock.now())
            if await self._leave.owned_networks(scope.value):
                raise NotAllowed(OWNS_NETWORK)
        # The memberships end first: while the tenant is still active its outbox is relayed, so the
        # `MemberRemoved` events reach the network. A start that stopped half way is run again.
        ended = await self._leave.execute(command.actor, scope.value)
        if ended or resumed:
            async with self._uow_factory() as uow:
                _unit_scope(uow)
                await _audit(
                    uow,
                    self._clock,
                    command.actor,
                    "EndNetworkMemberships",
                    AUDIT_UPDATE,
                    f"tenant-{scope.value}",
                    {"memberships_ended": ended, "resumed": resumed},
                )
                await uow.commit()
        if resumed:
            return OffboardTenantResult(
                scope.value,
                tenant.offboarding_started_at or self._clock.now(),
                offboarding_may_complete_at(tenant),
                ended,
                True,
            )
        started = await self._start.execute(command)
        return OffboardTenantResult(
            scope.value, started.started_at, started.notice_ends_at, ended, False
        )


# ---------------------------------------------------------------- export


@dataclass(frozen=True, slots=True)
class ExportTenantCommand:
    actor: Actor
    include_protected: bool = False
    """True only when the tenant has asked for its protected contacts and safety-concern text."""


@dataclass(frozen=True, slots=True)
class ExportResult:
    package_id: str
    manifest_hash: str
    files: tuple[FileEntry, ...]
    held_back: dict[str, int]
    excluded: dict[str, int]


class ExportTenant(OperatorUseCase):
    def __init__(
        self,
        tenants: TenantDirectory,
        reader: TenantDataReader,
        storage: ExportStorage,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._reader = reader
        self._storage = storage
        self._ids = ids

    async def execute(self, command: ExportTenantCommand) -> ExportResult:
        _, scope = self._begin(command.actor)
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        if tenant.status not in (TenantStatus.OFFBOARDING, TenantStatus.OFFBOARDED):
            raise NotAllowed(NOT_EXPORTABLE)
        package = f"export-{self._ids.new_id()}"
        plan, held_back, excluded = await self._plan(command.include_protected)
        files: list[FileEntry] = []
        for labels, export_class in plan:
            files.append(await self._write_nodes(tenant.id, package, labels, export_class))
        files.append(await self._write_relationships(tenant.id, package))
        head = await self._reader.audit_head()
        manifest = manifest_bytes(
            tenant_id=tenant.id,
            package_id=package,
            generated_at=self._clock.now(),
            files=files,
            held_back=held_back,
            excluded=excluded,
            audit_last_hash=None if head is None else head.last_hash,
            audit_last_seq=None if head is None else head.last_seq,
            protected_included=command.include_protected,
        )
        stored = await self._storage.put(tenant.id, package, MANIFEST_FILE, manifest)
        if stored != sha256_hex(manifest):
            raise ConnectionError(MANIFEST_MISMATCH)
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await _audit(
                uow,
                self._clock,
                command.actor,
                "ExportTenant",
                AUDIT_UPDATE,
                f"tenant-{scope.value}",
                {
                    "package": package,
                    "manifest_hash": stored,
                    "files": len(files),
                    "protected_included": command.include_protected,
                },
            )
            await uow.commit()
        return ExportResult(package, stored, tuple(files), held_back, excluded)

    async def _plan(
        self, include_protected: bool
    ) -> tuple[list[tuple[tuple[str, ...], str]], dict[str, int], dict[str, int]]:
        """Which label sets go into the package, which are held back and which are never exported.
        An unclassified label set refuses the whole export (`UnclassifiedData`)."""
        plan: list[tuple[tuple[str, ...], str]] = []
        held_back: dict[str, int] = {}
        excluded: dict[str, int] = {}
        for item in await self._reader.node_counts():
            classified = classify(item.labels)
            key = "+".join(item.labels)
            if classified.handling is Handling.EXCLUDED:
                excluded[key] = item.count
            elif classified.handling is Handling.PROTECTED and not include_protected:
                held_back[key] = item.count
            else:
                assert classified.export_class is not None
                plan.append((item.labels, classified.export_class.value))
        return plan, held_back, excluded

    async def _write_nodes(
        self, tenant_id: str, package: str, labels: tuple[str, ...], export_class: str
    ) -> FileEntry:
        rows: list[dict[str, object]] = []
        after: str | None = None
        while True:
            page = await self._reader.nodes(labels, after=after, limit=PAGE_SIZE)
            rows.extend(_node_row(node, labels) for node in page)
            if len(page) < PAGE_SIZE:
                break
            after = page[-1].ref
        content = jsonl(rows)
        name = file_name(ExportClass(export_class), labels)
        digest = await self._storage.put(tenant_id, package, name, content)
        if digest != sha256_hex(content):
            raise ConnectionError(MANIFEST_MISMATCH)
        return FileEntry(name, export_class, len(rows), digest)

    async def _write_relationships(self, tenant_id: str, package: str) -> FileEntry:
        rows: list[dict[str, object]] = []
        after: str | None = None
        while True:
            page = await self._reader.relationships(after=after, limit=PAGE_SIZE)
            rows.extend(
                {
                    "ref": rel.ref,
                    "type": rel.type,
                    "start": rel.start,
                    "end": rel.end,
                    "properties": dict(rel.properties),
                }
                for rel in page
            )
            if len(page) < PAGE_SIZE:
                break
            after = page[-1].ref
        content = jsonl(rows)
        digest = await self._storage.put(tenant_id, package, RELATIONSHIPS_FILE, content)
        if digest != sha256_hex(content):
            raise ConnectionError(MANIFEST_MISMATCH)
        return FileEntry(RELATIONSHIPS_FILE, "relationships", len(rows), digest)


def _node_row(node: ExportedNode, labels: tuple[str, ...]) -> dict[str, object]:
    return {"ref": node.ref, "labels": sorted(labels), "properties": dict(node.properties)}


# ---------------------------------------------------------------- complete


@dataclass(frozen=True, slots=True)
class CompleteOffboardingCommand:
    actor: Actor
    manifest_hash: str | None = None
    """The manifest hash of the package the tenant received, as `ExportTenant` returned it."""
    export_waived: bool = False
    """The tenant waived the export in writing."""
    notice_waived: bool = False
    """The tenant waived the rest of the notice period in writing."""


@dataclass(frozen=True, slots=True)
class CompleteOffboardingResult:
    tenant_id: str
    numbers_quarantined: int
    resumed: bool


class CompleteOffboarding(OperatorUseCase):
    def __init__(
        self,
        tenants: TenantDirectory,
        registry: TenantRegistry,
        storage: ExportStorage,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        on_changed: tuple[TenantChanged, ...] = (),
    ) -> None:
        super().__init__(tenants, uow_factory, clock)
        self._registry = registry
        self._storage = storage
        self._on_changed = on_changed

    async def execute(self, command: CompleteOffboardingCommand) -> CompleteOffboardingResult:
        _, scope = self._begin(command.actor)
        tenant = await self._tenants.get(scope.value)
        if tenant is None:
            raise NotFound(NO_TENANT)
        now = self._clock.now()
        resumed = tenant.status is TenantStatus.OFFBOARDED
        if not resumed:
            if tenant.status is not TenantStatus.OFFBOARDING:
                raise NotAllowed(NOT_OFFBOARDING)
            delivered = command.manifest_hash is not None and await self._storage.has_package(
                tenant.id, command.manifest_hash
            )
            if not delivered and command.export_waived is not True:
                raise NotAllowed(EXPORT_NOT_DELIVERED)
            # The notice period: refused before the notice has ended unless waived in writing.
            offboarded = complete_offboarding(tenant, now, waived=command.notice_waived)
            if not await self._registry.save(
                offboarded, expected_epoch=tenant.epoch, expected_status=TenantStatus.OFFBOARDING
            ):
                raise Conflict(MOVED)
            for changed in self._on_changed:
                changed(scope.value)
        quarantined = 0
        until = number_quarantine_until(now if not resumed else (tenant.offboarded_at or now))
        for number in await self._registry.numbers(scope.value):
            if number.status is NumberStatus.ACTIVE:
                await self._registry.put_number(
                    scope.value,
                    dataclasses.replace(
                        number, status=NumberStatus.QUARANTINED, quarantine_until=until
                    ),
                )
                quarantined += 1
        async with self._uow_factory() as uow:
            _unit_scope(uow)
            await _audit(
                uow,
                self._clock,
                command.actor,
                "CompleteOffboarding",
                AUDIT_UPDATE,
                f"tenant-{scope.value}",
                {
                    "numbers_quarantined": quarantined,
                    "export_waived": command.export_waived is True,
                    "notice_waived": command.notice_waived is True,
                    "resumed": resumed,
                },
            )
            await uow.commit()
        return CompleteOffboardingResult(scope.value, quarantined, resumed)
