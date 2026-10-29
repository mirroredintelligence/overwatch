"""Week summary for the COO and ICB (U35). Stub for the red commit (DEC-010)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Measure:
    value: float | int | None
    hidden: bool
    label: str


def london_week(week_start: date) -> tuple[datetime, datetime]:
    raise NotImplementedError


def count_measure(count: int, label: str) -> Measure:
    raise NotImplementedError


def percent_measure(part: int, base: int, label: str) -> Measure:
    raise NotImplementedError


def median_measure(values: Sequence[float], label: str) -> Measure:
    raise NotImplementedError


def on_time_updates(
    prompts: Sequence[tuple[str, datetime]], reports: Sequence[tuple[str, datetime]]
) -> int:
    raise NotImplementedError


def time_back_text(updates: int, minutes_per_call: int | None) -> str:
    raise NotImplementedError


def check_may_read(actor: Any) -> None:
    raise NotImplementedError
