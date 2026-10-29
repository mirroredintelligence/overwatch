"""Telemetry aggregates: the funnels, the suppression floor and the friction rate (O08). Stub for the red commit."""

from dataclasses import dataclass
from datetime import date
from typing import Final

SUPPRESS_BELOW_SESSIONS: Final = 0
FRICTION_REVIEW_RATE: Final = 0.0
RATE_WINDOW_DAYS: Final = 0


@dataclass(frozen=True, slots=True)
class FunnelStep:
    step: str
    event: str
    branch: bool = False


FUNNELS: dict[str, tuple[FunnelStep, ...]] = {}


def is_suppressed(sessions: int) -> bool:
    return False


def friction_rate(events: int, interactions: int) -> float | None:
    return None


def for_review(events: int, interactions: int) -> bool:
    return False


def rate_window_start(end: date) -> date:
    return end
