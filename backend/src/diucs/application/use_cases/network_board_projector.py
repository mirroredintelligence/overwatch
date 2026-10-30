"""The network board projector: the cached network board and the "board changed" message
(TEN-058, DEC-547, DEC-132 item 4). The network variant of `BoardProjector` (U09).

When what a network's board shows changes (a projection applied, a grant effective or ended, a
member added or removed) the projector rebuilds the board with `QueryNetworkBoard.build`, stores it
in the cache and publishes a small message on the network's channel so open pages refetch. The
message carries the type and the time, never a figure, a service or a tenant: a missed message is
harmless because a page refetches on connect and on a timer.

Scope. The work runs in the network scope: the cache qualifies the key and the channel by it
(`_net-<id>`), so a network's board never reaches another network's cache or stream and a tenant's
cache never holds a network's. `handle` takes the network from the event's payload, validates it as
a network id, and binds it for the rebuild; the registry then confirms the network exists and is
active (NotFound otherwise, nothing cached).

Reads. `get_board` asks the registry about the viewer on every call, cached or not, so a member who
left, or whose network was suspended, is refused at once and the cache never answers for them. The
cache is not a store of record: a read or a write that fails falls back to a rebuild and never
raises from `get_board`. A cached board was assembled at the time of its rebuild, so its status can
be up to the backstop time old (60 s); a board that is no longer cached is assembled at the time of
the read.

The `ProjectionNotifier` the apply step calls after it has committed is this class: `applied`
rebuilds the network of the projection; `rejected` changes nothing and does nothing. The cache key
does not depend on the caller's role (every role that may read a network board sees the same one).
"""

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.cache import NETWORK_BOARD_UPDATES_CHANNEL, Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.query_network_board import NetworkBoardView, QueryNetworkBoard
from diucs.domain.codes import ServiceCategory, Status
from diucs.domain.errors import ValidationFailed
from diucs.domain.events import ProjectionApplied, ProjectionRejected
from diucs.domain.model.network import DirectorySource, check_network_id
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.network_board import NetworkBoard, NetworkBoardEntry
from diucs.domain.rules.pressure import Pressure


class NetworkBoardAudience(StrEnum):
    """Who a cached network board is for. Every role that may read it sees the same board, so
    there is one audience; a view that differs by role adds a member here, and so its own key."""

    ALL = "all"


def network_board_cache_key(audience: NetworkBoardAudience) -> str:
    """The logical cache name of the network board for an audience: `network-board:v1:<audience>`.
    An audience that is not exactly a member of the enum is refused."""
    if type(audience) is not NetworkBoardAudience:
        raise ValidationFailed("audience", "is not a network board audience")
    return f"network-board:v1:{audience.value}"


NETWORK_BOARD_CACHE_KEY = network_board_cache_key(NetworkBoardAudience.ALL)
NETWORK_BOARD_CACHE_TTL = timedelta(seconds=60)
NETWORK_BOARD_CHANGED = "network-board-changed"
NETWORK_REBUILD_EVENTS = frozenset(
    {"ProjectionApplied", "GrantEffective", "GrantEnded", "MemberAdded", "MemberRemoved"}
)

_LOG = logging.getLogger(__name__)


def _utc_text(at: datetime) -> str:
    return at.astimezone(UTC).isoformat()


def _optional_utc_text(at: datetime | None) -> str | None:
    return None if at is None else _utc_text(at)


