"""The contract harness: one shape for every adapter of the cache and the event bus (P12).

A factory (factories.py) builds a fresh adapter and returns a Harness. Contract tests use only the
harness, so one test runs against the in-memory fake and, later, against Redis or the Service Bus
emulator.

- `subject` is the adapter under test.
- `now()` is the adapter's current instant, in UTC.
- `advance(delta)` moves time forward. A fake moves its manual clock. A real adapter waits.
- `receive(name, timeout)` is for the event bus only. It returns the next message for a queue that
  is due by now, or the next message published to a topic since the harness was made, or None.
  A fake answers at once. A real adapter waits up to `timeout`.
- `close()` releases the adapter.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from diucs.application.ports.outbound.event_bus import BusMessage


@dataclass(frozen=True, slots=True)
class Harness[T]:
    subject: T
    now: Callable[[], datetime]
    advance: Callable[[timedelta], Awaitable[None]]
    close: Callable[[], Awaitable[None]]
    receive: Callable[[str, timedelta], Awaitable[BusMessage | None]] | None = None


async def next_message(messages: AsyncIterator[str], timeout: timedelta) -> str | None:
    """Return the next message from a subscription, or None when none arrives within timeout."""
    try:
        return await asyncio.wait_for(anext(messages), timeout.total_seconds())
    except TimeoutError:
        return None
