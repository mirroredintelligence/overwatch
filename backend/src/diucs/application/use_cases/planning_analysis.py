"""Planning analysis from decision snapshots (U43). Stub for the red commit (DEC-010)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

MIN_COUNT: Final = 10


@dataclass(frozen=True, slots=True)
class PlanningQuery:
    period_days: int
    need_group: str


@dataclass(frozen=True, slots=True)
class HiddenCount:
    value: int | None
    hidden: bool


@dataclass(frozen=True, slots=True)
class OutcomeFact:
    case_key: str
    opened_at: datetime
    closed_at: datetime
    age_band: str | None
    urgency: str | None
    referrer: str | None
    needs: tuple[str, ...]
    destination_id: str | None


@dataclass(frozen=True, slots=True)
class DisplayFact:
    case_key: str
    at: datetime
    rows: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DeclineFact:
    service_id: str
    at: datetime


@dataclass(frozen=True, slots=True)
class FlowRow:
    best_fit: str
    state: str
    destination: str
    count: HiddenCount


@dataclass(frozen=True, slots=True)
class PlanningResult:
    referrals: HiddenCount
    best_fit_unavailable: HiddenCount
    best_fit_unavailable_pct: HiddenCount
    went_elsewhere: HiddenCount
    flows: tuple[FlowRow, ...]
    heat: dict[tuple[int, str], HiddenCount]
    busiest: tuple[int, str] | None
    declined_despite: tuple[tuple[str, HiddenCount], ...]


def validate_query(query: PlanningQuery) -> None:
    raise NotImplementedError


def in_cohort(fact: OutcomeFact, need_group: str) -> bool:
    raise NotImplementedError


def decision_for(fact: OutcomeFact, displays: Sequence[DisplayFact]) -> DisplayFact | None:
    raise NotImplementedError


def best_fit(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    raise NotImplementedError


def is_unavailable(row: Mapping[str, Any]) -> bool:
    raise NotImplementedError


def hide(count: int) -> HiddenCount:
    raise NotImplementedError


def share_of(part: int, base: int) -> HiddenCount:
    raise NotImplementedError


def heat_cell(opened_at: datetime) -> tuple[int, str]:
    raise NotImplementedError


def build_planning(
    query: PlanningQuery,
    outcomes: Sequence[OutcomeFact],
    displays: Sequence[DisplayFact],
    declines: Sequence[DeclineFact],
    names: Mapping[str, str],
) -> PlanningResult:
    raise NotImplementedError
