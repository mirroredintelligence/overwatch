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

from diucs.application.tenancy import ScopeId, ScopeKind, current_scope
from diucs.domain.errors import DomainError, ValidationFailed

BOARD_UPDATES_CHANNEL = "board.updates"

FAMILY_CACHE: Final = "cache"
FAMILY_LOCK: Final = "lock"
FAMILY_FENCE: Final = "fence"
FAMILY_CHANNEL: Final = "chan"

# A name is 1 to 512 characters with no control character (code point below 0x20, or 0x7F). Nothing
# else is refused: the replay key's alphabet, colons and dots are all names the cache holds.
MAX_NAME_LENGTH: Final = 512


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
    """The segment a scope's names start with: a tenant's id, or `_net-<id>` for a network. The
    leading underscore cannot begin a tenant id, so the two kinds never share a segment, and the
    platform segment `_` (pairing codes, the source-address limiter) is never produced here."""
    if scope.kind is ScopeKind.NETWORK:
        return f"_{scope.value}"
    return scope.value


def _checked(name: object) -> str:
    if type(name) is not str:
        raise ValidationFailed("name", "must be text")
    if not 0 < len(name) <= MAX_NAME_LENGTH:
        raise ValidationFailed("name", "must be 1 to 512 characters")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in name):
        raise ValidationFailed("name", "must not hold a control character")
    return name


@dataclass(frozen=True, slots=True)
class ScopedNames:
    """Every name the cache holds for one scope: `<segment>:<family>:<name>`. Built only here."""

    segment: str

    def key(self, name: str) -> str:
        return f"{self.segment}:{FAMILY_CACHE}:{_checked(name)}"

    def lock(self, name: str) -> str:
        return f"{self.segment}:{FAMILY_LOCK}:{_checked(name)}"

    def fence(self, name: str) -> str:
        return f"{self.segment}:{FAMILY_FENCE}:{_checked(name)}"

    def channel(self, name: str) -> str:
        return f"{self.segment}:{FAMILY_CHANNEL}:{_checked(name)}"


# The platform namespace (TEN-040): names that belong to no tenant, because they are counted before
# any tenant is known (the source-address limiter of the unauthenticated routes). One segment, and
# a tenant id cannot be it (a tenant id has two or more characters), so no tenant's name can fall
# in it and no platform name in a tenant's.
PLATFORM_SEGMENT: Final = "_"


def platform_names() -> ScopedNames:
    """The names of the platform namespace. Stub for the red commit."""
    raise NotImplementedError


def names_for(scope: ScopeId) -> ScopedNames:
    """The names of one scope. Pure: it takes the scope, it does not read the binding."""
    return ScopedNames(scope_segment(scope))


def scoped_names() -> ScopedNames:
    """The names of the scope bound now. With no scope bound, TenantNotBound (the fixed message of
    the tenancy kernel) propagates: there is no default scope and no global name."""
    return names_for(current_scope())


class Cache(Protocol):
    async def get(self, key: str) -> str | None:
        """Return the stored value of the bound scope, or None when the key is absent or expired.
        Logical names: the adapter qualifies each one with the bound scope (TEN-019)."""
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


class PlatformSlots(Protocol):
    """The cache's platform namespace (TEN-040): single-use, expiring markers that belong to no
    tenant. The only calls that do not read the bound scope, and the only ones that use the platform
    segment; a name is a name of this namespace and nothing else (a tenant name never reaches it)."""

    async def platform_take(self, name: str, ttl: timedelta) -> bool:
        """Store the marker when it is absent or expired, in one step; True when stored."""
        ...

    async def platform_release(self, name: str) -> None:
        """Remove a marker. Removing a missing one is not an error."""
        ...
