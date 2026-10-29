"""Support console rules (R18). Stub for the red commit."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from diucs.application.ports.outbound.telemetry_query import TimelineKind

ALLOWED_EVENT_KEYS: Final[frozenset[str]] = frozenset()
EVENT_FILTERS: Final[Mapping[str, frozenset[TimelineKind]]] = {}


def public_event(
    *,
    kind: TimelineKind,
    name: str,
    at: datetime,
    start: datetime,
    duration_ms: float | None,
    status: str | None,
    attributes: Mapping[str, Any],
) -> dict[str, Any]:
    return {}


def standout_events(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return []
