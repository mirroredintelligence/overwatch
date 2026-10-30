"""Stub (red commit)."""

from dataclasses import dataclass

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.unit_of_work import NetworkUnitOfWorkFactory
from diucs.application.use_cases.network_leave import EndProjections


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    checked: int
    sources_ended: int
    rows_marked: int


class ReconcileProjection:
    def __init__(
        self,
        reader_factory: NetworkUnitOfWorkFactory,
        ends: EndProjections,
        registry: NetworkRegistry,
        clock: Clock,
    ) -> None:
        self._ends = ends

    async def member(self, network_id: str, member_tenant_id: str) -> ReconcileResult:
        raise NotImplementedError
