"""The board's read model and projector are per tenant (TEN-039, DEC-130, DEC-251).

The board is cached and announced in the scope the work is bound to; an actor of another tenant, a
network scope and no scope at all are refused before anything is read; and what one tenant caches
or publishes is never seen by another. No Docker: the board is a fake and the cache is the
in-memory one, which qualifies every name by the bound scope exactly as the Redis adapter does.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import wall_actor
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL
from diucs.application.tenancy import (
    ScopeId,
    TenantMismatch,
    TenantNotBound,
    bind_scope,
    bind_tenant,
)
from diucs.application.use_cases.board_projector import (
    BOARD_CACHE_KEY,
    BoardAudience,
    BoardProjector,
)
from diucs.application.use_cases.board_projector import board_cache_key as cache_key
from diucs.application.use_cases.query_board import Board, QueryBoard, QueryBoardQuery
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.pressure import Pressure

AT = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
EMPTY = Board(entries=(), pressure=Pressure.NORMAL, all_limited_or_worse=False, generated_at=AT)


class _CountingBoard:
    def __init__(self) -> None:
        self.queries: list[QueryBoardQuery] = []

    async def execute(self, query: QueryBoardQuery) -> Board:
        self.queries.append(query)
        return EMPTY


def _projector() -> tuple[BoardProjector, _CountingBoard, InMemoryCache]:
    clock = FixedClock(AT)
    board = _CountingBoard()
    cache = InMemoryCache(clock)
    return BoardProjector(board, cache, clock), board, cache  # type: ignore[arg-type]


# The key


def test_the_board_key_names_its_audience() -> None:
    assert cache_key(BoardAudience.ALL) == "board:v1:all"
    assert BOARD_CACHE_KEY == "board:v1:all"


@pytest.mark.parametrize("audience", ["all", Role.LEAD, None, "board:v1:all", 1])
def test_an_audience_that_is_not_a_member_of_the_enum_is_refused(audience: Any) -> None:
    with pytest.raises(ValidationFailed) as info:
        cache_key(audience)
    assert info.value.field == "audience"


def test_every_audience_has_its_own_key() -> None:
    keys = [cache_key(audience) for audience in BoardAudience]
    assert len(set(keys)) == len(keys)


# The guards


async def test_a_board_read_for_an_actor_of_another_tenant_reads_and_stores_nothing() -> None:
    projector, board, cache = _projector()

    with bind_tenant("tenant-a"):
        with pytest.raises(TenantMismatch):
            await projector.get_board(wall_actor("tenant-b"))
        assert cache.keys() == frozenset()

    assert board.queries == []


async def test_a_board_read_with_no_tenant_bound_is_refused() -> None:
    projector, board, _ = _projector()

    with pytest.raises(TenantNotBound):
        await projector.get_board(wall_actor("tenant-a"))

    assert board.queries == []


async def test_a_board_read_in_a_network_scope_is_refused() -> None:
    projector, board, _ = _projector()

    with bind_scope(ScopeId.network("net-test")):
        with pytest.raises(TenantNotBound):
            await projector.get_board(wall_actor("tenant-a"))
        with pytest.raises(TenantNotBound):
            await projector.handle("StatusChanged", {"service_id": "svc-1"})

    assert board.queries == []


async def test_a_rebuild_with_no_tenant_bound_is_refused_and_publishes_nothing() -> None:
    projector, board, _ = _projector()

    with pytest.raises(TenantNotBound):
        await projector.handle("StatusChanged", {"service_id": "svc-1"})

    assert board.queries == []


async def test_the_anonymous_link_is_still_refused_in_its_own_tenant() -> None:
    from diucs.application.actor import anonymous_actor
    from diucs.domain.errors import NotAllowed

    projector, board, _ = _projector()

    with bind_tenant("tenant-a"), pytest.raises(NotAllowed):
        await projector.get_board(anonymous_actor("tenant-a", "link"))

    assert board.queries == []


# Two tenants, one cache


async def test_what_one_tenant_caches_another_does_not_read() -> None:
    projector, board, cache = _projector()

    with bind_tenant("tenant-a"):
        await projector.handle("StatusChanged", {"service_id": "svc-1"})
        assert cache.keys() == frozenset({"tenant-a:cache:board:v1:all"})
        await projector.get_board(wall_actor("tenant-a"))
    assert len(board.queries) == 1  # the read came from the cache

    with bind_tenant("tenant-b"):
        assert cache.keys() == frozenset()
        await projector.get_board(wall_actor("tenant-b"))
        assert cache.keys() == frozenset({"tenant-b:cache:board:v1:all"})
    assert [query.actor.tenant_id for query in board.queries] == ["tenant-a", "tenant-b"]


async def test_a_rebuild_announces_on_the_channel_of_its_own_tenant_only() -> None:
    projector, _, cache = _projector()
    with bind_tenant("tenant-a"):
        stream_a = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    with bind_tenant("tenant-b"):
        stream_b = await cache.subscribe(BOARD_UPDATES_CHANNEL)

    with bind_tenant("tenant-a"):
        await projector.handle("StatusChanged", {"service_id": "svc-1"})

    message = json.loads(await anext(stream_a))
    assert message["type"] == "board-changed"
    assert message["service_id"] == "svc-1"
    with bind_tenant("tenant-b"):
        assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 1
    await stream_a.aclose()  # type: ignore[attr-defined]
    await stream_b.aclose()  # type: ignore[attr-defined]


async def test_the_announcement_holds_no_tenant() -> None:
    projector, _, cache = _projector()
    with bind_tenant("tenant-a"):
        stream = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await projector.handle("StatusChanged", {"service_id": "svc-1"})
        text = await anext(stream)
        await stream.aclose()  # type: ignore[attr-defined]

    assert "tenant" not in text


# QueryBoard


class _NoUnit:
    def __call__(self) -> Any:
        raise AssertionError("a unit of work was opened before the guard refused")


async def test_the_query_refuses_an_actor_of_another_tenant_before_it_opens_a_unit() -> None:
    query = QueryBoard(_NoUnit(), FixedClock(AT))  # type: ignore[arg-type]

    with bind_tenant("tenant-a"), pytest.raises(TenantMismatch):
        await query.execute(QueryBoardQuery(actor=wall_actor("tenant-b")))


async def test_the_query_refuses_work_with_no_tenant_bound_before_it_opens_a_unit() -> None:
    query = QueryBoard(_NoUnit(), FixedClock(AT))  # type: ignore[arg-type]

    with pytest.raises(TenantNotBound):
        await query.execute(QueryBoardQuery(actor=wall_actor("tenant-a")))


async def test_the_query_refuses_a_network_scope_before_it_opens_a_unit() -> None:
    query = QueryBoard(_NoUnit(), FixedClock(AT))  # type: ignore[arg-type]

    with bind_scope(ScopeId.network("net-test")), pytest.raises(TenantNotBound):
        await query.execute(QueryBoardQuery(actor=wall_actor("tenant-a")))
