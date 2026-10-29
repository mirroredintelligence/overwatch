"""Outbound port: read raw telemetry for the support and insight console (O07).

Raw traces and events live in Application Insights on a Log Analytics workspace (observability.md,
"Where telemetry lives"). The console reads them through this port only, never through the store
directly. Three reads:

- `session_timeline`: what one session did, in time order (page views, clicks by element, field
  events without values, API calls with durations and statuses, friction flags, errors).
- `trace`: the spans of one trace, from the browser to the provider.
- `search_sessions`: session summaries for the find-a-session screen.

Every result carries only allow-listed attributes. An adapter drops every other attribute when it
maps a row, so a field value or a query text cannot reach the console
(observability.md, "Scrubbing").

The tenant is never an argument. Every read is for the tenant bound to the context at the edge
(DEC-130, DEC-132); an adapter reads it with `application.tenancy.current_tenant()` and refuses to
run when none is bound.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol

from diucs.domain.errors import ValidationFailed

# An attribute value after the allow-list: the types the telemetry schema carries.
AttributeValue = str | int | float | bool

_SESSION_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TRACE_ID: Final = re.compile(r"[0-9a-f]{32}")
MAX_SESSION_RESULTS: Final = 200


class TimelineKind(StrEnum):
    PAGE_VIEW = "page_view"
    CLICK = "click"
    FIELD = "field"
    API_CALL = "api_call"
    FRICTION = "friction"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One entry in a session timeline. `duration_ms` and `status` are set for API calls only."""

    at: datetime
    kind: TimelineKind
    name: str
    duration_ms: float | None
    status: str | None
    attributes: Mapping[str, AttributeValue]


@dataclass(frozen=True, slots=True)
class SpanRecord:
    """One span of a trace. `parent_span_id` is None for the root span."""

    span_id: str
    parent_span_id: str | None
    name: str
    start: datetime
    duration_ms: float
    status: str
    attributes: Mapping[str, AttributeValue]


@dataclass(frozen=True, slots=True)
class SessionSummary:
    session_id: str
    role: str
    device: str
    release: str
    started: datetime
    event_count: int
    friction_count: int
    error_count: int


@dataclass(frozen=True, slots=True)
class SessionFilters:
    """Optional filters for `search_sessions`. None means no filter on that field."""

    role: str | None = None
    device: str | None = None
    release: str | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None
    limit: int = 50


class TelemetryQuery(Protocol):
    async def session_timeline(
        self, session_id: str, start: datetime, end: datetime
    ) -> list[TimelineEvent]:
        """Timeline events of one session between start and end, in time order."""
        ...

    async def trace(self, trace_id: str) -> list[SpanRecord]:
        """Spans of one trace, in start order."""
        ...

    async def search_sessions(self, filters: SessionFilters) -> list[SessionSummary]:
        """Session summaries that match the filters, most recent first."""
        ...


def allowed_attributes(
    raw: Mapping[str, object], allowed: frozenset[str]
) -> dict[str, AttributeValue]:
    """Keep only the allow-listed keys whose values are plain scalars (text, whole number, number or
    boolean). Everything else is dropped: an unlisted key, a null, a list or an object."""
    kept: dict[str, AttributeValue] = {}
    for key, value in raw.items():
        if key in allowed and isinstance(value, bool | int | float | str):
            kept[key] = value
    return kept


def as_utc(value: object) -> datetime:
    """A timezone-aware instant in UTC, from a datetime or an ISO 8601 text (a trailing Z allowed).
    A naive value is refused: the console compares instants, never wall-clock times."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("a telemetry time must be a timezone-aware instant")
    return value.astimezone(UTC)


def check_session_id(value: str) -> str:
    """Return the session id when it is 1 to 64 letters, digits, hyphens or underscores; refuse
    anything else before it reaches a query. The field name only is in the refusal."""
    if not isinstance(value, str) or _SESSION_ID.fullmatch(value) is None:
        raise ValidationFailed(
            "session_id", "must be 1 to 64 letters, digits, hyphens or underscores"
        )
    return value


def check_trace_id(value: str) -> str:
    """Return the trace id when it is 32 lower-case hexadecimal characters (W3C trace id)."""
    if not isinstance(value, str) or _TRACE_ID.fullmatch(value) is None:
        raise ValidationFailed("trace_id", "must be 32 lower-case hexadecimal characters")
    return value


def check_limit(value: int) -> int:
    """Return the result limit when it is between 1 and MAX_SESSION_RESULTS."""
    if type(value) is not int or not 1 <= value <= MAX_SESSION_RESULTS:
        raise ValidationFailed("limit", f"must be from 1 to {MAX_SESSION_RESULTS}")
    return value
