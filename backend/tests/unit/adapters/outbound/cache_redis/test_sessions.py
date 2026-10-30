"""Pure tests of the reporter session and rate limit adapters (I13): the id, the body and the
refusals that come before any Redis call. No Docker; the Redis client is never reached here."""

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.outbound.cache_redis.sessions import (
    SESSION_TTL,
    RedisRateLimiter,
    RedisSessionStore,
    decode_session,
    encode_session,
    new_session_id,
)
from diucs.application.ports.outbound.identity import ReporterSession
from diucs.application.tenancy import TenantNotBound, bind_tenant
from diucs.domain.codes import Role

# Any call that reaches the client fails the test: the refusals below must come first.
NO_CLIENT: Any = object()
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def _session() -> ReporterSession:
    return ReporterSession(
        session_id="a-session-id",
        role=Role.REPORTER,
        practitioner_id="prac-1",
        device_id="device-1",
        services=("svc-1", "svc-2"),
        created=NOW,
        last_seen=NOW + timedelta(minutes=5),
    )


def test_a_session_id_is_256_random_bits_in_urlsafe_text() -> None:
    session_id = new_session_id()
    padded = session_id + "=" * (-len(session_id) % 4)
    assert len(session_id) == 43
    assert len(base64.urlsafe_b64decode(padded)) == 32
    assert "+" not in session_id and "/" not in session_id


def test_two_session_ids_differ() -> None:
    assert new_session_id() != new_session_id()


def test_the_session_ttl_is_twelve_hours() -> None:
    assert timedelta(hours=12) == SESSION_TTL


def test_a_session_body_round_trips() -> None:
    session = _session()
    assert decode_session(session.session_id, encode_session(session)) == session


def test_the_session_body_does_not_repeat_the_session_id() -> None:
    session = _session()
    assert session.session_id not in encode_session(session)


@pytest.mark.parametrize("text", ["", "not json", "{}", '{"role": "no-such-role"}'])
def test_text_that_is_not_a_session_body_decodes_to_none(text: str) -> None:
    assert decode_session("a-session-id", text) is None


async def test_create_without_a_tenant_is_refused_before_redis() -> None:
    store = RedisSessionStore(NO_CLIENT)
    with pytest.raises(TenantNotBound):
        await store.create(Role.REPORTER, "prac-1", "device-1", (), NOW, epoch=0)


async def test_a_session_body_keeps_its_epoch_and_an_old_body_reads_as_epoch_zero() -> None:
    session = replace(_session(), epoch=3)
    assert decode_session(session.session_id, encode_session(session)) == session
    old = json.loads(encode_session(_session()))
    del old["epoch"]
    assert decode_session("a-session-id", json.dumps(old)) == _session()


@pytest.mark.parametrize("epoch", ["3", -1, True, None, 1.5])
def test_a_body_with_a_bad_epoch_decodes_to_none(epoch: object) -> None:
    body = json.loads(encode_session(_session()))
    body["epoch"] = epoch
    assert decode_session("a-session-id", json.dumps(body)) is None


async def test_get_touch_delete_and_delete_all_without_a_tenant_are_refused() -> None:
    store = RedisSessionStore(NO_CLIENT)
    with pytest.raises(TenantNotBound):
        await store.epoch("prac-1")
    with pytest.raises(TenantNotBound):
        await store.get("a-session-id")
    with pytest.raises(TenantNotBound):
        await store.touch("a-session-id", NOW)
    with pytest.raises(TenantNotBound):
        await store.delete("a-session-id")
    with pytest.raises(TenantNotBound):
        await store.delete_all_for_person("prac-1")


async def test_a_rate_limit_without_a_tenant_is_refused_before_redis() -> None:
    with pytest.raises(TenantNotBound):
        await RedisRateLimiter(NO_CLIENT).allow("code:h1", 3, timedelta(seconds=60))


async def test_a_rate_limit_needs_a_positive_limit_and_window() -> None:
    limiter = RedisRateLimiter(NO_CLIENT)
    with bind_tenant("tenant-alpha"):
        with pytest.raises(ValueError):
            await limiter.allow("code:h1", 0, timedelta(seconds=60))
        with pytest.raises(ValueError):
            await limiter.allow("code:h1", 3, timedelta(0))
