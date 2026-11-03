"""The postcode download queue (DEC-1329): a request is keyed by its prefix, a worker drains one
request at a time, and a download the directory cannot answer fails rather than storing nothing."""

from datetime import UTC, datetime
from typing import Any

from overwatch.application.ports.outbound.lookups import TransientLookupError
from overwatch.application.use_cases.postcode_download import DownloadPostcodePoints
from overwatch.application.use_cases.postcode_download_queue import (
    DrainPostcodeDownload,
    RequestPostcodeDownload,
)
from tests.unit.application.use_cases.test_postcode_download import (
    POINTS,
    FakeDirectory,
    FakeStore,
)

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


class MemoryQueue:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def request(self, prefix: str, now: datetime) -> None:
        self.rows[prefix] = {"status": "queued", "requestedAt": now}

    async def claim_next(self, now: datetime) -> str | None:
        queued = sorted(
            (p for p, row in self.rows.items() if row["status"] == "queued"),
            key=lambda p: self.rows[p]["requestedAt"],
        )
        if not queued:
            return None
        self.rows[queued[0]]["status"] = "running"
        return queued[0]

    async def finish(self, prefix: str, postcodes: int, now: datetime) -> None:
        self.rows[prefix].update(status="done", postcodes=postcodes)

    async def fail(self, prefix: str, now: datetime) -> None:
        self.rows[prefix]["status"] = "failed"


class _Down:
    async def count(self, prefix: str) -> int:
        raise TransientLookupError

    async def postcodes(self, prefix: str) -> list[Any]:
        raise TransientLookupError


async def test_a_request_is_keyed_by_its_prefix_so_asking_twice_is_one_request() -> None:
    queue = MemoryQueue()
    request = RequestPostcodeDownload(queue)
    assert await request(" dt4 ", NOW) == "DT4"
    await request("DT4", NOW)
    assert list(queue.rows) == ["DT4"]


async def test_a_request_that_is_not_a_district_is_refused_and_queued_nothing() -> None:
    queue = MemoryQueue()
    for text in ("DT4 ABC", "DT4'; --", ""):
        try:
            await RequestPostcodeDownload(queue)(text, NOW)
        except ValueError:
            pass
        else:
            raise AssertionError(text)
    assert queue.rows == {}


async def test_a_worker_downloads_the_oldest_request_and_marks_it_done() -> None:
    queue = MemoryQueue()
    store = FakeStore()
    drain = DrainPostcodeDownload(queue, DownloadPostcodePoints(FakeDirectory(POINTS), store))
    await queue.request("DT4", NOW)
    assert await drain(NOW) is True
    assert queue.rows["DT4"] == {"status": "done", "requestedAt": NOW, "postcodes": 3}
    assert await drain(NOW) is False


async def test_a_download_the_directory_cannot_answer_fails_the_request_and_stores_nothing() -> (
    None
):
    queue = MemoryQueue()
    store = FakeStore()
    drain = DrainPostcodeDownload(queue, DownloadPostcodePoints(_Down(), store))  # type: ignore[arg-type]
    await queue.request("DT4", NOW)
    assert await drain(NOW) is True
    assert queue.rows["DT4"]["status"] == "failed"
    assert store.by_postcode == {}
