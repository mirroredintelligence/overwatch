"""Pure tests for the board's cache encoding (U09). No Neo4j, no clock, no cache."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from diucs.application.use_cases.board_projector import WALL_ACTOR, board_from_dict, board_to_dict
from diucs.application.use_cases.query_board import Board, BoardEntry
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


def test_the_system_actor_is_the_wall_role() -> None:
    assert WALL_ACTOR.role is Role.WALL
    assert WALL_ACTOR.practitioner_id is None
