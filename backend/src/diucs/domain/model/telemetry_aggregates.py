"""The daily telemetry aggregate rows (O08, docs/spec/fhir-data-model.md "Platform nodes").

Plain values: no person, no session id, no field value, no page text, no query text. A row is
what the daily job writes and what the read side reads back. Domain rules
(domain/rules/telemetry_insights.py) turn them into figures; the Neo4j adapter stores them.
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class FunnelDailyRow:
    day: date
    funnel: str
    step: str
    role: str
    channel: str
    device: str
    entered: int
    completed: int
    median_ms: float | None
    branch: bool = False


@dataclass(frozen=True, slots=True)
class FrictionDailyRow:
    day: date
    element_id: str
    kind: str
    role: str
    device: str
    interactions: int
    events: int
    sessions: int


@dataclass(frozen=True, slots=True)
class ElementUsageDailyRow:
    day: date
    element_id: str
    role: str
    device: str
    interactions: int
    sessions: int


@dataclass(frozen=True, slots=True)
class RouteDailyRow:
    day: date
    route: str
    role: str
    device: str
    p50: float | None
    p75: float | None
    p95: float | None
    lcp75: float | None
    inp75: float | None
    cls75: float | None
    errors: int
    sessions: int


@dataclass(frozen=True, slots=True)
class QueryStatDailyRow:
    day: date
    query_id: str
    calls: int
    p50: float | None
    p95: float | None
    errors: int


@dataclass(frozen=True, slots=True)
class DayAggregates:
    """One day's rows for the bound tenant, as the telemetry store summarises them."""

    funnel: tuple[FunnelDailyRow, ...] = field(default=())
    friction: tuple[FrictionDailyRow, ...] = field(default=())
    usage: tuple[ElementUsageDailyRow, ...] = field(default=())
    routes: tuple[RouteDailyRow, ...] = field(default=())
    queries: tuple[QueryStatDailyRow, ...] = field(default=())
