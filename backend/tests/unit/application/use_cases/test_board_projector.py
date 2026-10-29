"""Pure tests for the board's cache encoding (U09). No Neo4j, no clock, no cache."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.board_projector import (
    BoardProjector,
    board_from_dict,
    board_to_dict,
)
from diucs.application.use_cases.query_board import Board, BoardEntry, QueryBoardQuery
from diucs.domain.codes import Role, ServiceCategory, Status
from diucs.domain.rules.pressure import Pressure

AT = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)


def _every_status_board() -> Board:
    categories = list(ServiceCategory)
    entries = tuple(
        BoardEntry(
            service_id=f"svc-sample-{index}",
            name=f"Sample service {index}",
            category=categories[index % len(categories)],
            status=status,
            effective_available=None if index % 2 else 3,
            over_by=None if index % 3 else 1,
            used=None if index % 2 else 5,
            established=8,
            pending=index,
            unit_label="referrals",
            comment="Sample comment",
            reported_at=None if index % 2 else AT - timedelta(minutes=9),
            next_due_at=AT + timedelta(hours=2),
            was_due_at=None if index % 4 else AT - timedelta(hours=1),
        )
        for index, status in enumerate(Status)
    )
    return Board(
        entries=entries, pressure=Pressure.WATCH, all_limited_or_worse=False, generated_at=AT
    )


def test_a_board_with_every_status_survives_the_cache_encoding() -> None:
    board = _every_status_board()

    encoded: Any = json.loads(json.dumps(board_to_dict(board)))

    assert board_from_dict(encoded) == board


def test_the_encoding_uses_iso_times_and_plain_string_codes() -> None:
    encoded = board_to_dict(_every_status_board())

    assert encoded["generated_at"] == AT.isoformat()
    first = encoded["entries"][0]
    assert type(first["status"]) is str
    assert type(first["category"]) is str
    assert type(encoded["pressure"]) is str


class _RecordingQueryBoard:
    def __init__(self) -> None:
        self.queries: list[QueryBoardQuery] = []

    async def execute(self, query: QueryBoardQuery) -> Board:
        self.queries.append(query)
        return _every_status_board()


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("tenant", ["tenant-a", "tenant-b"])
async def test_the_projector_reads_the_board_as_the_wall_of_the_bound_tenant(tenant: str) -> None:
    query_board = _RecordingQueryBoard()
    projector = BoardProjector(
        query_board,  # type: ignore[arg-type]
        InMemoryCache(FixedClock(AT)),
        FixedClock(AT),
    )

    with bind_tenant(tenant):
        assert await projector.handle("StatusChanged", {"service_id": "svc-1"}) is True

    (query,) = query_board.queries
    assert query.actor.role is Role.WALL
    assert query.actor.practitioner_id is None
    assert query.actor.tenant_id == tenant
