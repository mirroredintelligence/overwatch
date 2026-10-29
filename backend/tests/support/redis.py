"""Redis helpers for the cache suites (I01, TEN-019). A run uses its own tenants, so it touches
only the keys of those tenants and nothing else on the shared Redis.

A run tenant is `ct<RUN_ID>-<label>`. The run id is unique per process, so two runs never share a
key, and a flush refuses any tenant that does not carry this run's id: a slip cannot reach a real
tenant.
"""

import re
from uuid import uuid4

from redis.asyncio import Redis

from diucs.application.tenancy import is_valid_tenant_id

RUN_ID: str = uuid4().hex[:8]
RUN_PREFIX: str = f"ct{RUN_ID}-"
_LABEL = re.compile(r"[a-z0-9-]{1,20}")


def run_tenant(label: str) -> str:
    """A tenant id for this run and a label: at most 31 characters, a valid tenant id."""
    if _LABEL.fullmatch(label) is None:
        raise ValueError("a run tenant label is 1 to 20 characters of a-z, 0-9 and hyphen")
    tenant = f"{RUN_PREFIX}{label}"
    if not is_valid_tenant_id(tenant):
        raise ValueError("a run tenant id is not a valid tenant id")
    return tenant


async def flush_tenant(client: Redis, tenant: str) -> None:
    """Delete every key of one run tenant. The trailing colon makes the match exact: tenant `a`
    never matches `diucs:ab:`. A tenant that is not this run's is refused before any key is read."""
    if not tenant.startswith(RUN_PREFIX):
        raise ValueError("flush_tenant refuses a tenant that is not this run's")
    await _delete_matching(client, f"diucs:{tenant}:*")


async def flush_run(client: Redis) -> None:
    """Delete every key of every tenant of this run, and nothing else."""
    await _delete_matching(client, f"diucs:{RUN_PREFIX}*")


async def flush_prefix(client: Redis, prefix: str) -> None:
    """Delete every key under a prefix that ends with a colon, so the match is exact."""
    if not prefix.endswith(":"):
        raise ValueError("a flush prefix ends with a colon, so the match is exact")
    await _delete_matching(client, f"{prefix}*")


async def _delete_matching(client: Redis, pattern: str) -> None:
    keys = [key async for key in client.scan_iter(match=pattern)]
    if keys:
        await client.delete(*keys)
