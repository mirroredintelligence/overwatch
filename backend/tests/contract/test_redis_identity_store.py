"""Redis cases of the identity stores (I13): reporter sessions, the fixed-window rate limit and the
text-code store, as the tenant-prefixed keys they write. The shared code-store cases run in
test_code_store_contract.py.

They need the Redis of infra/docker-compose.yml (DIUCS_REDIS_URL). Every key lives under a per-run
prefix, and the tenants are bound explicitly, because the integration hook binds none in this
folder. Nothing here starts Neo4j.
"""

import asyncio
import hashlib
import hmac
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.code_store import RedisCodeStore
from diucs.adapters.outbound.cache_redis.sessions import (
    SESSION_TTL,
    RedisRateLimiter,
    RedisSessionStore,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.identity import ReporterSession
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.settings import Settings
from diucs.domain.codes import Role
from diucs.domain.rules.identity_policy import CodeState
from tests.support.redis import flush_prefix

pytestmark = pytest.mark.integration

TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
CODE_DIGITS = "482913"
KEY = b"sample-phone-hash-key"


@pytest.fixture
async def redis() -> AsyncIterator[tuple[Redis, str]]:
    prefix = f"diucs-identity-{uuid4().hex}:"
    client = Redis.from_url(Settings().redis_url, decode_responses=True)
    try:
        yield client, prefix
    finally:
        try:
            await flush_prefix(client, prefix)
        finally:
            await client.aclose()


def _code_hash(digits: str) -> str:
    return hmac.new(KEY, digits.encode("ascii"), hashlib.sha256).hexdigest()


async def test_a_stored_code_is_the_keyed_hash_and_never_the_digits(
    redis: tuple[Redis, str],
) -> None:
    client, prefix = redis
    store = RedisCodeStore(client, FixedClock(NOW), key_prefix=prefix)
    code_hash = _code_hash(CODE_DIGITS)

    with bind_tenant(TENANT_A):
        await store.save("h1", code_hash, CodeState(issued_at=NOW))

    raw = await client.get(f"{prefix}{TENANT_A}:code:h1")
    assert raw is not None
    assert code_hash in raw
    assert CODE_DIGITS not in raw


async def test_a_code_key_carries_the_tenant_and_a_ttl(redis: tuple[Redis, str]) -> None:
    client, prefix = redis
    store = RedisCodeStore(client, FixedClock(NOW), key_prefix=prefix)

    with bind_tenant(TENANT_A):
        await store.save("h1", _code_hash(CODE_DIGITS), CodeState(issued_at=NOW))

    key = f"{prefix}{TENANT_A}:code:h1"
    assert await client.exists(key) == 1
    assert 0 < await client.pttl(key) <= 10 * 60 * 1000


async def test_a_code_is_invisible_to_another_tenant(redis: tuple[Redis, str]) -> None:
    client, prefix = redis
    store = RedisCodeStore(client, FixedClock(NOW), key_prefix=prefix)
    code_hash = _code_hash(CODE_DIGITS)
    with bind_tenant(TENANT_A):
        await store.save("h1", code_hash, CodeState(issued_at=NOW))

    with bind_tenant(TENANT_B):
        assert await store.get("h1") is None
        await store.clear("h1")

    with bind_tenant(TENANT_A):
        stored = await store.get("h1")
    assert stored is not None
    assert stored[0] == code_hash


async def test_a_session_is_created_read_and_deleted(redis: tuple[Redis, str]) -> None:
    client, prefix = redis
    sessions = RedisSessionStore(client, key_prefix=prefix)

    with bind_tenant(TENANT_A):
        session_id = await sessions.create(Role.REPORTER, "prac-1", "device-1", ("svc-1",), NOW)
        assert len(session_id) == 43
        assert await sessions.get(session_id) == ReporterSession(
            session_id=session_id,
            role=Role.REPORTER,
            practitioner_id="prac-1",
            device_id="device-1",
            services=("svc-1",),
            created=NOW,
            last_seen=NOW,
        )
        await sessions.delete(session_id)
        assert await sessions.get(session_id) is None


async def test_the_session_key_carries_the_tenant_and_the_full_ttl(
    redis: tuple[Redis, str],
) -> None:
    client, prefix = redis
    sessions = RedisSessionStore(client, key_prefix=prefix)

    with bind_tenant(TENANT_A):
        session_id = await sessions.create(Role.REPORTER, "prac-1", "device-1", (), NOW)

    key = f"{prefix}{TENANT_A}:sess:{session_id}"
    assert await client.exists(key) == 1
    ttl_ms = await client.pttl(key)
    assert (
        int(SESSION_TTL.total_seconds()) * 1000 - 60_000
        < ttl_ms
        <= SESSION_TTL.total_seconds() * 1000
    )


async def test_touch_extends_the_session_to_the_full_ttl(redis: tuple[Redis, str]) -> None:
    client, prefix = redis
    sessions = RedisSessionStore(client, key_prefix=prefix)
    with bind_tenant(TENANT_A):
        session_id = await sessions.create(Role.REPORTER, "prac-1", "device-1", (), NOW)
    key = f"{prefix}{TENANT_A}:sess:{session_id}"
    await client.pexpire(key, 5_000)
    later = NOW + timedelta(minutes=1)

    with bind_tenant(TENANT_A):
        assert await sessions.touch(session_id, later) is True
        touched = await sessions.get(session_id)

    assert await client.pttl(key) > 5_000
    assert touched is not None
    assert touched.last_seen == later
    assert touched.created == NOW


async def test_touch_of_a_missing_session_is_false(redis: tuple[Redis, str]) -> None:
    client, prefix = redis
    with bind_tenant(TENANT_A):
        assert await RedisSessionStore(client, key_prefix=prefix).touch("no-such-id", NOW) is False


async def test_delete_all_for_a_person_removes_each_of_their_sessions(
    redis: tuple[Redis, str],
) -> None:
    client, prefix = redis
    sessions = RedisSessionStore(client, key_prefix=prefix)
    with bind_tenant(TENANT_A):
        first = await sessions.create(Role.REPORTER, "prac-1", "phone-1", (), NOW)
        second = await sessions.create(Role.REPORTER, "prac-1", "tablet-1", (), NOW)
        other = await sessions.create(Role.REPORTER, "prac-2", "phone-2", (), NOW)

        await sessions.delete_all_for_person("prac-1")

        assert await sessions.get(first) is None
        assert await sessions.get(second) is None
        assert await sessions.get(other) is not None


async def test_sessions_are_kept_per_tenant(redis: tuple[Redis, str]) -> None:
    client, prefix = redis
    sessions = RedisSessionStore(client, key_prefix=prefix)
    with bind_tenant(TENANT_A):
        session_id = await sessions.create(Role.REPORTER, "prac-1", "device-1", (), NOW)

    with bind_tenant(TENANT_B):
        assert await sessions.get(session_id) is None
        await sessions.delete_all_for_person("prac-1")

    with bind_tenant(TENANT_A):
        assert await sessions.get(session_id) is not None


async def test_a_rate_limit_allows_three_attempts_then_refuses(redis: tuple[Redis, str]) -> None:
    client, prefix = redis
    limiter = RedisRateLimiter(client, key_prefix=prefix)
    window = timedelta(seconds=60)

    with bind_tenant(TENANT_A):
        results = [await limiter.allow("code:h1", 3, window) for _ in range(4)]

    assert results == [True, True, True, False]
    key = f"{prefix}{TENANT_A}:rate:code:h1"
    assert 0 < await client.pttl(key) <= 60_000


async def test_a_rate_limit_window_ends_and_the_count_starts_again(
    redis: tuple[Redis, str],
) -> None:
    client, prefix = redis
    limiter = RedisRateLimiter(client, key_prefix=prefix)
    window = timedelta(seconds=1)

    with bind_tenant(TENANT_A):
        for _ in range(3):
            assert await limiter.allow("pin:device-1", 3, window) is True
        assert await limiter.allow("pin:device-1", 3, window) is False
        await asyncio.sleep(1.2)
        assert await limiter.allow("pin:device-1", 3, window) is True


async def test_rate_limits_are_kept_per_tenant(redis: tuple[Redis, str]) -> None:
    client, prefix = redis
    limiter = RedisRateLimiter(client, key_prefix=prefix)
    window = timedelta(seconds=60)
    with bind_tenant(TENANT_A):
        for _ in range(3):
            await limiter.allow("code:h1", 3, window)
        assert await limiter.allow("code:h1", 3, window) is False

    with bind_tenant(TENANT_B):
        assert await limiter.allow("code:h1", 3, window) is True


async def test_no_log_line_holds_a_session_id_a_code_or_its_hash(
    redis: tuple[Redis, str], caplog: pytest.LogCaptureFixture
) -> None:
    client, prefix = redis
    sessions = RedisSessionStore(client, key_prefix=prefix)
    codes = RedisCodeStore(client, FixedClock(NOW), key_prefix=prefix)
    limiter = RedisRateLimiter(client, key_prefix=prefix)
    code_hash = _code_hash(CODE_DIGITS)
    caplog.set_level(logging.DEBUG)

    with bind_tenant(TENANT_A):
        session_id = await sessions.create(Role.REPORTER, "prac-1", "device-1", (), NOW)
        await sessions.get(session_id)
        await sessions.touch(session_id, NOW)
        await codes.save("h1", code_hash, CodeState(issued_at=NOW))
        await codes.get("h1")
        await limiter.allow("code:h1", 3, timedelta(seconds=60))

    assert session_id not in caplog.text
    assert code_hash not in caplog.text
    assert CODE_DIGITS not in caplog.text
