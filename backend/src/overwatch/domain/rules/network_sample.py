"""The hourly sample of a network board, and the week measures made from samples (TEN-082,
DEC-132 item 4, DEC-136 items 9 and 14).

A network keeps no history of reports (a projection is the current row, TEN-053). What a week of the
network can show is therefore taken from what the board showed: each time the network board is
rebuilt, its counts are written into the sample of that hour in the network scope. A sample holds
counts and a pressure level and nothing else: the number of services in each status, the number of
organisations shown, and the pressure. No organisation, service, grant or source tenant is in it, so
no measure made from samples can be broken down by member (DEC-136 item 14: the network owner sees
no per-member breakdown).

Measures are capacity-derived only (bookings, cases and outcomes are not shared, DEC-136 item 1):

- `on_time_pct`: of the services in hours at the sampled times, the share that was not "Not
  updated", that is, whose last report was recent enough to be read as current (the board's own
  freshness rule). It is the network's reading of "capacity updates on time": a network has no
  prompts, so it cannot say a report came inside a reply window.
- `status_share`: the share of the service-readings in each status.
- `pressure_hours`: the hours of the week at each pressure level (the highest level of the hour).
- `pressure_over_time`: the level of each sampled hour.

Small groups are hidden, as in the tenant's week summary (domain-rules 10): a count or a base under
`SMALL_GROUP` is not shown, and a network with fewer than `MIN_ORGANISATIONS` organisations in every
sample is withheld whole, because with fewer a share can be read as one member's own figure
(DEC-136 item 14 asks for at least three).

Pure: no I/O, no clock.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from diucs.domain.codes import Status
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.network_board import NetworkBoard
from diucs.domain.rules.pressure import Pressure

SMALL_GROUP: Final = 10
"""Counts and bases under this are hidden (domain-rules 10, as in the tenant's week summary)."""
MIN_ORGANISATIONS: Final = 3
"""A network with fewer organisations than this in every sample of the week is withheld (DEC-136
item 14: aggregates across at least three tenants)."""
PRESSURE_RANK: Final[dict[Pressure, int]] = {
    Pressure.NORMAL: 0,
    Pressure.WATCH: 1,
    Pressure.HIGH: 2,
}
_BY_RANK: Final = {rank: level for level, rank in PRESSURE_RANK.items()}
_IN_HOURS: Final = (
    Status.ACCEPTING,
    Status.LIMITED,
    Status.NOT_ACCEPTING,
    Status.OVER_CAPACITY,
    Status.NOT_UPDATED,
)
READINGS: Final = (*_IN_HOURS, Status.OUT_OF_HOURS)
"""The statuses a service reading can have. A row with no status (a paused listing, shown by name
only) is not a reading: it has no figure to be current or late."""


def hour_of(at: datetime) -> datetime:
    """The start of the UTC hour that holds `at`. `at` must be timezone-aware."""
    if type(at) is not datetime or at.utcoffset() is None:
        raise ValidationFailed("at", "must be a timezone-aware datetime")
    return at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class NetworkSample:
    """The counts of a network board at one instant, filed under the hour that holds it.
    `pressure` is the level of that board; a stored hour keeps the highest level it saw."""

    hour: datetime
    at: datetime
    counts: tuple[tuple[Status, int], ...]
    unavailable: int
    organisations: int
    pressure: Pressure

    def __post_init__(self) -> None:
        if hour_of(self.hour) != self.hour:
            raise ValidationFailed("hour", "must be the start of an hour")
        if hour_of(self.at) != self.hour:
            raise ValidationFailed("at", "must be inside the hour of the sample")
        if tuple(status for status, _ in self.counts) != READINGS:
            raise ValidationFailed("counts", "must hold every status once, in order")
        numbers = (*(n for _, n in self.counts), self.unavailable, self.organisations)
        if any(type(n) is not int or isinstance(n, bool) or n < 0 for n in numbers):
            raise ValidationFailed("counts", "must be whole numbers, none negative")
        if type(self.pressure) is not Pressure:
            raise ValidationFailed("pressure", "must be a pressure level")

    def count(self, status: Status) -> int:
        return dict(self.counts)[status]

    @property
    def readings(self) -> int:
        return sum(n for _, n in self.counts)


def sample_of(board: NetworkBoard) -> NetworkSample:
    """The sample of a board, taken at its own `generated_at`. Counts come from the rows' statuses
    and from nothing else."""
    tally = dict.fromkeys(READINGS, 0)
    unavailable = 0
    for entry in board.entries:
        if entry.status is None:
            unavailable += 1
        else:
            tally[entry.status] += 1
    return NetworkSample(
        hour=hour_of(board.generated_at),
        at=board.generated_at.astimezone(UTC),
        counts=tuple(tally.items()),
        unavailable=unavailable,
        organisations=len({entry.organisation_name for entry in board.entries}),
        pressure=board.pressure,
    )


def rank_of(pressure: Pressure) -> int:
    return PRESSURE_RANK[pressure]


def level_of(rank: int) -> Pressure:
    """The pressure level of a stored rank, or ValidationFailed for a rank that is not one."""
    if rank not in _BY_RANK:
        raise ValidationFailed("pressure", "is not a stored pressure rank")
    return _BY_RANK[rank]


@dataclass(frozen=True, slots=True)
class WeekMeasure:
    """One figure. A hidden figure carries no value: the page says it is not shown."""

    value: float | int | None
    hidden: bool
    label: str


@dataclass(frozen=True, slots=True)
class NetworkWeek:
    """The measures of one week of a network. When `withheld`, every measure is hidden and the
    series is empty."""

    withheld: bool
    hours_sampled: WeekMeasure
    on_time_pct: WeekMeasure
    status_share: tuple[tuple[Status, WeekMeasure], ...]
    pressure_hours: tuple[tuple[Pressure, WeekMeasure], ...]
    pressure_over_time: tuple[tuple[datetime, Pressure], ...]


def _count(value: int, label: str) -> WeekMeasure:
    if value < SMALL_GROUP:
        return WeekMeasure(None, True, label)
    return WeekMeasure(value, False, label)


def _percent(part: int, base: int, label: str) -> WeekMeasure:
    if base < SMALL_GROUP:
        return WeekMeasure(None, True, label)
    return WeekMeasure(int(100 * part / base + 0.5), False, label)


def _hidden(label: str) -> WeekMeasure:
    return WeekMeasure(None, True, label)


def week_of_samples(
    samples: Sequence[NetworkSample], start: datetime, end: datetime
) -> NetworkWeek:
    """The measures of the samples whose hour is in [start, end). Samples outside the week are
    ignored; two samples of one hour are refused (an hour is one sample)."""
    week = sorted((s for s in samples if start <= s.hour < end), key=lambda s: s.hour)
    if len({s.hour for s in week}) != len(week):
        raise ValidationFailed("samples", "an hour has one sample")
    on_time_label = "capacity updates on time"
    if max((s.organisations for s in week), default=0) < MIN_ORGANISATIONS:
        return NetworkWeek(
            withheld=True,
            hours_sampled=_hidden("hours sampled"),
            on_time_pct=_hidden(on_time_label),
            status_share=tuple((status, _hidden(status.value)) for status in READINGS),
            pressure_hours=tuple((level, _hidden(level.value)) for level in Pressure),
            pressure_over_time=(),
        )
    in_hours = sum(s.count(status) for s in week for status in _IN_HOURS)
    late = sum(s.count(Status.NOT_UPDATED) for s in week)
    readings = sum(s.readings for s in week)
    hours_at = {level: sum(1 for s in week if s.pressure is level) for level in Pressure}
    return NetworkWeek(
        withheld=False,
        hours_sampled=_count(len(week), "hours sampled"),
        on_time_pct=_percent(in_hours - late, in_hours, on_time_label),
        status_share=tuple(
            (status, _percent(sum(s.count(status) for s in week), readings, status.value))
            for status in READINGS
        ),
        pressure_hours=tuple((level, _count(hours_at[level], level.value)) for level in Pressure),
        pressure_over_time=tuple((s.hour, s.pressure) for s in week),
    )
