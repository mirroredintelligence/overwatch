"""Contract for removing every cache name of one scope (TEN-074, DEC-960 item 6): a purged tenant's
values, locks and fences go, and no other scope's name does, not even a scope whose id only starts
the same. Runs against every factory in factories.py (the in-memory fake and Redis)."""

from datetime import timedelta
from typing import cast
from uuid import uuid4

import pytest

from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.tenant_export import ScopeCachePurger
from diucs.application.tenancy import ScopeId, ScopeInvalid, bind_network, bind_scope, bind_tenant
from tests.contract.harness import Harness
from tests.support.redis import run_tenant

LONG = timedelta(seconds=30)


def _tenant(label: str) -> str:
    return run_tenant(f"{label}-{uuid4().hex[:8]}")


async def test_every_name_of_the_scope_is_removed_and_counted(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    purger = cast(ScopeCachePurger, cache)
    doomed = _tenant("p")
    with bind_tenant(doomed):
        await cache.set("board:v1:all", "x", LONG)
        await cache.set("other", "y", LONG)
        lock = await cache.acquire_lock("job", LONG)
        assert lock is not None
    removed = await purger.purge_scope(ScopeId.tenant(doomed))
    assert removed >= 2
    with bind_tenant(doomed):
        assert await cache.get("board:v1:all") is None
        assert await cache.get("other") is None
        assert await cache.acquire_lock("job", LONG) is not None  # the lock is gone too


async def test_another_tenant_and_a_tenant_whose_id_starts_the_same_are_untouched(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    purger = cast(ScopeCachePurger, cache)
    doomed = _tenant("q")
    sibling = doomed + "-two"
    stranger = _tenant("r")
    for tenant in (doomed, sibling, stranger):
        with bind_tenant(tenant):
            await cache.set("k", tenant, LONG)
    await purger.purge_scope(ScopeId.tenant(doomed))
    for tenant in (sibling, stranger):
        with bind_tenant(tenant):
            assert await cache.get("k") == tenant
    with bind_tenant(doomed):
        assert await cache.get("k") is None


async def test_a_scope_with_nothing_removes_nothing_and_a_network_scope_is_its_own(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    purger = cast(ScopeCachePurger, cache)
    empty = _tenant("s")
    assert await purger.purge_scope(ScopeId.tenant(empty)) == 0
    tenant = _tenant("t")
    network = f"net-{uuid4().hex[:8]}"
    with bind_network(network):
        await cache.set("network-board:v1:all", "n", LONG)
    with bind_tenant(tenant):
        await cache.set("k", "t", LONG)
    await purger.purge_scope(ScopeId.tenant(tenant))
    with bind_scope(ScopeId.network(network)):
        assert await cache.get("network-board:v1:all") == "n"


@pytest.mark.parametrize("pattern", ["*", "a?b", "[x]", "back\\slash"])
async def test_a_tenant_id_cannot_be_a_pattern_so_a_glob_never_reaches_another_scope(
    cache_harness: Harness[Cache], pattern: str
) -> None:
    cache = cache_harness.subject
    victim = _tenant("u")
    with bind_tenant(victim):
        await cache.set("k", "v", LONG)
    with pytest.raises(ScopeInvalid):
        await cast(ScopeCachePurger, cache).purge_scope(ScopeId.tenant(pattern))
    with bind_tenant(victim):
        assert await cache.get("k") == "v"
