"""The support console's rules (R18): what a session event may carry, the filter names and which
events stand out. Pure: no I/O, no clock (the caller passes the instants).

A support session is read by engineering and by support staff, and the only fields that leave
the telemetry store are the ones named here: an element id, a route template, an outcome, a
timing, a status and an offset. A field value, a page text or a query text never reaches a
response, because the mapping below builds each event from these keys and no other
(observability.md, "Privacy and governance").
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

ALLOWED_EVENT_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "elementId", "route", "outcome", "durationMs", "status", "offsetMs"}
)

# The timeline kinds (the telemetry port's TimelineKind values): "page_view", "click", "field",
# "api_call", "friction", "error".
TIMELINE_KINDS: Final[frozenset[str]] = frozenset(
    {"page_view", "click", "field", "api_call", "friction", "error"}
)
EVENT_FILTERS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "all": TIMELINE_KINDS,
        "errors": frozenset({"error"}),
        "friction": frozenset({"friction"}),
        "api": frozenset({"api_call"}),
        "navigation": frozenset({"page_view"}),
    }
)

# How many events are highlighted for the reader before the full timeline.
STANDOUT_LIMIT: Final = 5
_STANDOUT_KINDS: Final = frozenset({"friction", "error"})


def public_event(
    *,
    kind: str,
    name: str,
    at: datetime,
    start: datetime,
    duration_ms: float | None,
    status: str | None,
    attributes: Mapping[str, Any],
) -> dict[str, Any]:
    """One timeline event as a response may carry it.

    `name` is not returned: a name can hold a route with a parameter in it, and the route
    template in `route` is the only form that leaves.
    """
    event: dict[str, Any] = {
        "kind": kind,
        "offsetMs": int((at - start).total_seconds() * 1000),
    }
    element = attributes.get("element.id")
    if element is not None:
        event["elementId"] = str(element)
    route = attributes.get("page.route", attributes.get("http.route"))
    if route is not None:
        event["route"] = str(route)
    outcome = attributes.get("usecase.outcome")
    if outcome is not None:
        event["outcome"] = str(outcome)
    if duration_ms is not None:
        event["durationMs"] = duration_ms
    if status is not None:
        event["status"] = status
    return event


def standout_events(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The friction and error events, in time order, at most STANDOUT_LIMIT of them."""
    chosen = [event for event in events if event.get("kind") in _STANDOUT_KINDS]
    chosen.sort(key=lambda event: int(event.get("offsetMs", 0)))
    return chosen[:STANDOUT_LIMIT]
