"""Fixture fake for the telemetry query port (O07): the support console's raw telemetry, served
from a JSON fixture instead of Azure Monitor. An external-provider fake (Azure Monitor is an
external provider). It writes nothing and holds no record of truth.

The fixture is a list of rows per kind (sessions, timeline, spans), each row carrying its
`tenant_id`. A read returns only the rows of the tenant bound to the context, as the workspace
query does with its `tenant.id` filter. Attributes pass the same allow-list as the adapter.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True, slots=True)
class _Owned:
    tenant_id: str
    key: str
    value: Any


class FixtureTelemetryQuery:
    def __init__(self, fixture_path: Path, allowed: Iterable[str]) -> None:
        self._allowed = frozenset(allowed)
        data: Mapping[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
        self._timeline = [
            _Owned(row["tenant_id"], row["session_id"], self._event(row))
            for row in data["timeline"]
        ]
        self._spans = [
            _Owned(row["tenant_id"], row["trace_id"], self._span(row)) for row in data["spans"]
        ]
        self._sessions = [
            _Owned(row["tenant_id"], row["session_id"], self._session(row))
            for row in data["sessions"]
        ]

    def _event(self, row: Mapping[str, Any]) -> TimelineEvent:
        duration = row["duration_ms"]
        return TimelineEvent(
            at=as_utc(row["at"]),
            kind=TimelineKind(row["kind"]),
            name=str(row["name"]),
            duration_ms=None if duration is None else float(duration),
            status=row["status"],
            attributes=allowed_attributes(row["attributes"], self._allowed),
        )

    def _span(self, row: Mapping[str, Any]) -> SpanRecord:
        return SpanRecord(
            span_id=row["span_id"],
            parent_span_id=row["parent_span_id"],
            name=row["name"],
            start=as_utc(row["start"]),
            duration_ms=float(row["duration_ms"]),
            status=row["status"],
            attributes=allowed_attributes(row["attributes"], self._allowed),
        )

    def _session(self, row: Mapping[str, Any]) -> SessionSummary:
        return SessionSummary(
            session_id=row["session_id"],
            role=row["role"],
            device=row["device"],
            release=row["release"],
            started=as_utc(row["started"]),
            event_count=int(row["event_count"]),
            friction_count=int(row["friction_count"]),
            error_count=int(row["error_count"]),
        )

    async def session_timeline(
        self, session_id: str, start: datetime, end: datetime
    ) -> list[TimelineEvent]:
        check_session_id(session_id)
        tenant = current_tenant()
        begin, finish = as_utc(start), as_utc(end)
        events = [
            owned.value
            for owned in self._timeline
            if owned.tenant_id == tenant
            and owned.key == session_id
            and begin <= owned.value.at <= finish
        ]
        return sorted(events, key=lambda event: event.at)

    async def trace(self, trace_id: str) -> list[SpanRecord]:
        check_trace_id(trace_id)
        tenant = current_tenant()
        spans = [
            owned.value
            for owned in self._spans
            if owned.tenant_id == tenant and owned.key == trace_id
        ]
        return sorted(spans, key=lambda span: span.start)

    async def search_sessions(self, filters: SessionFilters) -> list[SessionSummary]:
        limit = check_limit(filters.limit)
        tenant = current_tenant()
        found = [
            owned.value
            for owned in self._sessions
            if owned.tenant_id == tenant and _matches(owned.value, filters)
        ]
        found.sort(key=lambda session: session.started, reverse=True)
        return found[:limit]


def _matches(session: SessionSummary, filters: SessionFilters) -> bool:
    if filters.role is not None and session.role != filters.role:
        return False
    if filters.device is not None and session.device != filters.device:
        return False
    if filters.release is not None and session.release != filters.release:
        return False
    if filters.started_from is not None and session.started < as_utc(filters.started_from):
        return False
    return not (filters.started_to is not None and session.started > as_utc(filters.started_to))
