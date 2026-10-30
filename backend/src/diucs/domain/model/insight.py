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
