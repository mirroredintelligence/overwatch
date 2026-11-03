"""The postcode download requests (DEC-1329): the shift lead's confirm queues a prefix, and a
worker drains one request at a time, so the request never ties up the page.

A request is checked again when it is queued, because the worker runs later and from the queue. A
download the directory cannot answer fails the request; it is never stored as done with no points.
"""

from datetime import datetime

from overwatch.application.ports.outbound.lookups import LookupRejected, TransientLookupError
from overwatch.application.ports.outbound.postcode_download_queue import PostcodeDownloadQueue
from overwatch.application.use_cases.postcode_download import DownloadPostcodePoints
from overwatch.domain.rules.postcode import partial_district


class RequestPostcodeDownload:
    def __init__(self, queue: PostcodeDownloadQueue) -> None:
        self._queue = queue

    async def __call__(self, text: str, now: datetime) -> str:
        normalised = " ".join(text.split()).upper()
        if partial_district(normalised) is None:
            raise ValueError("the prefix is not a postcode district")
        await self._queue.request(normalised, now)
        return normalised


class DrainPostcodeDownload:
    """One claimed request: download it, then record done or failed. False when none waits."""

    def __init__(self, queue: PostcodeDownloadQueue, download: DownloadPostcodePoints) -> None:
        self._queue = queue
        self._download = download

    async def __call__(self, now: datetime) -> bool:
        prefix = await self._queue.claim_next(now)
        if prefix is None:
            return False
        try:
            written = await self._download(prefix)
        except TransientLookupError, LookupRejected, ValueError:
            await self._queue.fail(prefix, now)
            return True
        await self._queue.finish(prefix, written, now)
        return True
