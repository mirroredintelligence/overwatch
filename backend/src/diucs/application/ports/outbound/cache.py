"""Outbound port: the cache for read models, short-lived keys, live-update fan-out and single-flight locks.

Redis is the production cache (architecture.md, Platform decisions). The cache holds no record of
truth: nothing in Neo4j depends on it, and losing every key must lose no fact.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

BOARD_UPDATES_CHANNEL = "board.updates"


@dataclass(frozen=True, slots=True)
class Lock:
    """A single-flight lock holding a fencing token. Only the holder of the current token may release."""

    name: str
    fencing_token: int


class Cache(Protocol):
    async def get(self, key: str) -> str | None:
        """Return the stored value, or None when the key is absent or expired."""
        ...

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        """Store a value. With no ttl the key stays until deleted or overwritten."""
        ...

    async def delete(self, key: str) -> None:
        """Remove a key. Deleting a missing key is not an error."""
        ...

    async def publish(self, channel: str, message: str) -> None:
        """Send a message to the subscribers present at the time of publishing. Nothing is stored."""
        ...

    def subscribe(self, channel: str) -> AsyncIterator[str]:
        """Return an iterator of messages published to the channel after this call returns.

        The subscription exists from the moment this method returns, not from the first
        iteration (DEC-057). Messages published earlier are not replayed.
        """
        ...

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        """Return a lock with a fresh fencing token, or None while another holder's lock is unexpired."""
        ...

    async def release_lock(self, lock: Lock) -> None:
        """Release the lock only if its token is the current holder's token. Otherwise do nothing."""
        ...
