"""The network live stream on a real Redis (TEN-059, DEC-548, DEC-132 item 4).

Written, not run, in build wave 5 (the owner's instruction: the whole integration suite runs once,
on the merged tip).

The stream is the network's own channel in Redis. The tests show: a message published in a
network's scope reaches that network's stream and no other's; a tenant's own board channel never
reaches a network stream; and a member who leaves is told `scope-ended` and the stream closes.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from diucs.adapters.inbound.fhir_rest import routes_network_events as module
from diucs.adapters.inbound.fhir_rest.routes_network_events import (
    SCOPE_ENDED_EVENT,
    network_events,
)
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import (
    BOARD_UPDATES_CHANNEL,
    NETWORK_BOARD_UPDATES_CHANNEL,
)
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")

CHANGED = "2026-10-23T13:12:00+00:00"


@pytest_asyncio.fixture(loop_scope="session")
async def cache() -> AsyncIterator[RedisCache]:
    store = RedisCache.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    try:
        yield store
    finally:
        await store.aclose()


class _Access:
    def __init__(self) -> None:
        self.member = True

    async def require_member(self, actor: Actor, network_id: str) -> None:
        if not self.member:
            raise NotFound("the network was not found")


def _actor(tenant: str) -> Actor:
    return Actor(Role.ADVISOR, "p", None, "api", frozenset(), tenant)


def _message() -> str:
    return json.dumps({"type": "network-board-changed", "at": CHANGED})


async def test_a_message_reaches_its_own_networks_stream_and_no_others(
    cache: RedisCache, run_identity: RunIdentity
) -> None:
    mine, other = run_identity.network_id, f"{run_identity.network_id}-b"
    with bind_network(mine):
        messages = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    with bind_network(other):
        await cache.publish(NETWORK_BOARD_UPDATES_CHANNEL, _message())
    with bind_tenant(run_identity.tenant_id):
        await cache.publish(
            BOARD_UPDATES_CHANNEL, json.dumps({"type": "board-changed", "at": CHANGED})
        )
    stream = network_events(messages, _Access(), _actor(run_identity.tenant_id), mine)  # type: ignore[arg-type]
    pending = asyncio.ensure_future(stream.__anext__())
    done, _ = await asyncio.wait({pending}, timeout=1)
    assert not done  # nothing from the other network or the tenant board
    with bind_network(mine):
        await cache.publish(NETWORK_BOARD_UPDATES_CHANNEL, _message())
    assert (await asyncio.wait_for(pending, 2)).startswith("event: network-board")
    await stream.aclose()


async def test_a_member_who_leaves_is_told_the_scope_ended(
    cache: RedisCache, run_identity: RunIdentity, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "RECHECK_INTERVAL_SECONDS", 0.05)
    access = _Access()
    with bind_network(run_identity.network_id):
        messages = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    stream = network_events(
        messages, access, _actor(run_identity.tenant_id), run_identity.network_id
    )  # type: ignore[arg-type]
    access.member = False
    events = [item async for item in stream]
    assert events[-1] == f"event: {SCOPE_ENDED_EVENT}\ndata: {{}}\n\n"
