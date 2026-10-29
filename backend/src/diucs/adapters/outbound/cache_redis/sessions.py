"""Redis adapters for reporter sessions and the fixed-window rate limit (I13, D27).

Keys, all under the bound tenant's prefix (tenant_keys.py):
- `sess:<id>`: one session, a JSON body, with a sliding TTL (SESSION_TTL).
- `sess-by-person:<practitioner id>`: the set of one practitioner's session ids, so "sign out of
  every phone" deletes them all.
- `rate:<key>`: a fixed-window counter (INCR, with its TTL set once by EXPIRE NX).

Losing Redis signs people out; that is acceptable. Nothing here is a record, and no session id,
code or phone hash is ever logged.
"""

from datetime import datetime, timedelta
from typing import Final

from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import DEFAULT_KEY_PREFIX
from diucs.application.ports.outbound.identity import ReporterSession
from diucs.domain.codes import Role

# [ASSUMED] Sliding lifetime of a reporter session (I13 prompt: 12 hours). A named constant so the
# owner can change it without touching logic.
SESSION_TTL: Final = timedelta(hours=12)


def new_session_id() -> str:
    """A random session id of 256 bits, urlsafe base64 without padding (43 characters)."""
    raise NotImplementedError


def encode_session(session: ReporterSession) -> str:
    """The JSON body stored under `sess:<id>`: role, practitioner, device, services, created and
    last seen (UTC, ISO 8601). The session id is not in the body; it is in the key."""
    raise NotImplementedError


def decode_session(session_id: str, text: str) -> ReporterSession | None:
    """The session stored as `text`, or None when the text is not a session body."""
    raise NotImplementedError


class RedisSessionStore:
    def __init__(
        self, client: Redis, key_prefix: str = DEFAULT_KEY_PREFIX, ttl: timedelta = SESSION_TTL
    ) -> None:
        raise NotImplementedError

    async def create(
        self,
        role: Role,
        practitioner_id: str,
        device_id: str,
        services: tuple[str, ...],
        now: datetime,
    ) -> str:
        raise NotImplementedError

    async def get(self, session_id: str) -> ReporterSession | None:
        raise NotImplementedError

    async def touch(self, session_id: str, now: datetime) -> bool:
        raise NotImplementedError

    async def delete(self, session_id: str) -> None:
        raise NotImplementedError

    async def delete_all_for_person(self, practitioner_id: str) -> None:
        raise NotImplementedError


class RedisRateLimiter:
    def __init__(self, client: Redis, key_prefix: str = DEFAULT_KEY_PREFIX) -> None:
        raise NotImplementedError

    async def allow(self, key: str, limit: int, window: timedelta) -> bool:
        raise NotImplementedError
