"""The rows the browser-insight counters and the pipeline read keep (W9F).

Plain values: no person, no session id, no field value, no page text. A `MeasureRow` is one day's
histogram of one web vital for one route, device and release; a `ReleaseRow` is one day's counters
for one release; a `PipelineRow` is the tenant's own outbox for one topic, read live.
"""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class MeasureRow:
    day: date
    measure: str
    route: str
    device: str
    release: str
    sessions: int
    samples: int
    buckets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReleaseRow:
    day: date
    release: str
    sessions: int
    interactions: int
    friction: int
    errors: int
    views: int


@dataclass(frozen=True, slots=True)
class PipelineRow:
    topic: str
    active: int
    dead: int
    oldest_pending: datetime | None


# What one batch adds to a day's counters. `sessions` is the number of sessions new to the group
# today (a marker not seen before), `count` the events. The repository adds both to the node.


@dataclass(frozen=True, slots=True)
class UsageAdd:
    element_id: str
    role: str
    device: str
    count: int
    sessions: int


@dataclass(frozen=True, slots=True)
class FrictionAdd:
    element_id: str
    kind: str
    route: str
    role: str
    device: str
    count: int
    sessions: int


@dataclass(frozen=True, slots=True)
class RouteAdd:
    route: str
    role: str
    device: str
    errors: int
    sessions: int


@dataclass(frozen=True, slots=True)
class FunnelAdd:
    funnel: str
    step: str
    role: str
    channel: str
    device: str
    count: int


@dataclass(frozen=True, slots=True)
class MeasureAdd:
    measure: str
    route: str
    device: str
    release: str
    buckets: tuple[int, ...]
    samples: int
    sessions: int


@dataclass(frozen=True, slots=True)
class ReleaseAdd:
    release: str
    interactions: int
    friction: int
    errors: int
    views: int
    sessions: int


@dataclass(frozen=True, slots=True)
class FunnelMark:
    """A session's furthest step so far in one funnel group: `marker` is the pseudonymous key."""

    marker: str
    top: int
