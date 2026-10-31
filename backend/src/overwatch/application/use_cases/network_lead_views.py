"""What a shift lead (and every other staff role that sees a network) reads of a network beyond the
board: "System now" and the phones of the services in it (TEN-082 and the network variants of W17
and W43, DEC-136 items 1, 9 and 14, DEC-546).

Both are derived from what the member routes already read, so no new Cypher is added and nothing
that is not already on the network board or in the network directory can appear:

- `QuerySystemNow`: the counts of the network board by status, the number of services and of
  organisations shown, the pressure and the network pressure alert. The alert is a state read from
  the same board (DEC-136 item 9: alerts are not driven by network events, so there is no task, no
  push and no write in any tenant): it is raised while the pressure is HIGH, with the platform's
  default thresholds (DEC-546 item 3; a network's own thresholds are a later decision). It carries
  the count and the two thresholds so a page can say why.
- `QueryPhones`: one row per service in the network, with the organisation, the service, its status
  (or none: Phone to confirm) and the service line the organisation chose to share (DEC-134 item 8:
  phoning is the only action on a network row). Never a reporter's number, a cover or a move: those
  are the tenant's own people and are not in any projection. The moves of U38 have no network
  variant.

The viewer is checked by the use cases they read through (`NetworkAccess.require_member`: a role
outside `NETWORK_VIEW_ROLES`, a tenant that is not an active member and an unknown network are the
one refusal). No result names a tenant, a grant or a member's own service id.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.use_cases.network_board_projector import NetworkBoardProjector
from diucs.application.use_cases.query_network_directory import QueryNetworkDirectory
from diucs.domain.codes import ServiceCategory, Status
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.network_board import NetworkBoardEntry
from diucs.domain.rules.pressure import Pressure, limited_or_worse_count

UNAVAILABLE_KEY: Final = "unavailable"
"""The key of the rows with no status: a paused listing, shown by name only."""
STATUS_KEYS: Final[tuple[str, ...]] = (*(status.value for status in Status), UNAVAILABLE_KEY)
"""Every key of `by_status`, in the order the board's badges use, so a page never meets a missing
count and a test pins the set."""


@dataclass(frozen=True, slots=True)
class NetworkPressureAlert:
    """The network pressure alert as a state. `raised` while the pressure is HIGH.
    `limited_or_worse` counts the services that are limited, not accepting or over capacity,
    against `watch_from` and `high_from` (the platform's default thresholds)."""

    raised: bool
    level: Pressure
    limited_or_worse: int
    watch_from: int
    high_from: int


@dataclass(frozen=True, slots=True)
class NetworkSystemNow:
    generated_at: datetime
    services: int
    organisations: int
    by_status: Mapping[str, int]
    pressure: Pressure
    all_limited_or_worse: bool
    alert: NetworkPressureAlert
    system_name: str
    pathway_name: str
    time_zone: str


@dataclass(frozen=True, slots=True)
class NetworkPhone:
    row_ref: str
    organisation_name: str
    service_name: str
    category: ServiceCategory
    presentation: ListingPresentation
    status: Status | None
    stale_warning: bool
    reported_at: datetime | None
    contact_label: str | None
    contact_phone: str | None


@dataclass(frozen=True, slots=True)
class NetworkPhones:
    phones: tuple[NetworkPhone, ...]
    organisations: int
    system_name: str
    pathway_name: str
    time_zone: str


def status_counts(entries: tuple[NetworkBoardEntry, ...]) -> dict[str, int]:
    """The number of rows per status key, every key present."""
    counts = dict.fromkeys(STATUS_KEYS, 0)
    for entry in entries:
        counts[UNAVAILABLE_KEY if entry.status is None else entry.status.value] += 1
    return counts


class QuerySystemNow:
    def __init__(self, projector: NetworkBoardProjector) -> None:
        self._projector = projector

    async def execute(self, actor: Actor, network_id: str) -> NetworkSystemNow:
        view = await self._projector.get_board(actor, network_id)
        board = view.board
        counted = limited_or_worse_count(e.status for e in board.entries if e.status is not None)
        return NetworkSystemNow(
            generated_at=board.generated_at,
            services=len(board.entries),
            organisations=len({entry.organisation_name for entry in board.entries}),
            by_status=status_counts(board.entries),
            pressure=board.pressure,
            all_limited_or_worse=board.all_limited_or_worse,
            alert=NetworkPressureAlert(
                raised=board.pressure is Pressure.HIGH,
                level=board.pressure,
                limited_or_worse=counted,
                watch_from=DEFAULT_POLICY.pressure_watch_from,
                high_from=DEFAULT_POLICY.pressure_high_from,
            ),
            system_name=view.system_name,
            pathway_name=view.pathway_name,
            time_zone=view.time_zone,
        )


class QueryPhones:
    def __init__(self, projector: NetworkBoardProjector, directory: QueryNetworkDirectory) -> None:
        self._projector = projector
        self._directory = directory

    async def execute(self, actor: Actor, network_id: str) -> NetworkPhones:
        board = await self._projector.get_board(actor, network_id)
        listed = await self._directory.execute(actor, network_id)
        rows = {entry.row_ref: entry for entry in board.board.entries}
        phones: list[NetworkPhone] = []
        for entry in listed.entries:
            row = rows.get(entry.row_ref)
            phones.append(
                NetworkPhone(
                    row_ref=entry.row_ref,
                    organisation_name=entry.organisation_name,
                    service_name=entry.service_name,
                    category=entry.category,
                    presentation=entry.presentation,
                    status=None if row is None else row.status,
                    stale_warning=False if row is None else row.stale_warning,
                    reported_at=None if row is None else row.reported_at,
                    contact_label=entry.contact_label,
                    contact_phone=entry.contact_phone,
                )
            )
        return NetworkPhones(
            phones=tuple(phones),
            organisations=len({phone.organisation_name for phone in phones}),
            system_name=listed.system_name,
            pathway_name=listed.pathway_name,
            time_zone=listed.time_zone,
        )
