"""Redis contract harnesses share no keys, so concurrent runs on one Redis do not break each other
(I01). The fixture is the shared Redis of infra/docker-compose.yml; these tests use only their own
keys and remove them."""

import pytest
from redis.asyncio import Redis

from diucs.bootstrap.settings import Settings
from tests.contract.factories import make_redis_cache


@pytest.mark.integration
async def test_a_new_harness_does_not_delete_keys_another_run_wrote() -> None:
    other = Redis.from_url(Settings().redis_url, decode_responses=True)
    key = "diucs:cache:isolation-check:status"
    try:
        await other.set(key, "accepting")
        harness = await make_redis_cache()
        try:
            assert await other.get(key) == "accepting"
        finally:
            await harness.close()
    finally:
        await other.delete(key)
        await other.aclose()


@pytest.mark.integration
async def test_closing_one_harness_does_not_delete_another_harness_keys() -> None:
    first = await make_redis_cache()
    second = await make_redis_cache()
    try:
        await first.subject.set("svc-1:status", "accepting")
        await second.close()
        assert await first.subject.get("svc-1:status") == "accepting"
    finally:
        await first.close()
