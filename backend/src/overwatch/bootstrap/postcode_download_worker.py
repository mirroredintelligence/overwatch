"""The postcode download worker, run in the workers (DEC-1329).

It drains the shared download queue one request at a time: each claimed district's postcodes are
read from the ONS Postcode Directory and stored as shared points, then the request is recorded done
or failed. With nothing queued it waits, so a confirmed district never ties up the admin's page.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime

from overwatch.adapters.outbound.graph_store.postcode_points import Neo4jPostcodePointStore
from overwatch.adapters.outbound.graph_store.tenant_registry import Neo4jPostcodePoints
from overwatch.application.use_cases.postcode_download import DownloadPostcodePoints
from overwatch.application.use_cases.postcode_download_queue import DrainPostcodeDownload
from overwatch.bootstrap.container import Container

log = logging.getLogger(__name__)

IDLE_SECONDS: float = 60.0


class PostcodeDownloadWorker:
    def __init__(self, drain: DrainPostcodeDownload, idle_seconds: float = IDLE_SECONDS) -> None:
        self._drain = drain
        self._idle = idle_seconds

    async def serve(self, stop: asyncio.Event) -> None:
        """Drain requests while there are any, then wait for the next, until `stop` is set."""
        while not stop.is_set():
            try:
                worked = await self._drain(datetime.now(UTC))
            except Exception:
                log.warning("postcode download stopped for this run: reason=run")
                worked = False
            if worked:
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._idle)


def build_postcode_download_worker(container: Container) -> PostcodeDownloadWorker:
    store = Neo4jPostcodePointStore(container.neo4j, Neo4jPostcodePoints(container.neo4j))
    download = DownloadPostcodePoints(container.postcode_directory, store)
    return PostcodeDownloadWorker(DrainPostcodeDownload(container.postcode_queue, download))
