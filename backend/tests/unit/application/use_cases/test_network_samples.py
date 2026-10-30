"""Samples of the network board, filed by the projector (TEN-082, DEC-132 item 4).

A board that is built (a rebuild after an event, or a read that found nothing cached) is filed as
the sample of its hour, in a unit of work bound to the network scope. A board served from the cache
files nothing. A sample that cannot be written never fails the board: it is logged by the class of
the error and nothing else.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeKind, bind_network, current_scope_or_none
from diucs.application.use_cases.network_board_projector import NetworkBoardProjector
from diucs.application.use_cases.network_samples import RecordNetworkSample
from diucs.application.use_cases.query_network_board import NetworkBoardView
from diucs.domain.codes import Role, Status
from diucs.domain.rules.network_sample import NetworkSample
from tests.support.network_board_samples import BOARD_AT, board_entry, board_of

NET = "net-pilot"


def _view() -> NetworkBoardView:
    board = board_of(
        board_entry("a", "North", Status.ACCEPTING),
        board_entry("b", "South", Status.LIMITED),
        board_entry("c", "East", Status.OVER_CAPACITY),
    )
    return NetworkBoardView(board, "Capacity board", "Urgent pathway", "Europe/London")


class _Query:
    def __init__(self) -> None:
        self.builds = 0

    async def build(self, network_id: str) -> NetworkBoardView:
        self.builds += 1
        return _view()


class _Access:
    async def require_member(self, actor: Actor, network_id: str) -> None:
        return None


class _Recorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.recorded: list[tuple[str, NetworkBoardView, Any]] = []
        self.error = error

    async def record(self, network_id: str, view: NetworkBoardView) -> None:
        if self.error is not None:
            raise self.error
        self.recorded.append((network_id, view, current_scope_or_none()))


def _projector(recorder: _Recorder | None) -> tuple[NetworkBoardProjector, _Query]:
    clock = FixedClock(BOARD_AT)
    query = _Query()
    built = NetworkBoardProjector(
        query,  # type: ignore[arg-type]
        _Access(),  # type: ignore[arg-type]
        InMemoryCache(clock),
        clock,
        recorder,
    )
    return built, query


def _viewer() -> Actor:
    return Actor(Role.ADVISOR, "prac-1", None, "web", frozenset(), "tenant-b")


async def test_a_rebuild_files_the_board_in_the_network_scope() -> None:
    recorder = _Recorder()
    projector, _ = _projector(recorder)
    await projector.handle("MemberAdded", {"network_id": NET})
    assert len(recorder.recorded) == 1
    network, _, scope = recorder.recorded[0]
    assert network == NET
    assert scope is not None and scope.kind is ScopeKind.NETWORK and scope.value == NET


async def test_a_read_that_builds_files_the_board_and_a_cached_read_does_not() -> None:
    recorder = _Recorder()
    projector, query = _projector(recorder)
    await projector.get_board(_viewer(), NET)
    await projector.get_board(_viewer(), NET)
    assert query.builds == 1
    assert len(recorder.recorded) == 1


async def test_a_wall_read_that_builds_is_filed_the_same() -> None:
    recorder = _Recorder()
    clock = FixedClock(BOARD_AT)

    class _WallAccess(_Access):
        async def require_wall(self, actor: Actor) -> Any:
            class _Member:
                class network:  # noqa: N801
                    id = NET

            return _Member()

    projector = NetworkBoardProjector(
        _Query(),  # type: ignore[arg-type]
        _WallAccess(),  # type: ignore[arg-type]
        InMemoryCache(clock),
        clock,
        recorder,
    )
    wall = Actor(Role.WALL, None, "screen-1", "api", frozenset(), "tenant-b")
    await projector.get_wall_board(wall)
    assert len(recorder.recorded) == 1


async def test_a_projector_with_no_recorder_still_serves_the_board() -> None:
    projector, query = _projector(None)
    view = await projector.get_board(_viewer(), NET)
    assert len(view.board.entries) == 3 and query.builds == 1


async def test_a_sample_that_cannot_be_written_never_fails_the_board_and_logs_the_class_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = _Recorder(RuntimeError("secret-value-123 in the failure"))
    projector, _ = _projector(recorder)
    with caplog.at_level(logging.WARNING):
        view = await projector.get_board(_viewer(), NET)
        await projector.handle("GrantEnded", {"network_id": NET})
    assert len(view.board.entries) == 3
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged
    assert "secret-value-123" not in logged


# ---- the recorder over a unit of work


class _Samples:
    def __init__(self) -> None:
        self.recorded: list[NetworkSample] = []

    async def record(self, sample: NetworkSample) -> bool:
        self.recorded.append(sample)
        return True


class _Uow:
    def __init__(self, samples: _Samples) -> None:
        self.network_samples = samples
        self.committed = False
        self.scope = current_scope_or_none()

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


async def test_the_recorder_files_the_sample_of_the_boards_hour_and_commits() -> None:
    samples = _Samples()
    uows: list[_Uow] = []

    def factory() -> _Uow:
        uows.append(_Uow(samples))
        return uows[-1]

    await RecordNetworkSample(factory).record(NET, _view())  # type: ignore[arg-type]
    assert len(samples.recorded) == 1
    sample = samples.recorded[0]
    assert sample.hour == datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
    assert sample.organisations == 3
    assert uows[0].committed is True
    assert uows[0].scope is not None and uows[0].scope.kind is ScopeKind.NETWORK


async def test_the_recorder_binds_the_network_it_was_given_and_nothing_else() -> None:
    seen: list[Any] = []

    def factory() -> _Uow:
        unit = _Uow(_Samples())
        seen.append(unit.scope)
        return unit

    with bind_network("net-other"):
        await RecordNetworkSample(factory).record(NET, _view())  # type: ignore[arg-type]
    assert seen[0] is not None and seen[0].value == NET
