"""Stub (red commit)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.application.use_cases.projection_reconcile import ReconcileProjection

HEARTBEAT_INTERVAL: Final = timedelta(minutes=5)
MIN_GAP: Final = timedelta(minutes=1)
AFTER_LEAVE: Final = timedelta(hours=24)
CONSUMER: Final = "projection-heartbeat"


@dataclass(frozen=True, slots=True)
class RunProjectionHeartbeatCommand:
    work_id: str


@dataclass(frozen=True, slots=True)
class HeartbeatResult:
    requested: int
    networks_reconciled: int
    superseded: int
    next_due: datetime | None
    replayed: bool


class RunProjectionHeartbeat:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        registry: NetworkRegistry,
        producer: ProjectNetwork,
        reconcile: ReconcileProjection,
        supersede: Callable[[], Awaitable[int]] | None = None,
    ) -> None:
        pass

    async def execute(self, command: RunProjectionHeartbeatCommand) -> HeartbeatResult:
        raise NotImplementedError


async def ensure_projection_schedule(
    uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock
) -> bool:
    raise NotImplementedError
