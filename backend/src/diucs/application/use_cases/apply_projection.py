"""The network projection apply step (TEN-054, DEC-543, DEC-132 items 3, 4 and 6).

The second of the two units of work. A `ProjectionRequested` message arrives with the source
tenant as its verified bus property (the worker checked it against the directory and against the
payload) and the network scope bound from the payload's network id (the worker checked that the
network exists and is active). The message is never the authority: this step asks the registry,

1. is the source tenant an active member of the network (`MEMBER_NOT_ACTIVE`);
2. is the grant the message names, at the version it names, effective now for this member, kind
   and network (`GRANT_NOT_EFFECTIVE`);
3. has the network owner admitted this service (`LISTING_NOT_ADMITTED`);

and checks the message itself: the allowlist version is ours (`ALLOWLIST_MISMATCH`) and the body is
exactly the allowlisted body of its kind for the service and version it names (`INVALID_BODY`).
Only then does it open one read-write unit of work in the network scope: it marks the message
processed, makes sure the member's source is open, writes the row, appends one audit entry (ids and
versions, never a value) and commits. A rejected message opens no unit and is not retried.

The source is opened by the first projection under an effective grant. An ended source is reopened
only by a grant that began after it ended (approved, or started, after: TEN-056): a message that was in flight when a member left or a grant
ended carries an older grant and cannot reopen it (a grant that ends between the gate and the write
may let one projection through, DEC-132 item 3, and the end marks that row when it runs).

After the commit the notifier is told (TEN-058 rebuilds the network board); a notifier that fails
changes nothing, because the projection is already committed. Rejections are notified and counted;
they write no audit entry, because a rejection opens no unit of work.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from diucs.application.actor import system_actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.network import ActiveGrant, NetworkRegistry
from diucs.application.ports.outbound.projection import (
    GrantRef,
    ProjectionNotifier,
    SourceStatus,
)
from diucs.application.ports.outbound.unit_of_work import (
    NetworkUnitOfWork,
    NetworkUnitOfWorkFactory,
)
from diucs.application.projection import Projection, from_body
from diucs.application.tenancy import ScopeKind, current_scope_or_none
from diucs.domain.errors import DomainError, ValidationFailed
from diucs.domain.events import (
    ProjectionApplied,
    ProjectionRejected,
    ProjectionRejectReason,
    ProjectionRequested,
)
from diucs.domain.model.network import Grant
from diucs.domain.rules.listing import may_project_listing
from diucs.domain.rules.projection import (
    PROJECTION_ALLOWLIST_VERSION,
    CapacityProjection,
    CriteriaProjection,
    ServiceProjection,
)

logger = logging.getLogger(__name__)

CONSUMER_NAME: Final = "network-projector"
APPLY_CHANNEL: Final = "network-projector"
_AUDIT_ACTION: Final = "C"
_USE_CASE: Final = "ApplyProjection"


class ApplyOutcome(StrEnum):
    APPLIED = "applied"
    STALE = "stale"  # an older version: the stored row is newer, nothing was written
    DUPLICATE = "duplicate"  # this message was processed before
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ApplyResult:
    outcome: ApplyOutcome
    reason: ProjectionRejectReason | None = None


class ProjectionMismatch(DomainError):
    """The message cannot be what it says: the scope bound is not the network it names, or the bus
    tenant is not the source tenant it names. Permanent: the worker dead-letters it."""

    def __init__(self, text: str = "the projection message does not match its scope") -> None:
        super().__init__(text)


class ApplyUnitReadOnly(RuntimeError):
    def __init__(self) -> None:
        super().__init__("the apply step needs a unit of work that can write")


def _version(dto: Projection) -> int:
    return dto.version if isinstance(dto, CriteriaProjection) else dto.source_version


def _in_force_from(grant: Grant) -> datetime:
    """The instant this grant began to allow sharing: its last approval or its start, whichever is
    later. A grant approved before an end but starting after it is a new grant for the source."""
    approvals = [a.at for a in (grant.grantor_approval, grant.owner_approval) if a is not None]
    return max(*approvals, grant.effective_from)


class ApplyProjection:
    def __init__(
        self,
        uow_factory: NetworkUnitOfWorkFactory,
        registry: NetworkRegistry,
        clock: Clock,
        notifier: ProjectionNotifier | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._clock = clock
        self._notifier = notifier

    async def execute(
        self, request: ProjectionRequested, *, message_id: str, source_tenant_id: str
    ) -> ApplyResult:
        scope = current_scope_or_none()
        if (
            scope is None
            or scope.kind is not ScopeKind.NETWORK
            or scope.value != request.network_id
            or source_tenant_id != request.source_tenant_id
        ):
            raise ProjectionMismatch
        now = self._clock.now()
        refusal = await self._gate(request, now)
        if isinstance(refusal, ProjectionRejectReason):
            await self._notify_rejected(request, refusal, now)
            return ApplyResult(ApplyOutcome.REJECTED, refusal)
        dto, active = refusal
        result = await self._write(request, dto, active, message_id, now)
        if result.outcome is ApplyOutcome.REJECTED and result.reason is not None:
            await self._notify_rejected(request, result.reason, now)
        elif result.outcome is ApplyOutcome.APPLIED:
            await self._notify_applied(request, now)
        return result

    # ---- the registry and the message

    async def _gate(
        self, request: ProjectionRequested, now: datetime
    ) -> ProjectionRejectReason | tuple[Projection, ActiveGrant]:
        if request.allowlist_version != PROJECTION_ALLOWLIST_VERSION:
            return ProjectionRejectReason.ALLOWLIST_MISMATCH
        try:
            dto = from_body(request.kind, request.body)
        except ValidationFailed, KeyError, TypeError, ValueError:
            return ProjectionRejectReason.INVALID_BODY
        if dto.source_service_id != request.source_service_id or (
            _version(dto) != request.source_version
        ):
            return ProjectionRejectReason.INVALID_BODY
        source = request.source_tenant_id
        membership = await self._registry.active_membership(request.network_id, source)
        if membership is None:
            return ProjectionRejectReason.MEMBER_NOT_ACTIVE
        active = next(
            (
                a
                for a in await self._registry.active_grants_for(source, request.kind, now)
                if a.grant.id == request.grant_id
                and a.grant.version == request.grant_version
                and a.network.network.id == request.network_id
            ),
            None,
        )
        if active is None:
            return ProjectionRejectReason.GRANT_NOT_EFFECTIVE
        listings = await self._registry.listings_of(request.network_id, source)
        if not any(
            listing.source_service_id == request.source_service_id
            and may_project_listing(listing, active.membership, active.grant, now)
            for listing in listings
        ):
            return ProjectionRejectReason.LISTING_NOT_ADMITTED
        return dto, active

    # ---- the network unit of work

    async def _write(
        self,
        request: ProjectionRequested,
        dto: Projection,
        active: ActiveGrant,
        message_id: str,
        now: datetime,
    ) -> ApplyResult:
        source = request.source_tenant_id
        grant = GrantRef(active.grant.id, active.grant.version)
        async with self._uow_factory() as uow:
            if uow.read_only:
                raise ApplyUnitReadOnly
            scope = current_scope_or_none()
            if uow.unit_scope is None or scope is None or uow.unit_scope != scope:
                raise ProjectionMismatch
            if not await uow.processed.mark_if_new(message_id, CONSUMER_NAME):
                return ApplyResult(ApplyOutcome.DUPLICATE)
            if not await self._source_open(uow, request, active.grant, grant):
                return ApplyResult(
                    ApplyOutcome.REJECTED, ProjectionRejectReason.GRANT_NOT_EFFECTIVE
                )
            written = await self._upsert(uow, source, dto, grant, now)
            if not written:
                await uow.commit()  # the marker only: the stored row is newer
                return ApplyResult(ApplyOutcome.STALE)
            await uow.audit.append(
                AuditEntry(
                    action=_AUDIT_ACTION,
                    use_case=_USE_CASE,
                    actor=system_actor(source, APPLY_CHANNEL),
                    entity_ids=(f"{source}/{request.source_service_id}",),
                    snapshot={
                        "kind": request.kind.value,
                        "source_service_id": request.source_service_id,
                        "source_version": request.source_version,
                        "grant_id": grant.grant_id,
                        "grant_version": grant.grant_version,
                    },
                    at=now,
                )
            )
            await uow.commit()
        return ApplyResult(ApplyOutcome.APPLIED)

    @staticmethod
    async def _source_open(
        uow: NetworkUnitOfWork, request: ProjectionRequested, grant: Grant, ref: GrantRef
    ) -> bool:
        state = await uow.network_view.source(request.source_tenant_id, request.kind)
        if state is not None and state.status is SourceStatus.ACTIVE:
            return True
        if (
            state is not None
            and state.ended_at is not None
            and _in_force_from(grant) <= state.ended_at
        ):
            return False  # a grant that began before the end: it cannot reopen the source
        await uow.projections.open_source(request.source_tenant_id, request.kind, ref)
        return True

    @staticmethod
    async def _upsert(
        uow: NetworkUnitOfWork, source: str, dto: Projection, grant: GrantRef, now: datetime
    ) -> bool:
        if isinstance(dto, ServiceProjection):
            return await uow.projections.upsert_service(source, dto, grant=grant, projected_at=now)
        if isinstance(dto, CapacityProjection):
            return await uow.projections.upsert_capacity(source, dto, grant=grant, projected_at=now)
        return await uow.projections.upsert_criteria(source, dto, grant=grant, projected_at=now)

    # ---- after the commit

    async def _notify_applied(self, request: ProjectionRequested, now: datetime) -> None:
        if self._notifier is None:
            return
        event = ProjectionApplied(
            network_id=request.network_id,
            source_tenant_id=request.source_tenant_id,
            kind=request.kind,
            item_id=request.source_service_id,
            source_version=request.source_version,
            at=now,
        )
        try:
            await self._notifier.applied(event)
        except Exception as error:
            logger.warning("the network notifier failed after a commit: %s", type(error).__name__)

    async def _notify_rejected(
        self, request: ProjectionRequested, reason: ProjectionRejectReason, now: datetime
    ) -> None:
        if self._notifier is None:
            return
        event = ProjectionRejected(
            network_id=request.network_id,
            source_tenant_id=request.source_tenant_id,
            kind=request.kind,
            reason=reason,
            at=now,
        )
        try:
            await self._notifier.rejected(event)
        except Exception as error:
            logger.warning("the network notifier failed on a rejection: %s", type(error).__name__)
