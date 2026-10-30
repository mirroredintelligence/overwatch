"""The network projection apply step (TEN-054). Stub for the red commit."""

from dataclasses import dataclass
from enum import StrEnum

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.projection import ProjectionNotifier
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.domain.errors import DomainError
from diucs.domain.events import ProjectionRejectReason, ProjectionRequested


class ApplyOutcome(StrEnum):
    APPLIED = "applied"
    STALE = "stale"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ApplyResult:
    outcome: ApplyOutcome
    reason: ProjectionRejectReason | None = None


class ProjectionMismatch(DomainError):
    pass


class ApplyUnitReadOnly(RuntimeError):
    pass


class ApplyProjection:
    def __init__(
        self,
        uow_factory: NetworkUnitOfWorkFactory,
        registry: NetworkRegistry,
        clock: Clock,
        notifier: ProjectionNotifier | None = None,
    ) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, request: ProjectionRequested, *, message_id: str, source_tenant_id: str
    ) -> ApplyResult:
        raise NotImplementedError
