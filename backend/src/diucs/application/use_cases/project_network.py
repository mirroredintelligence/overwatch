"""The network projection producer (TEN-054). Stub for the red commit."""

from dataclasses import dataclass

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.projection import ProjectionPublisher
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.model.network import GrantScope


class ProducerUnitNotReadOnly(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectionRun:
    requested: int
    skipped: int


class ProjectNetwork:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: NetworkRegistry,
        publisher: ProjectionPublisher,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory

    async def project(self, kind: GrantScope, service_id: str) -> ProjectionRun:
        raise NotImplementedError

    async def project_all(self, service_id: str) -> ProjectionRun:
        raise NotImplementedError

    async def backfill(self, kind: GrantScope | None = None) -> ProjectionRun:
        raise NotImplementedError
