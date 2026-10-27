"""Board projector: the cached wall board and the "board changed" message (U09).

Stub for the red commit (DEC-010): constants and signatures only. Behaviour arrives in the green
commit.
"""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.use_cases.query_board import Board, QueryBoard
from diucs.domain.codes import Role

BOARD_CACHE_KEY = "board:v1"
# [ASSUMED] in docs/plan/prompts/U09.md: a 60 s backstop. The rebuild on each event does the work.
BOARD_CACHE_TTL = timedelta(seconds=60)
BOARD_CHANGED = "board-changed"
REBUILD_EVENTS = frozenset(
    {
        "StatusChanged",
        "CapacityReported",
        "BookingRequested",
        "BookingResponded",
        "BookingExpired",
        "CriteriaApproved",
        "PhoneTaskRaised",
    }
)
WALL_ACTOR = Actor(
    role=Role.WALL, practitioner_id=None, device_id=None, channel="system", service_ids=frozenset()
)


def board_to_dict(board: Board) -> dict[str, Any]:
    raise NotImplementedError


def board_from_dict(data: Mapping[str, Any]) -> Board:
    raise NotImplementedError


class BoardProjector:
    def __init__(self, query_board: QueryBoard, cache: Cache, clock: Clock) -> None:
        self._query_board = query_board
        self._cache = cache
        self._clock = clock

    async def handle(self, event_type: str, payload: Mapping[str, Any]) -> bool:
        raise NotImplementedError

    async def get_board(self, actor: Actor) -> Board:
        raise NotImplementedError
