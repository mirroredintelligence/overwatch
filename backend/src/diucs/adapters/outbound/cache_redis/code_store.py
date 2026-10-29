"""Redis adapter for the text-code store (I13, D27).

One key per (purpose, phone hash): `code:<purpose>:<phone hash>` under the bound tenant's
prefix (tenant_keys.py). The
value is JSON: the code's keyed hash (never the digits), issue time, failed tries, verified flag and
last outcome. Redis expires the key with the code; the store also judges validity by its clock, so
a code the clock has passed is never returned (fail closed), as InMemoryCodeStore does.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Final, cast

from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import DEFAULT_KEY_PREFIX
from diucs.adapters.outbound.cache_redis.tenant_keys import millis, tenant_prefix
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import CodeResendRefused
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.identity_policy import (
    CODE_VALID_FOR,
    CodeOutcome,
    CodeState,
    can_resend,
    check_purpose,
)

_CODE_KEY: Final = "code:{}:{}"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed("issued_at", "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _instant(text: object) -> datetime:
    if not isinstance(text, str):
        raise ValueError("an instant is text")
    return _aware_utc(datetime.fromisoformat(text))


def encode_code(code_hash: str, state: CodeState) -> str:
    return json.dumps(
        {
            "hash": code_hash,
            "issuedAt": _aware_utc(state.issued_at).isoformat(),
            "failedTries": state.failed_tries,
            "verified": state.verified,
            "lastOutcome": None if state.last_outcome is None else state.last_outcome.value,
        },
        sort_keys=True,
    )


def decode_code(text: str) -> tuple[str, CodeState] | None:
    """The stored code and its state, or None when the text is not a code record."""
    try:
        body = json.loads(text)
        code_hash = body["hash"]
        if not isinstance(code_hash, str):
            return None
        outcome = body["lastOutcome"]
        state = CodeState(
            issued_at=_instant(body["issuedAt"]),
            failed_tries=int(body["failedTries"]),
            verified=bool(body["verified"]),
            last_outcome=None if outcome is None else CodeOutcome(outcome),
        )
    except ValueError, KeyError, TypeError:
        return None
    return code_hash, state


def _valid_at(issued: datetime, now: datetime) -> bool:
    """The code is valid from its issue time for CODE_VALID_FOR, and not before it (as the fake)."""
    return issued <= now < issued + CODE_VALID_FOR


def _text(value: object) -> str | None:
    return cast("str | None", value)


class RedisCodeStore:
    """Text codes in Redis, under the bound tenant's prefix. It holds only the code's keyed hash,
    which the caller computes; the digits never reach this module."""

    def __init__(self, client: Redis, clock: Clock, key_prefix: str = DEFAULT_KEY_PREFIX) -> None:
        self._client = client
        self._clock = clock
        self._prefix = key_prefix

    def _key(self, purpose: str, phone_hash: str) -> str:
        return tenant_prefix(self._prefix) + _CODE_KEY.format(purpose, phone_hash)

    async def save(self, purpose: str, phone_hash: str, code_hash: str, state: CodeState) -> None:
        check_purpose(purpose)
        issued = _aware_utc(state.issued_at)
        key = self._key(purpose, phone_hash)
        stored = _text(await self._client.get(key))
        if stored is not None:
            current = decode_code(stored)
            # A different code within the resend cooldown of the one it replaces is refused.
            if (
                current is not None
                and current[0] != code_hash
                and not can_resend(current[1].issued_at, issued)
            ):
                raise CodeResendRefused()
        remaining = issued + CODE_VALID_FOR - self._clock.now().astimezone(UTC)
        if remaining <= timedelta(0):
            await self._client.delete(key)
            return
        await self._client.set(key, encode_code(code_hash, state), px=millis(remaining))

    async def get(self, purpose: str, phone_hash: str) -> tuple[str, CodeState] | None:
        check_purpose(purpose)
        key = self._key(purpose, phone_hash)
        stored = _text(await self._client.get(key))
        if stored is None:
            return None
        record = decode_code(stored)
        if record is None or not _valid_at(record[1].issued_at, self._clock.now().astimezone(UTC)):
            await self._client.delete(key)
            return None
        return record

    async def clear(self, purpose: str, phone_hash: str) -> None:
        check_purpose(purpose)
        key = self._key(purpose, phone_hash)
        await self._client.delete(key)
