"""The network board's projector, cache key and channel (TEN-058, DEC-547, DEC-132 item 4).

The projector rebuilds the board of one network when what the board shows changes (a projection
applied, a grant effective or ended, a member added or removed), stores it in the cache and tells
open pages on the network's own channel. Both the key and the channel belong to the network scope
the work is bound to (the cache qualifies them `_net-<id>`), so one network's board never reaches
another's cache or stream, and a tenant's cache never holds a network's. A read is never served from
the cache without asking the registry about the viewer first: a member who left sees nothing, cached
or not. The cache is not a store of record: a failing read or write falls back to a rebuild. The
query and the registry gate are fakes here; the cache is the in-memory one.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from diucs.application.use_cases.network_board_projector import (
    NETWORK_BOARD_CACHE_KEY,
    NETWORK_BOARD_CACHE_TTL,
    NETWORK_BOARD_CHANGED,
    NETWORK_REBUILD_EVENTS,
    NetworkBoardAudience,
    NetworkBoardProjector,
    network_board_cache_key,
    network_board_from_dict,
    network_board_to_dict,
)

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import NETWORK_BOARD_UPDATES_CHANNEL
from diucs.application.tenancy import ScopeKind, bind_network, current_scope_or_none
from diucs.application.use_cases.query_network_board import NetworkBoardView
from diucs.domain.codes import Role, ServiceCategory, Status
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.events import ProjectionApplied, ProjectionRejected, ProjectionRejectReason
from diucs.domain.model.network import DirectorySource, GrantScope
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.network_board import NetworkBoard, NetworkBoardEntry
from diucs.domain.rules.pressure import Pressure

AT = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
NET_A = "net-pilot"
NET_B = "net-other"


def entry(
    index: int, status: Status | None, presentation: ListingPresentation
) -> NetworkBoardEntry:
    shown = presentation is ListingPresentation.SHOWN
    return NetworkBoardEntry(
        row_ref=f"lst-{index}",
        organisation_name=f"Org {index}",
        service_name=f"Service {index}",
        category=list(ServiceCategory)[index % len(ServiceCategory)],
        presentation=presentation,
        status=status,
        unit_label="referrals" if shown else None,
        effective_available=3 if shown else None,
        over_by=1 if shown and index % 2 else None,
        used=5 if shown else None,
        established=8 if shown else None,
        reported_at=AT - timedelta(minutes=index) if shown else None,
        stale_warning=bool(index % 2),
        was_due_at=AT - timedelta(hours=1) if index % 3 == 0 else None,
        source=DirectorySource.MANUAL,
    )


def view(network: str = NET_A, entries: tuple[NetworkBoardEntry, ...] = ()) -> NetworkBoardView:
    return NetworkBoardView(
        NetworkBoard(entries, Pressure.WATCH, False, AT),
        "Capacity board",
        "Urgent pathway",
        "Europe/London",
    )


def every_kind_view() -> NetworkBoardView:
    rows = [entry(i, s, ListingPresentation.SHOWN) for i, s in enumerate(Status)]
    rows.append(entry(len(rows), None, ListingPresentation.UNAVAILABLE))
    return view(entries=tuple(rows))


def staff(tenant: str = "tenant-b") -> Actor:
    return Actor(Role.ADVISOR, "prac-1", None, "web", frozenset(), tenant)


class _Query:
    def __init__(self) -> None:
        self.built: list[tuple[str, Any]] = []
        self.error: Exception | None = None

    async def build(self, network_id: str) -> NetworkBoardView:
        self.built.append((network_id, current_scope_or_none()))
        if self.error is not None:
            raise self.error
        return view(network_id)


class _Access:
    def __init__(self, members: set[str]) -> None:
        self.members = members
        self.asked: list[tuple[str, str]] = []

    async def require_member(self, actor: Actor, network_id: str) -> None:
        self.asked.append((actor.tenant_id, network_id))
        if actor.tenant_id not in self.members:
            raise NotFound("the network was not found")


class _BrokenCache(InMemoryCache):
    def __init__(self, clock: FixedClock, *, read: bool = False, write: bool = False) -> None:
        super().__init__(clock)
        self.fail_read, self.fail_write = read, write

    async def get(self, key: str) -> str | None:
        if self.fail_read:
            raise ConnectionError("down")
        return await super().get(key)

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        if self.fail_write:
            raise ConnectionError("down")
        await super().set(key, value, ttl)


def projector(
    members: set[str] | None = None, cache: InMemoryCache | None = None
) -> tuple[NetworkBoardProjector, _Query, _Access, InMemoryCache]:
    clock = FixedClock(AT)
    query, access = _Query(), _Access(members if members is not None else {"tenant-b"})
    store = cache or InMemoryCache(clock)
    built = NetworkBoardProjector(query, access, store, clock)  # type: ignore[arg-type]
    return built, query, access, store


# the key


def test_the_key_names_its_audience() -> None:
    assert network_board_cache_key(NetworkBoardAudience.ALL) == "network-board:v1:all"
    assert NETWORK_BOARD_CACHE_KEY == "network-board:v1:all"
    assert timedelta(seconds=60) == NETWORK_BOARD_CACHE_TTL


@pytest.mark.parametrize("audience", ["all", Role.LEAD, None, "network-board:v1:all", 1])
def test_an_audience_that_is_not_a_member_of_the_enum_is_refused(audience: Any) -> None:
    with pytest.raises(ValidationFailed) as info:
        network_board_cache_key(audience)
    assert info.value.field == "audience"


def test_the_network_key_is_not_the_tenant_boards_key() -> None:
    from diucs.application.use_cases.board_projector import BOARD_CACHE_KEY

    assert NETWORK_BOARD_CACHE_KEY != BOARD_CACHE_KEY
    assert NETWORK_BOARD_UPDATES_CHANNEL != "board.updates"


# the encoding


def test_a_board_with_every_status_and_presentation_survives_the_cache_encoding() -> None:
    original = every_kind_view()
    encoded: Any = json.loads(json.dumps(network_board_to_dict(original)))
    assert network_board_from_dict(encoded) == original


def test_the_encoding_holds_no_tenant_and_no_grant() -> None:
    text = json.dumps(network_board_to_dict(every_kind_view()))
    assert "tenant" not in text and "grant" not in text


# the rebuild


def test_the_events_that_rebuild_the_board_are_the_ones_that_change_what_it_shows() -> None:
    assert {
        "ProjectionApplied",
        "GrantEffective",
        "GrantEnded",
        "MemberAdded",
        "MemberRemoved",
    } == NETWORK_REBUILD_EVENTS


async def test_an_event_the_board_does_not_show_builds_nothing() -> None:
    built, query, _, cache = projector()
    assert await built.handle("GrantProposed", {"network_id": NET_A}) is False
    assert query.built == [] and cache.keys() == frozenset()


async def test_a_rebuild_runs_in_the_network_scope_and_caches_and_announces_there() -> None:
    built, query, _, cache = projector()
    received: list[str] = []
    import asyncio

    async def listen() -> None:
        with bind_network(NET_A):
            async for message in cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL):
                received.append(message)
                return

    task = asyncio.create_task(listen())
    await asyncio.sleep(0)
    assert await built.handle("ProjectionApplied", {"network_id": NET_A, "service_id": "x"}) is True
    await asyncio.wait_for(task, 1)

    [(network, scope)] = query.built
    assert network == NET_A and scope.kind is ScopeKind.NETWORK and scope.value == NET_A
    keys = cache.keys()
    assert keys and all(NET_A in key for key in keys)
    assert current_scope_or_none() is None
    message = json.loads(received[0])
    assert set(message) == {"type", "at"}
    assert message["type"] == NETWORK_BOARD_CHANGED


async def test_two_networks_never_share_a_key_or_a_channel() -> None:
    built, _, _, cache = projector()
    await built.handle("MemberAdded", {"network_id": NET_A})
    await built.handle("MemberAdded", {"network_id": NET_B})
    keys = cache.keys()
    assert len(keys) == 2
    assert {NET_A in key for key in keys} == {NET_B in key for key in keys} == {True, False}


@pytest.mark.parametrize("network_id", [None, "", "tenant-a", "net-", 7, "net-bad id"])
async def test_a_payload_without_a_valid_network_id_builds_nothing(network_id: Any) -> None:
    built, query, _, cache = projector()
    with pytest.raises(ValidationFailed):
        await built.handle("GrantEnded", {"network_id": network_id})
    assert query.built == [] and cache.keys() == frozenset()


async def test_a_network_the_registry_does_not_know_is_raised_not_cached() -> None:
    built, query, _, cache = projector()
    query.error = NotFound("the network was not found")
    with pytest.raises(NotFound):
        await built.handle("GrantEnded", {"network_id": NET_A})
    assert cache.keys() == frozenset()


async def test_an_applied_projection_rebuilds_its_network_and_a_rejected_one_does_not() -> None:
    built, query, _, _ = projector()
    await built.applied(ProjectionApplied(NET_A, "tenant-b", GrantScope.CAPACITY, "svc-1", 3, AT))
    await built.rejected(
        ProjectionRejected(
            NET_B, "tenant-b", GrantScope.CAPACITY, ProjectionRejectReason.GRANT_NOT_EFFECTIVE, AT
        )
    )
    assert [network for network, _ in query.built] == [NET_A]


# the read


async def test_a_read_asks_the_registry_about_the_viewer_every_time_even_when_cached() -> None:
    built, query, access, _ = projector()
    await built.handle("MemberAdded", {"network_id": NET_A})
    first = await built.get_board(staff(), NET_A)
    second = await built.get_board(staff(), NET_A)
    assert first == second == view(NET_A)
    assert len(query.built) == 1  # both reads came from the cache
    assert access.asked == [("tenant-b", NET_A), ("tenant-b", NET_A)]


async def test_a_member_who_left_is_refused_although_the_board_is_cached() -> None:
    built, query, access, _ = projector()
    await built.handle("MemberAdded", {"network_id": NET_A})
    access.members.clear()
    with pytest.raises(NotFound):
        await built.get_board(staff(), NET_A)
    assert len(query.built) == 1


async def test_a_miss_builds_and_stores_the_board_for_the_backstop_time() -> None:
    built, query, _, cache = projector()
    assert await built.get_board(staff(), NET_A) == view(NET_A)
    assert len(query.built) == 1 and cache.keys()
    assert await built.get_board(staff(), NET_A) == view(NET_A)
    assert len(query.built) == 1


async def test_a_cache_that_cannot_be_read_or_written_falls_back_to_the_query() -> None:
    clock = FixedClock(AT)
    built, query, _, _ = projector(cache=_BrokenCache(clock, read=True, write=True))
    assert await built.get_board(staff(), NET_A) == view(NET_A)
    assert len(query.built) == 1


async def test_a_cached_value_that_is_not_a_board_is_rebuilt() -> None:
    built, query, _, cache = projector()
    with bind_network(NET_A):
        await cache.set(NETWORK_BOARD_CACHE_KEY, "not json")
    assert await built.get_board(staff(), NET_A) == view(NET_A)
    assert len(query.built) == 1


async def test_a_non_member_reads_nothing_and_stores_nothing() -> None:
    built, query, _, cache = projector()
    with pytest.raises(NotFound):
        await built.get_board(staff("tenant-z"), NET_A)
    assert query.built == [] and cache.keys() == frozenset()
