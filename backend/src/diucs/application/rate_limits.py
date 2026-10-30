"""Limits on the routes that carry no token, counted in the platform namespace (TEN-040, audit C
TEN-C25).

A request with no token has no tenant yet, and one that names an unknown host never will, so its
limit cannot be a tenant's: it is a count per source address in the cache's platform namespace
(`PlatformSlots`), taken before the host is looked at. The address is hashed before it reaches the
cache, so no address is held there, and the count belongs to no tenant's keys.

The window is counted from each event, not from the first: an event takes the first free slot
`rl:<kind>:<address hash>#<n>`, written with the window as its lifetime, so a slot comes free one
window after it was taken. Taking a slot is one atomic step, so parallel callers can never hold more
than `limit` slots between them. Nothing here is a record: losing the cache loses no fact. A cache
that cannot be reached raises, and the caller refuses the request, never lets it through.
"""

import hashlib
import re
from datetime import timedelta
from typing import Final

from diucs.application.ports.outbound.cache import PlatformSlots

# [ASSUMED] (domain-rules 7): a person's browser asks for a profile once per page, so 60 a minute is
# generous for one address and small for a flood.
PUBLIC_REQUESTS_PER_ADDRESS: Final = 60
PUBLIC_WINDOW: Final = timedelta(minutes=1)
PUBLIC_KIND: Final = "public"

_KIND: Final = re.compile(r"[a-z][a-z0-9-]{0,31}")
_PREFIX: Final = "rl"


def address_digest(address: str) -> str:
    """The first 32 hexadecimal digits of the address's SHA-256: what the cache holds."""
    return hashlib.sha256(address.encode("utf-8")).hexdigest()[:32]


class PlatformRateLimiter:
    def __init__(self, slots: PlatformSlots) -> None:
        self._slots = slots

    async def take(self, kind: str, address: str, limit: int, window: timedelta) -> str | None:
        """Count one event and return the slot it took, or None (and count nothing) when `limit`
        events are already inside the window."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if _KIND.fullmatch(kind) is None:
            raise ValueError("kind is not a limit kind")
        base = f"{_PREFIX}:{kind}:{address_digest(address)}"
        for number in range(limit):
            slot = f"{base}#{number}"
            if await self._slots.platform_take(slot, window):
                return slot
        return None

    async def release(self, slot: str) -> None:
        """Give back a slot that `take` returned. A slot that is already free does nothing."""
        await self._slots.platform_release(slot)
