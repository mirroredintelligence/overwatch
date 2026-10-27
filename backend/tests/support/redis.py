"""Redis helpers for the cache suites (I01). They touch only keys under the diucs: prefix."""

from redis.asyncio import Redis

DIUCS_KEYS = "diucs:*"


async def flush_diucs_keys(client: Redis) -> None:
    """Delete every key under the diucs: prefix, and nothing else on the shared Redis."""
    keys = [key async for key in client.scan_iter(match=DIUCS_KEYS)]
    if keys:
        await client.delete(*keys)


async def flush_prefix(client: Redis, prefix: str) -> None:
    """Delete every key under one run's prefix, and nothing else on the shared Redis."""
    keys = [key async for key in client.scan_iter(match=f"{prefix}*")]
    if keys:
        await client.delete(*keys)
