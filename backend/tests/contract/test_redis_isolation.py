"""Redis contract harnesses share no keys with another run, so concurrent runs on one Redis do not
break each other (I01, TEN-019). A harness removes the keys of its own run tenants and nothing else.
The fixture is the shared Redis of infra/docker-compose.yml. The other run is simulated by a tenant
id this run does not own: its keys must survive every harness close."""

from uuid import uuid4

import pytest
from redis.asyncio import Redis

from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.settings import Settings
from tests.contract.factories import make_redis_cache
from tests.support.redis import RUN_PREFIX, run_tenant


def another_runs_tenant() -> str:
    """A tenant id of a run that is not this one (its id is not this run's prefix)."""
    other_run = uuid4().hex[:8]
    assert f"ct{other_run}-" != RUN_PREFIX
    return f"ct{other_run}-elsewhere"


@pytest.mark.integration
async def test_a_new_harness_does_not_delete_keys_another_run_wrote() -> None:
    other = Redis.from_url(Settings().redis_url, decode_responses=True)
    tenant = another_runs_tenant()
    key = f"diucs:{tenant}:cache:isolation-check:status"
    try:
        await other.set(key, "accepting")
        with bind_tenant(run_tenant("iso")):
            harness = await make_redis_cache()
            try:
                assert await other.get(key) == "accepting"
            finally:
                await harness.close()
        assert await other.get(key) == "accepting"
    finally:
        await other.delete(key)
        await other.aclose()


@pytest.mark.integration
async def test_closing_one_harness_does_not_delete_keys_of_another_run() -> None:
    other = Redis.from_url(Settings().redis_url, decode_responses=True)
    tenant = another_runs_tenant()
    key = f"diucs:{tenant}:cache:svc-1:status"
    try:
        await other.set(key, "accepting")
        with bind_tenant(run_tenant("iso-a")):
            first = await make_redis_cache()
            second = await make_redis_cache()
            try:
                await first.subject.set("svc-1:status", "accepting")
                await second.close()
                # Both harnesses use this run's tenant, and a close removes the keys of the run's
                # tenants (the module docstring, factories.make_redis_cache), so the close of the
                # second harness also removed what the first one wrote. What it must never remove
                # is another run's key: that stays after every close, not only the last.
                assert await first.subject.get("svc-1:status") is None
                assert await other.get(key) == "accepting"
            finally:
                await first.close()
        assert await other.get(key) == "accepting"
    finally:
        await other.delete(key)
        await other.aclose()
