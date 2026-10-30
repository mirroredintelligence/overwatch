"""Helpers for tests that race writers of one record (F6B).

Two things made a "sixteen racing saves" test pass or fail by chance (F6B): the racers were not
concurrent, because a save that opens its transaction late reads the record after an earlier
racer committed it and so replaces it, which is a legitimate save; and `write_tx` runs a managed
transaction, which the driver re-runs after a deadlock, so a refused racer came back as a save
over the winner. A race test therefore holds every racer after its first read until all have read
(`ReadBarrier`) and runs each in a transaction that is never re-run (`write_once`), so a deadlock
reaches the test as the error it is.
"""

import asyncio
from collections.abc import Awaitable, Callable

from neo4j import AsyncDriver, AsyncManagedTransaction

from tests.support.scoped import scoped


class ReadBarrier:
    """Holds each racer, once, until `parties` racers have reached it. A racer that arrives again
    (the same object, a second read) is let through, so only the first read waits."""

    def __init__(self, parties: int, timeout_s: float = 20.0) -> None:
        self._barrier = asyncio.Barrier(parties)
        self._timeout_s = timeout_s
        self._passed: set[int] = set()

    async def hold(self, racer: object) -> None:
        if id(racer) in self._passed:
            return
        self._passed.add(id(racer))
        await asyncio.wait_for(self._barrier.wait(), self._timeout_s)


async def write_once[T](
    driver: AsyncDriver, fn: Callable[[AsyncManagedTransaction], Awaitable[T]]
) -> T:
    """One explicit write transaction on a scoped transaction, committed or rolled back, and never
    re-run. The unit of work is the same: it does not retry a transient error either."""
    async with driver.session() as session:
        tx = await session.begin_transaction()
        try:
            result = await fn(scoped(tx))
            await tx.commit()
        except BaseException:
            await tx.rollback()
            raise
        return result
