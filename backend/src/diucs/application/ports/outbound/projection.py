"""Outbound port: the projections in a network scope (TEN-053, DEC-542, DEC-132 item 4, DEC-134
items 6 and 7).

Two Protocols, and they are separate on purpose: member-facing use cases import only `NetworkView`
(read), so "members read the network through a read-only use case" is a fact a test can assert, and
only the projection use cases import `ProjectionWriter`. Both run in a unit of work bound to a
network scope; the writer needs a unit that is not read-only.

What is written is a DTO of the allowlist (`domain/rules/projection.py`) and nothing else: a writer
method takes a DTO and the grant it is written under, never a property bag, and the repository
sends exactly the stored properties of the DTO's label. The member the projection came from is an
argument (`source_tenant_id`) that the caller took from a verified grant (TEN-054), and it is stored
on the row; it is never a field of a DTO.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from diucs.domain.events import ProjectionApplied, ProjectionRejected, ProjectionRequested
from diucs.domain.model.network import GrantScope
from diucs.domain.rules.projection import CapacityProjection, CriteriaProjection, ServiceProjection


class ProjectionRecordInvalid(RuntimeError):
    """A projected node is not one the allowlist's DTO accepts. A configuration fault: callers fail
    closed. The text is fixed and holds no value."""


class SourceStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class ProjectionEndReason(StrEnum):
    """Why a projected row stopped being live: the member left, the grant ended, or a newer version
    of the service has no such window or location (the row is history, never deleted)."""

    LEFT = "left"
    GRANT_ENDED = "grant-ended"
    REPLACED = "replaced"


@dataclass(frozen=True, slots=True)
class GrantRef:
    """The grant a projection is written under: its id and version, stored on the row."""

    grant_id: str
    grant_version: int


@dataclass(frozen=True, slots=True)
class SourceState:
    """One member's projection source for one kind of grant scope: open while the grant projects,
    ended (with the date and the reason) when the grant ends or the member leaves."""

    source_tenant_id: str
    kind: GrantScope
    status: SourceStatus
    grant_id: str
    ended_at: datetime | None
    end_reason: ProjectionEndReason | None


@dataclass(frozen=True, slots=True)
class ProjectedRow[T]:
    """A projection as stored, with the member it came from and its history marks."""

    source_tenant_id: str
    projection: T
    projected_at: datetime
    grant_id: str
    ended_at: datetime | None
    end_reason: ProjectionEndReason | None


class ProjectionWriter(Protocol):
    async def open_source(self, source_tenant_id: str, kind: GrantScope, grant: GrantRef) -> None:
        """Open (or reopen after an end) the source of this member and kind under this grant. The
        caller checked the grant and the membership in the registry first."""
        ...

    async def end_source(
        self,
        source_tenant_id: str,
        kind: GrantScope,
        *,
        at: datetime,
        reason: ProjectionEndReason,
    ) -> bool:
        """End an active source. True when it was active; an ended or missing source is False."""
        ...

    async def upsert_service(
        self,
        source_tenant_id: str,
        service: ServiceProjection,
        *,
        grant: GrantRef,
        projected_at: datetime,
    ) -> bool:
        """Write a service with its location and opening hours. False, and nothing written, when
        the directory source is not active or the stored version is newer (a replay of the stored
        version writes the same rows again)."""
        ...

    async def upsert_capacity(
        self,
        source_tenant_id: str,
        capacity: CapacityProjection,
        *,
        grant: GrantRef,
        projected_at: datetime,
    ) -> bool: ...

    async def upsert_criteria(
        self,
        source_tenant_id: str,
        criteria: CriteriaProjection,
        *,
        grant: GrantRef,
        projected_at: datetime,
    ) -> bool: ...

    async def mark_ended(
        self,
        source_tenant_id: str,
        kind: GrantScope,
        *,
        at: datetime,
        reason: ProjectionEndReason,
    ) -> int:
        """Mark every live row of this member and kind as ended at `at` (history stays, nothing is
        deleted). Returns the number of rows marked."""
        ...


class NetworkView(Protocol):
    async def source(self, source_tenant_id: str, kind: GrantScope) -> SourceState | None: ...

    async def sources(self) -> Sequence[SourceState]: ...

    async def services(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[ServiceProjection]]:
        """The projected services with their location and opening hours. Live rows only by default;
        with `live_only=False` also the ended ones, marked with their end date and reason."""
        ...

    async def capacities(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[CapacityProjection]]: ...

    async def criteria(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[CriteriaProjection]]: ...


class ProjectionPublisher(Protocol):
    """Where a producer sends what it built (TEN-054). The production adapter publishes the message
    to the projection work queue with the source tenant as its tenant (TEN-055); a test records it.
    The message carries the allowlisted body and identifiers, and nothing else."""

    async def publish(self, request: ProjectionRequested) -> None: ...


class ProjectionNotifier(Protocol):
    """Told after the apply step has committed (TEN-054, TEN-058): the network board rebuilds and
    announces itself. A notifier that fails must not undo or fail the projection, which is already
    committed: the apply step logs the class of the error and carries on."""

    async def applied(self, event: ProjectionApplied) -> None: ...

    async def rejected(self, event: ProjectionRejected) -> None: ...
