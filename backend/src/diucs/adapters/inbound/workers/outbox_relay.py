"""Outbox relay worker (I03). Red-commit stub (DEC-010): the names and signatures, no behaviour.

The result values are impossible ones, so every test that reads a result fails on its assertion.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Protocol

from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import EventBus
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory

LOCK_NAME: Final = "outbox-relay"
LOCK_TTL: Final = timedelta(seconds=30)
LOCK_MARGIN: Final = timedelta(seconds=5)
BATCH_SIZE: Final = 100
POLL_INTERVAL_SECONDS: Final = 1.0
BACKOFF_START_SECONDS: Final = 1.0
BACKOFF_CAP_SECONDS: Final = 60.0


@dataclass(frozen=True, slots=True)
class RelayResult:
    published: int
    failed: int
    skipped_no_lock: bool


class ActiveTenants(Protocol):
    async def active_tenant_ids(self) -> Sequence[str]: ...


class StaticTenants:
    def __init__(self, tenant_ids: Sequence[str]) -> None:
        self._tenant_ids = tuple(tenant_ids)

    async def active_tenant_ids(self) -> Sequence[str]:
        return self._tenant_ids


class OutboxRelay:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        bus: EventBus,
        cache: Cache,
        clock: Clock,
        tenants: ActiveTenants,
        batch_size: int = BATCH_SIZE,
        *,
        poll_interval_s: float = POLL_INTERVAL_SECONDS,
        backoff_start_s: float = BACKOFF_START_SECONDS,
    ) -> None:
        self._batch_size = batch_size

    async def run_once(self) -> RelayResult:
        return RelayResult(published=-1, failed=-1, skipped_no_lock=False)

    async def run_forever(self, stop: asyncio.Event) -> None:
        raise NotImplementedError
