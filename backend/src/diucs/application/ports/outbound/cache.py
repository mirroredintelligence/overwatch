"""Outbound port: the cache for read models, short-lived keys, live updates and single-flight locks.

Redis is the production cache (architecture.md, Platform decisions). The cache holds no record of
truth: nothing in Neo4j depends on it, and losing every key must lose no fact.

Every name the cache holds belongs to a scope: the tenant or the network scope the unit of work is
bound to (DEC-130 item 7, DEC-132 items 1 and 4, TEN-019). Callers pass logical names (`board:v1`,
`board.updates`, `relay`); the adapter qualifies each one with the bound scope through
`ScopedNames`, the one builder of every cache name. A missing scope is an error, never a default.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Protocol

from diucs.application.tenancy import ScopeId
from diucs.domain.errors import DomainError

BOARD_UPDATES_CHANNEL = "board.updates"

FAMILY_CACHE: Final = "cache"
FAMILY_LOCK: Final = "lock"
FAMILY_FENCE: Final = "fence"
FAMILY_CHANNEL: Final = "chan"


class CacheScopeMismatch(DomainError):
    """A lock was released in a scope other than the one it was issued in: a bug, never a stale
    holder, so nothing is released."""

    def __init__(self) -> None:
        super().__init__("lock belongs to another scope")


@dataclass(frozen=True, slots=True)
class Lock:
    """A single-flight lock with a fencing token. Only the current holder's token may release it.
    `scope` is the segment of the scope the lock was issued in."""

    name: str
    fencing_token: int
    scope: str


def scope_segment(scope: ScopeId) -> str:
    """STUB (TEN-019 red): the segment is always empty, so no scope is ever qualified."""
    return ""


@dataclass(frozen=True, slots=True)
class ScopedNames:
    """STUB (TEN-019 red): builds names without the scope."""

    segment: str

    def key(self, name: str) -> str:
        return f"{self.segment}:{FAMILY_CACHE}:{name}"

    def lock(self, name: str) -> str:
        return f"{self.segment}:{FAMILY_LOCK}:{name}"

    def fence(self, name: str) -> str:
        return f"{self.segment}:{FAMILY_FENCE}:{name}"

    def channel(self, name: str) -> str:
        return f"{self.segment}:{FAMILY_CHANNEL}:{name}"


def names_for(scope: ScopeId) -> ScopedNames:
    return ScopedNames(scope_segment(scope))


def scoped_names() -> ScopedNames:
    """STUB (TEN-019 red): no scope is read, so an unbound call does not fail."""
    return ScopedNames("")


class Cache(Protocol):
    async def get(self, key: str) -> str | None:
        """Return the stored value, or None when the key is absent or expired."""
        ...

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        """Store a value. With no ttl the key stays until deleted or overwritten."""
        ...

    async def set_if_absent(self, key: str, value: str, ttl: timedelta) -> bool:
        """Store a value only when the key is absent or expired, in one step. Return True when it
        was stored, False when the key already held a value (which is left unchanged). The ttl is
        required and must be positive (ValueError otherwise): a marker that never expires would
        grow the cache without bound (I07)."""
        ...

    async def delete(self, key: str) -> None:
        """Remove a key. Deleting a missing key is not an error."""
        ...

    async def publish(self, channel: str, message: str) -> None:
        """Send a message to the subscribers present now. Nothing is stored."""
        ...

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        """Return an iterator of messages published to the channel after this call returns.

        The subscription exists from the moment this method returns, not from the first
        iteration (DEC-058). Messages published earlier are not replayed. The channel is the one of
        the scope bound when this is called, and the subscription keeps it.

        The iterator may also have `aclose()`, which ends the subscription and frees it on the
        cache. A caller that stops reading (the live stream, when a client leaves) closes it.
        """
        ...

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        """Return a lock with a fresh fencing token, or None while another holder is unexpired."""
        ...

    async def release_lock(self, lock: Lock) -> None:
        """Release the lock only when its token is the current holder's. Otherwise do nothing. A
        lock issued in another scope is refused with CacheScopeMismatch and nothing is released."""
        ...
