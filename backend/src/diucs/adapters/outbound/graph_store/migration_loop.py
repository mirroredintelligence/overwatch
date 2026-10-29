"""One batched data step of a migration (TEN-005): the statement is repeated, each repetition in
its own session and write transaction, until it reports that it changed nothing.

A loop statement receives `$batch` and every parameter of its migration, and returns exactly one
row with an integer column `changed`. `CALL { } IN TRANSACTIONS` is not available inside a managed
transaction, so the loop is here, in Python, as the test harness's own wipe is. A repetition is
safe to retry (the driver may run the callback more than once): the statements select only what is
still to do. Raw `tx.run` is allowed in this module by the architecture test, like the runner's.
"""

from collections.abc import Mapping
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction


class LoopResultInvalid(Exception):
    """The statement did not return exactly one row with an integer `changed`."""


class LoopDidNotFinish(Exception):
    """The statement still changed rows after the largest number of repetitions allowed."""


async def run_loop(
    driver: AsyncDriver,
    statement: str,
    params: Mapping[str, Any],
    *,
    batch: int,
    max_iterations: int,
) -> int:
    """Repeat `statement` until it changes nothing. Return the total it changed."""
    arguments = {**params, "batch": batch}

    async def repetition(tx: AsyncManagedTransaction) -> int:
        result = await tx.run(statement, arguments)
        rows = await result.data()
        if len(rows) != 1:
            raise LoopResultInvalid
        changed = rows[0].get("changed")
        if isinstance(changed, bool) or not isinstance(changed, int):
            raise LoopResultInvalid
        return changed

    total = 0
    for _ in range(max_iterations):
        async with driver.session() as session:
            changed = await session.execute_write(repetition)
        if changed == 0:
            return total
        total += changed
    raise LoopDidNotFinish
