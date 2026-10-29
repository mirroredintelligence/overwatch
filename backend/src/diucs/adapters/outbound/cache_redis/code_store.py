"""Redis adapter for the text-code store (I13, D27).

One key per phone hash: `code:<phone hash>` under the bound tenant's prefix (tenant_keys.py). The
value is JSON: the code's keyed hash (never the digits), issue time, failed tries, verified flag and
last outcome. Redis expires the key with the code; the store also judges validity by its clock, so
a code the clock has passed is never returned (fail closed), as InMemoryCodeStore does.
"""

from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import DEFAULT_KEY_PREFIX
from diucs.application.ports.outbound.clock import Clock
from diucs.domain.rules.identity_policy import CodeState


def encode_code(code_hash: str, state: CodeState) -> str:
    raise NotImplementedError


def decode_code(text: str) -> tuple[str, CodeState] | None:
    """The stored code and its state, or None when the text is not a code record."""
    raise NotImplementedError


class RedisCodeStore:
    def __init__(self, client: Redis, clock: Clock, key_prefix: str = DEFAULT_KEY_PREFIX) -> None:
        raise NotImplementedError

    async def save(self, phone_hash: str, code_hash: str, state: CodeState) -> None:
        raise NotImplementedError

    async def get(self, phone_hash: str) -> tuple[str, CodeState] | None:
        raise NotImplementedError

    async def clear(self, phone_hash: str) -> None:
        raise NotImplementedError
