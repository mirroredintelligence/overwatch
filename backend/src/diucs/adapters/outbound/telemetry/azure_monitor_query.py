"""Azure Monitor adapter for the telemetry query port (O07).

Runs the three KQL queries in `kql.py` against the Log Analytics workspace and maps the rows. The
tenant is the bound one (`current_tenant`) and goes to the query as a parameter. Each row is
checked against that tenant again after the query, so a row the server sent for another tenant
is dropped (defence in depth: the KQL already filters). Attributes pass the allow-list, and every
other attribute is dropped when the row is mapped.

The session id, trace id and filters are parameters, never text in the query. The window for a
trace or a search is the raw retention below, from the clock.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from diucs.adapters.outbound.telemetry.kql import SESSIONS_QUERY, SPANS_QUERY, TIMELINE_QUERY
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.telemetry_query import (
    SessionFilters,
    SessionSummary,
    SpanRecord,
    TimelineEvent,
    TimelineKind,
    allowed_attributes,
    as_utc,
    check_limit,
    check_session_id,
    check_trace_id,
)
from diucs.application.tenancy import current_tenant

# Raw retention is 30 to 90 days (observability.md, "Privacy and governance"). [ASSUMED] 90: a
# trace or a search older than this is not looked up. Set with IG.
RAW_LOOKBACK: Final = timedelta(days=90)
_TENANT_KEY: Final = "tenant.id"


@dataclass(frozen=True, slots=True)
class LogsTable:
    """One query result: the column names and the rows, in column order."""

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


class LogsQueryClient(Protocol):
    """The part of an Azure Monitor logs client this adapter uses. The production client is wrapped
    to match it; tests pass a recording stub."""

    async def query_workspace(
        self,
        workspace_id: str,
        query: str,
        *,
        parameters: Mapping[str, str],
        timespan: tuple[datetime, datetime] | timedelta,
    ) -> LogsTable: ...


def _records(table: LogsTable) -> list[dict[str, object]]:
    return [dict(zip(table.columns, row, strict=True)) for row in table.rows]


def _text(value: object) -> str | None:
    """A text column, with an empty or null value read as absent."""
    if value is None or value == "":
        return None
    return str(value)


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("a duration must be a number")
    return float(value)


class AzureMonitorTelemetryQuery:
    def __init__(
        self,
        client: LogsQueryClient,
        workspace_id: str,
        clock: Clock,
        allowed_attributes: Iterable[str],
    ) -> None:
        self._client = client
        self._workspace_id = workspace_id
        self._clock = clock
        self._allowed = frozenset(allowed_attributes)

    def _window(self) -> tuple[datetime, datetime]:
        now = as_utc(self._clock.now())
        return now - RAW_LOOKBACK, now

    def _owned(self, record: Mapping[str, object], tenant: str) -> bool:
        dims = record.get("customDimensions")
        return isinstance(dims, Mapping) and dims.get(_TENANT_KEY) == tenant

    def _attributes(self, record: Mapping[str, object]) -> dict[str, str | int | float | bool]:
        dims = record.get("customDimensions")
        if not isinstance(dims, Mapping):
            return {}
        return allowed_attributes(dims, self._allowed)

    async def session_timeline(
        self, session_id: str, start: datetime, end: datetime
    ) -> list[TimelineEvent]:
        check_session_id(session_id)
        tenant = current_tenant()
        begin, finish = as_utc(start), as_utc(end)
        table = await self._client.query_workspace(
            self._workspace_id,
            TIMELINE_QUERY,
            parameters={
                "session_id": session_id,
                "tenant_id": tenant,
                "start": begin.isoformat(),
                "end": finish.isoformat(),
            },
            timespan=(begin, finish),
        )
        events: list[TimelineEvent] = []
        for record in _records(table):
            if not self._owned(record, tenant):
                continue
            try:
                kind = TimelineKind(str(record["kind"]))
            except ValueError:
                continue
            events.append(
                TimelineEvent(
                    at=as_utc(record["TimeGenerated"]),
                    kind=kind,
                    name=str(record["name"]),
                    duration_ms=_number(record["DurationMs"]),
                    status=_text(record["status"]),
                    attributes=self._attributes(record),
                )
            )
        return sorted(events, key=lambda event: event.at)

    async def trace(self, trace_id: str) -> list[SpanRecord]:
        check_trace_id(trace_id)
        tenant = current_tenant()
        table = await self._client.query_workspace(
            self._workspace_id,
            SPANS_QUERY,
            parameters={"trace_id": trace_id, "tenant_id": tenant},
            timespan=self._window(),
        )
        spans: list[SpanRecord] = []
        for record in _records(table):
            if not self._owned(record, tenant):
                continue
            duration = _number(record["DurationMs"])
            if duration is None:
                continue
            spans.append(
                SpanRecord(
                    span_id=str(record["SpanId"]),
                    parent_span_id=_text(record["ParentSpanId"]),
                    name=str(record["SpanName"]),
                    start=as_utc(record["StartTime"]),
                    duration_ms=duration,
                    status=str(record["Status"]),
                    attributes=self._attributes(record),
                )
            )
        return sorted(spans, key=lambda span: span.start)

    async def search_sessions(self, filters: SessionFilters) -> list[SessionSummary]:
        limit = check_limit(filters.limit)
        tenant = current_tenant()
        parameters = {
            "tenant_id": tenant,
            "role": filters.role or "",
            "device": filters.device or "",
            "release": filters.release or "",
            "started_from": ""
            if filters.started_from is None
            else as_utc(filters.started_from).isoformat(),
            "started_to": ""
            if filters.started_to is None
            else as_utc(filters.started_to).isoformat(),
            "limit": str(limit),
        }
        table = await self._client.query_workspace(
            self._workspace_id,
            SESSIONS_QUERY,
            parameters=parameters,
            timespan=self._window(),
        )
        return [
            SessionSummary(
                session_id=str(record["session_id"]),
                role=str(record["role"]),
                device=str(record["device"]),
                release=str(record["release"]),
                started=as_utc(record["started"]),
                event_count=int(str(record["event_count"])),
                friction_count=int(str(record["friction_count"])),
                error_count=int(str(record["error_count"])),
            )
            for record in _records(table)
        ]
