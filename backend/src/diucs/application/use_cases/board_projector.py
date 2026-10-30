"""Board projector: the cached wall board and the "board changed" message (U09).

When a capacity, booking or criteria event arrives, the projector rebuilds the board from Neo4j
through QueryBoard, stores it in the cache under one key, and publishes a small message on
`board.updates` so open pages refetch. The message carries the service id and the time, never a
figure: a missed message is harmless because the page refetches on connect and on a timer.

Rules: the cache is not a store of record. A read or a store that fails falls back to QueryBoard
and never raises from get_board (architecture.md, Platform decisions). A failed publish is raised
from handle, so the consumer can retry: rebuilding is idempotent. The anonymous link is refused
before the cache is read, so the cache cannot serve it a board (QueryBoard refuses it too).

The cache key does not depend on the caller's role. Every role that may read the board sees the
same board today (`BoardAudience.ALL`). Any role-specific filter added to QueryBoard needs its own
audience and key.

Tenancy (TEN-039): the board, its cache key and the "board changed" channel belong to the scope
the work is bound to. The projector takes no tenant: a rebuild runs in the scope the consumer bound
from the message (`workers/board_consumer.py`), reads the board as that tenant's wall actor, and the
cache qualifies the key and the channel by the same scope. `get_board` refuses an actor of another
tenant, a network scope and no scope.
"""

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from diucs.application.actor import Actor, require_actor_in_bound_tenant, wall_actor
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL, Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.tenancy import current_tenant
from diucs.application.use_cases.query_board import Board, BoardEntry, QueryBoard, QueryBoardQuery
from diucs.domain.codes import Role, ServiceCategory, Status
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.rules.pressure import Pressure


class BoardAudience(StrEnum):
    """Who a cached board is for. Today every role that may read the board sees the same board
    (DEC-099 item 7), so there is one audience. A view that differs by role, service or flag adds a
    member here, and so its own key (L130); the cache qualifies every key by the bound scope
    (TEN-019), so a key never crosses tenants whatever the audience."""

    ALL = "all"


def board_cache_key(audience: BoardAudience) -> str:
    """The logical cache name of the board for an audience: `board:v1:<audience>`. An audience that
    is not exactly a member of the enum is refused (a plain string would be a key no test pins)."""
    if type(audience) is not BoardAudience:
        raise ValidationFailed("audience", "is not a board audience")
    return f"board:v1:{audience.value}"


BOARD_CACHE_KEY = board_cache_key(BoardAudience.ALL)

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

_LOG = logging.getLogger(__name__)


def _utc_text(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def _optional_utc_text(at: datetime | None) -> str | None:
    return None if at is None else _utc_text(at)


def _optional_time(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def _entry_to_dict(entry: BoardEntry) -> dict[str, Any]:
    return {
        "service_id": entry.service_id,
        "name": entry.name,
        "category": entry.category.value,
        "status": entry.status.value,
        "effective_available": entry.effective_available,
        "over_by": entry.over_by,
        "used": entry.used,
        "established": entry.established,
        "pending": entry.pending,
        "unit_label": entry.unit_label,
        "comment": entry.comment,
        "reported_at": _optional_utc_text(entry.reported_at),
        "next_due_at": _optional_utc_text(entry.next_due_at),
        "was_due_at": _optional_utc_text(entry.was_due_at),
    }


def _entry_from_dict(data: Mapping[str, Any]) -> BoardEntry:
    return BoardEntry(
        service_id=str(data["service_id"]),
        name=str(data["name"]),
        category=ServiceCategory(data["category"]),
        status=Status(data["status"]),
        effective_available=data["effective_available"],
        over_by=data["over_by"],
        used=data["used"],
        established=int(data["established"]),
        pending=int(data["pending"]),
        unit_label=str(data["unit_label"]),
        comment=str(data["comment"]),
        reported_at=_optional_time(data["reported_at"]),
        next_due_at=_optional_time(data["next_due_at"]),
        was_due_at=_optional_time(data["was_due_at"]),
    )


def board_to_dict(board: Board) -> dict[str, Any]:
    """The board as plain JSON-ready values: ISO 8601 UTC times, enum values as strings."""
    return {
        "entries": [_entry_to_dict(entry) for entry in board.entries],
        "pressure": board.pressure.value,
        "all_limited_or_worse": board.all_limited_or_worse,
        "generated_at": _utc_text(board.generated_at),
    }


def board_from_dict(data: Mapping[str, Any]) -> Board:
    """Rebuild a board from board_to_dict's output. Raises on a value that is not a board."""
    return Board(
        entries=tuple(_entry_from_dict(item) for item in data["entries"]),
        pressure=Pressure(data["pressure"]),
        all_limited_or_worse=bool(data["all_limited_or_worse"]),
        generated_at=datetime.fromisoformat(data["generated_at"]),
    )


class BoardProjector:
    def __init__(self, query_board: QueryBoard, cache: Cache, clock: Clock) -> None:
        self._query_board = query_board
        self._cache = cache
        self._clock = clock

    async def handle(self, event_type: str, payload: Mapping[str, Any]) -> bool:
        """Rebuild and publish for an event the board shows. Return False for any other event."""
        if event_type not in REBUILD_EVENTS:
            return False
        board = await self._query_board.execute(QueryBoardQuery(actor=wall_actor(current_tenant())))
        # Store before publishing: a page that refetches on the message must find the new board.
        await self._cache.set(BOARD_CACHE_KEY, json.dumps(board_to_dict(board)), BOARD_CACHE_TTL)
        service_id = payload.get("service_id")
        message = {
            "type": BOARD_CHANGED,
            "service_id": service_id if isinstance(service_id, str) else None,
            "at": _utc_text(self._clock.now()),
        }
        await self._cache.publish(BOARD_UPDATES_CHANNEL, json.dumps(message))
        return True

    async def get_board(self, actor: Actor) -> Board:
        """The cached board, or a computed one that is then cached for the backstop time."""
        if actor.role is Role.ANONYMOUS_LINK:
            raise NotAllowed("the anonymous link cannot read the board")
        # The cache and the board are the bound scope's: an actor of another tenant, a network
        # scope and no scope are wiring faults, refused before anything is read or stored.
        require_actor_in_bound_tenant(actor)
        cached = await self._read_cached()
        if cached is not None:
            return cached
        board = await self._query_board.execute(QueryBoardQuery(actor=actor))
        await self._store_best_effort(board)
        return board

    async def _read_cached(self) -> Board | None:
        try:
            text = await self._cache.get(BOARD_CACHE_KEY)
            if text is None:
                return None
            return board_from_dict(json.loads(text))
        except Exception as error:
            _LOG.warning("board cache read failed: %s", type(error).__name__)
            return None

    async def _store_best_effort(self, board: Board) -> None:
        try:
            await self._cache.set(
                BOARD_CACHE_KEY, json.dumps(board_to_dict(board)), BOARD_CACHE_TTL
            )
        except Exception as error:
            _LOG.warning("board cache write failed: %s", type(error).__name__)