def _optional_time(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def _entry_to_dict(entry: NetworkBoardEntry) -> dict[str, Any]:
    return {
        "row_ref": entry.row_ref,
        "organisation_name": entry.organisation_name,
        "service_name": entry.service_name,
        "category": entry.category.value,
        "presentation": entry.presentation.value,
        "status": None if entry.status is None else entry.status.value,
        "unit_label": entry.unit_label,
        "effective_available": entry.effective_available,
        "over_by": entry.over_by,
        "used": entry.used,
        "established": entry.established,
        "reported_at": _optional_utc_text(entry.reported_at),
        "stale_warning": entry.stale_warning,
        "was_due_at": _optional_utc_text(entry.was_due_at),
        "source": entry.source.value,
    }


def _entry_from_dict(data: Mapping[str, Any]) -> NetworkBoardEntry:
    status = data["status"]
    return NetworkBoardEntry(
        row_ref=str(data["row_ref"]),
        organisation_name=str(data["organisation_name"]),
        service_name=str(data["service_name"]),
        category=ServiceCategory(data["category"]),
        presentation=ListingPresentation(data["presentation"]),
        status=None if status is None else Status(status),
        unit_label=data["unit_label"],
        effective_available=data["effective_available"],
        over_by=data["over_by"],
        used=data["used"],
        established=data["established"],
        reported_at=_optional_time(data["reported_at"]),
        stale_warning=bool(data["stale_warning"]),
        was_due_at=_optional_time(data["was_due_at"]),
        source=DirectorySource(data["source"]),
    )


def network_board_to_dict(view: NetworkBoardView) -> dict[str, Any]:
    """The board and its labels as plain JSON-ready values: ISO 8601 UTC times, enums as strings.
    It holds no tenant, no grant and no source service id (the board has none to hold)."""
    return {
        "entries": [_entry_to_dict(entry) for entry in view.board.entries],
        "pressure": view.board.pressure.value,
        "all_limited_or_worse": view.board.all_limited_or_worse,
        "generated_at": _utc_text(view.board.generated_at),
        "system_name": view.system_name,
        "pathway_name": view.pathway_name,
        "time_zone": view.time_zone,
    }


def network_board_from_dict(data: Mapping[str, Any]) -> NetworkBoardView:
    """Rebuild a board from `network_board_to_dict`'s output. Raises on a value that is not one."""
    board = NetworkBoard(
        entries=tuple(_entry_from_dict(item) for item in data["entries"]),
        pressure=Pressure(data["pressure"]),
        all_limited_or_worse=bool(data["all_limited_or_worse"]),
        generated_at=datetime.fromisoformat(data["generated_at"]),
    )
    return NetworkBoardView(
        board, str(data["system_name"]), str(data["pathway_name"]), str(data["time_zone"])
    )


class NetworkBoardProjector:
    def __init__(
        self, query: QueryNetworkBoard, access: NetworkAccess, cache: Cache, clock: Clock
    ) -> None:
        self._query = query
        self._access = access
        self._cache = cache
        self._clock = clock

    async def handle(self, event_type: str, payload: Mapping[str, Any]) -> bool:
        """Rebuild and publish for an event the board shows. Return False for any other event."""
        if event_type not in NETWORK_REBUILD_EVENTS:
            return False
        network_id = check_network_id(payload.get("network_id"), "network_id")
        await self._rebuild(network_id)
        return True

    async def applied(self, event: ProjectionApplied) -> None:
        await self._rebuild(event.network_id)

    async def rejected(self, event: ProjectionRejected) -> None:
        """A rejection changes nothing the board shows."""

    async def _rebuild(self, network_id: str) -> None:
        with bind_network(network_id):
            view = await self._query.build(network_id)
            # Store before publishing: a page that refetches on the message must find the new board.
            await self._cache.set(
                NETWORK_BOARD_CACHE_KEY,
                json.dumps(network_board_to_dict(view)),
                NETWORK_BOARD_CACHE_TTL,
            )
            message = {"type": NETWORK_BOARD_CHANGED, "at": _utc_text(self._clock.now())}
            await self._cache.publish(NETWORK_BOARD_UPDATES_CHANNEL, json.dumps(message))

    async def get_board(self, actor: Actor, network_id: str) -> NetworkBoardView:
        """The cached board, or a computed one that is then cached for the backstop time, for a
        viewer the registry has just confirmed (NotFound or NotAllowed otherwise)."""
        await self._access.require_member(actor, network_id)
        return await self._serve(network_id)

    async def get_wall_board(self, actor: Actor) -> NetworkBoardView:
        """The board of the network a wall screen is set to (TEN-067): the screen's own record
        names it and the registry confirms the membership, on every call, cached or not. A screen
        set to its own board, a revoked one and one whose tenant left are NotFound."""
        member = await self._access.require_wall(actor)
        return await self._serve(member.network.id)

    async def _serve(self, network_id: str) -> NetworkBoardView:
        with bind_network(network_id):
            cached = await self._read_cached()
            if cached is not None:
                return cached
            view = await self._query.build(network_id)
            await self._store_best_effort(view)
            return view

    async def _read_cached(self) -> NetworkBoardView | None:
        try:
            text = await self._cache.get(NETWORK_BOARD_CACHE_KEY)
            if text is None:
                return None
            return network_board_from_dict(json.loads(text))
        except Exception as error:
            _LOG.warning("network board cache read failed: %s", type(error).__name__)
            return None

    async def _store_best_effort(self, view: NetworkBoardView) -> None:
        try:
            await self._cache.set(
                NETWORK_BOARD_CACHE_KEY,
                json.dumps(network_board_to_dict(view)),
                NETWORK_BOARD_CACHE_TTL,
            )
        except Exception as error:
            _LOG.warning("network board cache write failed: %s", type(error).__name__)
