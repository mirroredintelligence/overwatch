"""The platform's staff registry sync, run in the workers (DEC-1327).

Every interval it runs `SyncStaffRegistry`: each active tenant's role groups are read through Graph
with the tenant's own consent, and the tenant's staff records are made to match. A tenant whose read
fails keeps its records; the loop logs a reason word, never a name, an address or an id.
"""

import asyncio
import contextlib
import logging

import httpx

from overwatch.adapters.outbound.entra_graph.groups import GraphEntraGroups
from overwatch.application.use_cases.staff_registry import SyncStaffRegistry
from overwatch.bootstrap.admin_consent import consent_links
from overwatch.bootstrap.container import Container
from overwatch.bootstrap.settings import Settings

log = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS: float = 600.0


class StaffRegistrySync:
    def __init__(
        self, sync: SyncStaffRegistry, interval_seconds: float = SYNC_INTERVAL_SECONDS
    ) -> None:
        self._sync = sync
        self._interval = interval_seconds

    async def serve(self, stop: asyncio.Event) -> None:
        """Run the sync now and then every interval, until `stop` is set."""
        while not stop.is_set():
            try:
                report = await self._sync.execute()
                log.info(
                    "staff registry synced: tenants=%d replaced=%d skipped=%d",
                    report.tenants,
                    report.replaced,
                    report.skipped,
                )
            except Exception:
                log.warning("staff registry sync stopped for this run: reason=run")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._interval)


def build_staff_registry_sync(
    container: Container, settings: Settings, http: httpx.AsyncClient
) -> StaffRegistrySync | None:
    """The sync for this process, or None when the staff client id is not set (no sign-in can name
    a directory then, so there is nothing to keep)."""
    links = consent_links(settings)
    if links is None:
        log.warning("staff registry: not synced, the staff client id is not set")
        return None
    groups = GraphEntraGroups(http, container.secrets, links.client_id)
    return StaffRegistrySync(
        SyncStaffRegistry(
            container.uow_factory,
            container.tenants,
            groups,
            container.staff_registry,
            container.secrets,
            container.clock,
        )
    )
