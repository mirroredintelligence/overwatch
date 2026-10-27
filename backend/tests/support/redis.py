"""Redis helpers for the cache suites (I01). They touch only keys under one run's prefix."""

from redis.asyncio import Redis


async def flush_prefix(client: Redis, prefix: str) -> None:
    """Delete every key under one run's prefix, and nothing else on the shared Redis."""
    keys = [key async for key in client.scan_iter(match=f"{prefix}*")]
    if keys:
        await client.delete(*keys)
