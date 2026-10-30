"""The network live stream (TEN-059, DEC-548, DEC-132 item 4).

GET /network/{id}/events relays the network's own channel as server-sent events. The viewer is
checked against the registry before the subscription opens and again on a timer while it is open,
so a member who leaves (or whose network is suspended) is told `scope-ended` and the stream closes:
the token is not what keeps a stream alive. The stream holds no figure: a message becomes
`event: network-board` with the time and nothing else. Both the stream and the checks are tested
here without a socket.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.inbound.fhir_rest import routes_network_events as module
from diucs.adapters.inbound.fhir_rest.routes_network_events import (
    SCOPE_ENDED_EVENT,
    network_events,
    to_network_sse,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import NETWORK_BOARD_UPDATES_CHANNEL
from diucs.application.tenancy import bind_network
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound
from tests.support.edge import EDGE_NOW, TENANT_A

NET = "net-pilot"
CHANGED = "2026-10-23T13:12:00+00:00"


def test_a_network_board_message_becomes_one_event_with_only_the_time() -> None:
    message = {"type": "network-board-changed", "at": CHANGED, "extra": "x"}
    assert to_network_sse(message) == (
        'event: network-board\ndata: {"changedAt":"2026-10-23T13:12:00Z"}\n\n'
    )


@pytest.mark.parametrize(
    "message",
    [
        None,
        "text",
        {},
        {"type": "board-changed", "at": CHANGED},
        {"type": "network-board-changed"},
        {"type": "network-board-changed", "at": "yesterday"},
        {"type": "network-board-changed", "at": "2026-10-23T13:12:00+01:00"},
        {"serviceId": "svc-1", "changedAt": CHANGED},
    ],
)
def test_anything_else_is_dropped(message: Any) -> None:
    assert to_network_sse(message) is None


class _Access:
    def __init__(self) -> None:
        self.checks = 0
        self.refuse_from: int | None = None

    async def require_member(self, actor: Actor, network_id: str) -> None:
        self.checks += 1
        if self.refuse_from is not None and self.checks >= self.refuse_from:
            raise NotFound("the network was not found")


def _actor() -> Actor:
    return Actor(
        Role.ADVISOR, "p", None, "api", frozenset(), TENANT_A, network_ids=frozenset({NET})
    )


async def _collect(stream: AsyncIterator[str], count: int) -> list[str]:
    out: list[str] = []
    async for item in stream:
        out.append(item)
        if len(out) == count:
            break
    return out


async def test_a_message_published_in_the_network_scope_reaches_the_stream() -> None:
    cache = InMemoryCache(FixedClock(EDGE_NOW))
    with bind_network(NET):
        messages = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
        await cache.publish(
            NETWORK_BOARD_UPDATES_CHANNEL,
            json.dumps({"type": "network-board-changed", "at": CHANGED}),
        )
    stream = network_events(messages, _Access(), _actor(), NET)  # type: ignore[arg-type]
    [event] = await asyncio.wait_for(_collect(stream, 1), 1)
    assert event == 'event: network-board\ndata: {"changedAt":"2026-10-23T13:12:00Z"}\n\n'
    await stream.aclose()  # type: ignore[attr-defined]


async def test_another_networks_message_never_reaches_the_stream() -> None:
    cache = InMemoryCache(FixedClock(EDGE_NOW))
    with bind_network(NET):
        messages = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    with bind_network("net-other"):
        await cache.publish(
            NETWORK_BOARD_UPDATES_CHANNEL,
            json.dumps({"type": "network-board-changed", "at": CHANGED}),
        )
    stream = network_events(messages, _Access(), _actor(), NET)  # type: ignore[arg-type]
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(_collect(stream, 1), 0.1)
    await stream.aclose()  # type: ignore[attr-defined]


async def test_a_member_who_leaves_is_told_the_scope_ended_and_the_stream_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "RECHECK_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(module, "KEEPALIVE_INTERVAL_SECONDS", 0.02)
    cache = InMemoryCache(FixedClock(EDGE_NOW))
    with bind_network(NET):
        messages = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
        assert cache.subscriber_count(NETWORK_BOARD_UPDATES_CHANNEL) == 1
    access = _Access()
    access.refuse_from = 2
    stream = network_events(messages, access, _actor(), NET)  # type: ignore[arg-type]
    events = [item async for item in stream]
    assert events[-1] == f"event: {SCOPE_ENDED_EVENT}\ndata: {{}}\n\n"
    assert all(e.startswith(": keep-alive") for e in events[:-1])
    with bind_network(NET):
        assert cache.subscriber_count(NETWORK_BOARD_UPDATES_CHANNEL) == 0  # the subscription closed


async def test_an_idle_stream_sends_keep_alives(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "KEEPALIVE_INTERVAL_SECONDS", 0.01)
    cache = InMemoryCache(FixedClock(EDGE_NOW))
    with bind_network(NET):
        messages = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    stream = network_events(messages, _Access(), _actor(), NET)  # type: ignore[arg-type]
    items = await asyncio.wait_for(_collect(stream, 2), 1)
    assert items == [": keep-alive\n\n", ": keep-alive\n\n"]
    await stream.aclose()  # type: ignore[attr-defined]


def test_the_recheck_is_at_most_every_thirty_seconds_and_not_less_often_than_a_minute() -> None:
    assert 5 <= module.RECHECK_INTERVAL_SECONDS <= 60
    assert timedelta(seconds=module.RECHECK_INTERVAL_SECONDS) <= timedelta(minutes=1)
