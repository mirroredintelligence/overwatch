"""Redis adapters for reporter sessions and the fixed-window rate limit (I13, D27).

Keys, all under the bound tenant's prefix (tenant_keys.py):
- `sess:<id>`: one session, a JSON body, with a sliding TTL (SESSION_TTL).
- `sess-by-person:<practitioner id>`: the set of one practitioner's session ids, so "sign out of
  every phone" deletes them all.
- `sess-epoch:<practitioner id>`: the person's session epoch, a counter that "sign out of every
  phone" raises in the same transaction as the deletes (U37). A session carries the epoch it began
  under and is dead once the person's epoch is any other value, so a session that was being created
  at the moment of the delete (it is not in the index yet) can never outlive the sign-out: `create`
  takes the epoch the caller read before it checked the PIN and refuses, in one script, when it has
  moved. The epoch key lives longer than any session it can kill (EPOCH_TTL).
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

from diucs.adapters.outbound.cache_redis.redis_cache import ROOT
from diucs.adapters.outbound.cache_redis.tenant_keys import millis, tenant_prefix
from diucs.application.ports.outbound.identity import ReporterSession, SessionEpochChanged
from diucs.domain.codes import Role

# [ASSUMED] Sliding lifetime of a reporter session (I13 prompt: 12 hours). A named constant so the
# owner can change it without touching logic.
SESSION_TTL: Final = timedelta(hours=12)

# The epoch outlives the longest session it can kill, with a margin: a session is alive at most
# SESSION_TTL after its last touch, and a dead session is never touched again.
EPOCH_TTL: Final = SESSION_TTL * 2

_SESSION_KEY: Final = "sess:{}"
_EPOCH_KEY: Final = "sess-epoch:{}"
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
            "epoch": session.epoch,
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
        epoch = body.get("epoch", 0)
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 0:
            return None
        return ReporterSession(
            session_id=session_id,
            role=Role(body["role"]),
            practitioner_id=str(body["practitioner"]),
            device_id=str(body["device"]),
            services=tuple(services),
            created=_instant(body["created"]),
            last_seen=_instant(body["lastSeen"]),
            epoch=epoch,
        )
    except ValueError, KeyError, TypeError:
        return None


def _text(value: object) -> str | None:
    return cast("str | None", value)


# Create the session only when the person's epoch is still the one the caller read. One script, so
# no sign out everywhere can run between the check and the write. KEYS: session, index, epoch.
# ARGV: the epoch read, the body, the ttl in ms, the session id, the epoch ttl in ms.
_CREATE_IF_EPOCH = """
local current = tonumber(redis.call('GET', KEYS[3]) or '0')
if current ~= tonumber(ARGV[1]) then
  return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'PX', ARGV[3])
redis.call('SADD', KEYS[2], ARGV[4])
redis.call('PEXPIRE', KEYS[2], ARGV[3], 'NX')
redis.call('PEXPIRE', KEYS[2], ARGV[3], 'GT')
redis.call('PEXPIRE', KEYS[3], ARGV[5], 'GT')
return 1
"""


class RedisSessionStore:
    """Reporter sessions in Redis, under the bound tenant's prefix (see tenant_keys.py)."""

    def __init__(self, client: Redis, key_prefix: str = ROOT, ttl: timedelta = SESSION_TTL) -> None:
        self._client = client
        self._prefix = key_prefix
        self._ttl = ttl

    def _session_key(self, session_id: str) -> str:
        return tenant_prefix(self._prefix) + _SESSION_KEY.format(session_id)

    def _index_key(self, practitioner_id: str) -> str:
        return tenant_prefix(self._prefix) + _PERSON_INDEX_KEY.format(practitioner_id)

    def _epoch_key(self, practitioner_id: str) -> str:
        return tenant_prefix(self._prefix) + _EPOCH_KEY.format(practitioner_id)

    async def epoch(self, practitioner_id: str) -> int:
        return await self._current_epoch(practitioner_id)

    async def _current_epoch(self, practitioner_id: str) -> int:
        key = self._epoch_key(practitioner_id)
        raw = _text(await self._client.get(key))
        return 0 if raw is None else int(raw)

    async def create(
        self,
        role: Role,
        practitioner_id: str,
        device_id: str,
        services: tuple[str, ...],
        now: datetime,
        *,
        epoch: int,
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
            epoch=epoch,
        )
        keys = (
            self._session_key(session_id),
            self._index_key(practitioner_id),
            self._epoch_key(practitioner_id),
        )
        created = await self._client.eval(
            _CREATE_IF_EPOCH,
            3,
            *keys,
            str(epoch),
            encode_session(session),
            str(millis(self._ttl)),
            session_id,
            str(millis(EPOCH_TTL)),
        )
        if int(created) != 1:
            raise SessionEpochChanged
        return session_id

    async def get(self, session_id: str) -> ReporterSession | None:
        key = self._session_key(session_id)
        raw = _text(await self._client.get(key))
        if raw is None:
            return None
        session = decode_session(session_id, raw)
        if session is None or session.epoch != await self._current_epoch(session.practitioner_id):
            return None
        return session

    async def touch(self, session_id: str, now: datetime) -> bool:
        key = self._session_key(session_id)
        raw = _text(await self._client.get(key))
        if raw is None:
            return False
        session = decode_session(session_id, raw)
        if session is None or session.epoch != await self._current_epoch(session.practitioner_id):
            # A session of an earlier epoch is dead: it is not extended, so it simply expires.
            return False
        renewed = replace(session, last_seen=now)
        index = self._index_key(session.practitioner_id)
        epoch_key = self._epoch_key(session.practitioner_id)
        async with self._client.pipeline(transaction=True) as pipe:
            # XX: a session that expired between the read and this write is not brought back.
            pipe.set(key, encode_session(renewed), px=millis(self._ttl), xx=True)
            _extend_index(pipe, index, self._ttl)
            pipe.pexpire(epoch_key, millis(EPOCH_TTL), gt=True)
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
        epoch_key = self._epoch_key(practitioner_id)
        members = cast("set[str]", await self._client.smembers(index))
        keys = [self._session_key(str(session_id)) for session_id in members]
        async with self._client.pipeline(transaction=True) as pipe:
            # The epoch goes up first and in the same transaction as the deletes: a session made
            # in the moment after the index was read carries the old epoch and is dead on arrival.
            pipe.incr(epoch_key)
            pipe.pexpire(epoch_key, millis(EPOCH_TTL), nx=True)
            pipe.pexpire(epoch_key, millis(EPOCH_TTL), gt=True)
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

    def __init__(self, client: Redis, key_prefix: str = ROOT) -> None:
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
