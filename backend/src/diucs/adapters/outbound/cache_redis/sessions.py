"""Redis adapters for reporter sessions and the fixed-window rate limit (I13, D27).

Keys, all under the bound tenant's prefix (tenant_keys.py):
- `sess:<id>`: one session, a JSON body, with a sliding TTL (SESSION_TTL).
- `sess-by-person:<practitioner id>`: the set of one practitioner's session ids, so "sign out of
  every phone" deletes them all.
- `rate:<key>`: a fixed-window counter (INCR, with its TTL set once by EXPIRE NX).

Losing Redis signs people out; that is acceptable. Nothing here is a record, and no session id,
code or phone hash is ever logged.
"""

import json
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final, cast

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline

from diucs.adapters.outbound.cache_redis.redis_cache import DEFAULT_KEY_PREFIX
from diucs.adapters.outbound.cache_redis.tenant_keys import millis, tenant_prefix
from diucs.application.ports.outbound.identity import ReporterSession
from diucs.domain.codes import Role

# [ASSUMED] Sliding lifetime of a reporter session (I13 prompt: 12 hours). A named constant so the
# owner can change it without touching logic.
SESSION_TTL: Final = timedelta(hours=12)

_SESSION_KEY: Final = "sess:{}"
_PERSON_INDEX_KEY: Final = "sess-by-person:{}"
_RATE_KEY: Final = "rate:{}"
# 256 random bits, urlsafe base64 without padding: 43 characters.
_SESSION_ID_BYTES: Final = 32


def new_session_id() -> str:
    """A random session id of 256 bits, urlsafe base64 without padding (43 characters)."""
    return secrets.token_urlsafe(_SESSION_ID_BYTES)


def _instant(text: object) -> datetime:
    """An ISO 8601 instant that must carry a timezone. Raises ValueError otherwise."""
    if not isinstance(text, str):
        raise ValueError("an instant is text")
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise ValueError("an instant needs a timezone")
    return value.astimezone(UTC)


def encode_session(session: ReporterSession) -> str:
    """The JSON body stored under `sess:<id>`: role, practitioner, device, services, created and
    last seen (UTC, ISO 8601). The session id is not in the body; it is in the key."""
    return json.dumps(
        {
            "role": session.role.value,
            "practitioner": session.practitioner_id,
            "device": session.device_id,
            "services": list(session.services),
            "created": session.created.astimezone(UTC).isoformat(),
            "lastSeen": session.last_seen.astimezone(UTC).isoformat(),
        },
        sort_keys=True,
    )


def decode_session(session_id: str, text: str) -> ReporterSession | None:
    """The session stored as `text`, or None when the text is not a session body."""
    try:
        body = json.loads(text)
        services = body["services"]
        if not isinstance(services, list) or not all(isinstance(s, str) for s in services):
            return None
        return ReporterSession(
            session_id=session_id,
            role=Role(body["role"]),
            practitioner_id=str(body["practitioner"]),
            device_id=str(body["device"]),
            services=tuple(services),
            created=_instant(body["created"]),
            last_seen=_instant(body["lastSeen"]),
        )
    except ValueError, KeyError, TypeError:
        return None


def _text(value: object) -> str | None:
    return cast("str | None", value)


class RedisSessionStore:
    """Reporter sessions in Redis, under the bound tenant's prefix (see tenant_keys.py)."""

    def __init__(
        self, client: Redis, key_prefix: str = DEFAULT_KEY_PREFIX, ttl: timedelta = SESSION_TTL
    ) -> None:
        self._client = client
        self._prefix = key_prefix
        self._ttl = ttl

    def _session_key(self, session_id: str) -> str:
        return tenant_prefix(self._prefix) + _SESSION_KEY.format(session_id)

    def _index_key(self, practitioner_id: str) -> str:
        return tenant_prefix(self._prefix) + _PERSON_INDEX_KEY.format(practitioner_id)

    async def create(
        self,
        role: Role,
        practitioner_id: str,
        device_id: str,
        services: tuple[str, ...],
        now: datetime,
    ) -> str:
        session_id = new_session_id()
        session = ReporterSession(
            session_id=session_id,
            role=role,
            practitioner_id=practitioner_id,
            device_id=device_id,
            services=tuple(services),
            created=now,
            last_seen=now,
        )
        key = self._session_key(session_id)
        index = self._index_key(practitioner_id)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.set(key, encode_session(session), px=millis(self._ttl))
            pipe.sadd(index, session_id)
            _extend_index(pipe, index, self._ttl)
            await pipe.execute()
        return session_id

    async def get(self, session_id: str) -> ReporterSession | None:
        key = self._session_key(session_id)
        raw = _text(await self._client.get(key))
        if raw is None:
            return None
        return decode_session(session_id, raw)

    async def touch(self, session_id: str, now: datetime) -> bool:
        key = self._session_key(session_id)
        raw = _text(await self._client.get(key))
        if raw is None:
            return False
        session = decode_session(session_id, raw)
        if session is None:
            return False
        renewed = replace(session, last_seen=now)
        index = self._index_key(session.practitioner_id)
        async with self._client.pipeline(transaction=True) as pipe:
            # XX: a session that expired between the read and this write is not brought back.
            pipe.set(key, encode_session(renewed), px=millis(self._ttl), xx=True)
            _extend_index(pipe, index, self._ttl)
            results = await pipe.execute()
        # SET ... XX answers True when it wrote, None when the key had gone.
        return bool(results[0])

    async def delete(self, session_id: str) -> None:
        key = self._session_key(session_id)
        raw = _text(await self._client.get(key))
        if raw is None:
            return
        session = decode_session(session_id, raw)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            if session is not None:
                pipe.srem(self._index_key(session.practitioner_id), session_id)
            await pipe.execute()

    async def delete_all_for_person(self, practitioner_id: str) -> None:
        index = self._index_key(practitioner_id)
        members = cast("set[str]", await self._client.smembers(index))
        keys = [self._session_key(str(session_id)) for session_id in members]
        async with self._client.pipeline(transaction=True) as pipe:
            if keys:
                pipe.delete(*keys)
            pipe.delete(index)
            await pipe.execute()


def _extend_index(pipe: Pipeline, index: str, ttl: timedelta) -> None:
    """The index of one practitioner's sessions lives at least as long as its longest session, so
    "sign out of every phone" always finds them. NX sets a TTL on a new index; GT only extends
    it."""
    pipe.pexpire(index, millis(ttl), nx=True)
    pipe.pexpire(index, millis(ttl), gt=True)


class RedisRateLimiter:
    """A fixed-window throttle in Redis (I13): INCR, and the window's TTL set once by EXPIRE NX in
    the same transaction, so a window can never be left without an end."""

    def __init__(self, client: Redis, key_prefix: str = DEFAULT_KEY_PREFIX) -> None:
        self._client = client
        self._prefix = key_prefix

    async def allow(self, key: str, limit: int, window: timedelta) -> bool:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window <= timedelta(0):
            raise ValueError("window must be positive")
        name = tenant_prefix(self._prefix) + _RATE_KEY.format(key)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(name)
            pipe.pexpire(name, millis(window), nx=True)
            results = await pipe.execute()
        return int(results[0]) <= limit
