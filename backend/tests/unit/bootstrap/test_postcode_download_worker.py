"""The postcode download worker (DEC-1329): it drains the queue while there is work, waits when
there is none, and a run that fails is logged by reason only and does not stop the worker."""

import asyncio
from datetime import datetime

from overwatch.bootstrap.postcode_download_worker import PostcodeDownloadWorker


class ScriptedDrain:
    def __init__(self, answers: list[bool | Exception]) -> None:
        self._answers = answers
        self.calls = 0

    async def __call__(self, now: datetime) -> bool:
        self.calls += 1
        answer = self._answers.pop(0) if self._answers else False
        if isinstance(answer, Exception):
            raise answer
        return answer


async def test_the_worker_drains_while_there_is_work_then_waits_until_stopped() -> None:
    drain = ScriptedDrain([True, True, False, False])
    stop = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    worker = PostcodeDownloadWorker(drain, idle_seconds=0.01)  # type: ignore[arg-type]
    await asyncio.gather(worker.serve(stop), stop_soon())
    assert drain.calls >= 3


async def test_a_failed_run_does_not_stop_the_worker() -> None:
    drain = ScriptedDrain([RuntimeError("boom"), False])
    stop = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    worker = PostcodeDownloadWorker(drain, idle_seconds=0.01)  # type: ignore[arg-type]
    await asyncio.gather(worker.serve(stop), stop_soon())
    assert drain.calls >= 2
