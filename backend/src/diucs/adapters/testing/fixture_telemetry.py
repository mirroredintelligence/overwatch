"""Fixture fake for the telemetry query port (O07): the support console's raw telemetry, served
from a JSON fixture instead of Azure Monitor. An external-provider fake (Azure Monitor is an
external provider). It writes nothing and holds no record of truth.

The fixture is a list of rows per kind (sessions, timeline, spans), each row carrying its
`tenant_id`. A read returns only the rows of the tenant bound to the context, as the workspace
query does with its `tenant.id` filter. Attributes pass the same allow-list as the adapter.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from diucs.application.ports.outbound.telemetry_query import (
    AttributeCleaner,
    SessionFilters,
    SessionSummary,
    SpanRecord,
    TimelineEvent,
    TimelineKind,
    as_utc,
    check_limit,
    check_session_id,
    check_trace_id,
)
from diucs.application.tenancy import current_tenant
from diucs.domain.model.telemetry_aggregates import (
    DayAggregates,
    ElementUsageDailyRow,
    FrictionDailyRow,
    FunnelDailyRow,
    QueryStatDailyRow,
    RouteDailyRow,
)


@dataclass(frozen=True, slots=True)
class _Owned:
    tenant_id: str
    key: str
    value: Any


class FixtureTelemetryQuery:
    def __init__(self, fixture_path: Path, attributes: AttributeCleaner) -> None:
        """`attributes` is the O01 cleaner the composition root passes (the allow-list and the value
        scan); this fake has no allow-list of its own.

        """
        self._attributes = attributes
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
        self._daily = [
            _Owned(row["tenant_id"], row["day"], _day_aggregates(row))
            for row in data.get("daily", [])
        ]

    def _event(self, row: Mapping[str, Any]) -> TimelineEvent:
        duration = row["duration_ms"]
        return TimelineEvent(
            at=as_utc(row["at"]),
            kind=TimelineKind(row["kind"]),
            name=str(row["name"]),
            duration_ms=None if duration is None else float(duration),
            status=row["status"],
            attributes=self._attributes(row["attributes"]),
        )

    def _span(self, row: Mapping[str, Any]) -> SpanRecord:
        return SpanRecord(
            span_id=row["span_id"],
            parent_span_id=row["parent_span_id"],
            name=row["name"],
            start=as_utc(row["start"]),
            duration_ms=float(row["duration_ms"]),
            status=row["status"],
            attributes=self._attributes(row["attributes"]),
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

    async def daily_aggregates(self, day: date) -> DayAggregates:
        tenant = current_tenant()
        key = day.isoformat()
        for owned in self._daily:
            if owned.tenant_id == tenant and owned.key == key:
                aggregates: DayAggregates = owned.value
                return aggregates
        return DayAggregates()

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


def _day_aggregates(row: Mapping[str, Any]) -> DayAggregates:
    """One tenant's day from the fixture. Each row names its day; the fake serves the day asked
    for.

    """
    day = date.fromisoformat(row["day"])
    return DayAggregates(
        funnel=tuple(
            FunnelDailyRow(
                day=day,
                funnel=item["funnel"],
                step=item["step"],
                role=item["role"],
                channel=item["channel"],
                device=item["device"],
                entered=int(item["entered"]),
                completed=int(item["completed"]),
                median_ms=_optional_float(item["median_ms"]),
                branch=bool(item["branch"]),
            )
            for item in row.get("funnel", [])
        ),
        friction=tuple(
            FrictionDailyRow(
                day=day,
                element_id=item["element_id"],
                kind=item["kind"],
                role=item["role"],
                device=item["device"],
                interactions=int(item["interactions"]),
                events=int(item["events"]),
                sessions=int(item["sessions"]),
            )
            for item in row.get("friction", [])
        ),
        usage=tuple(
            ElementUsageDailyRow(
                day=day,
                element_id=item["element_id"],
                role=item["role"],
                device=item["device"],
                interactions=int(item["interactions"]),
                sessions=int(item["sessions"]),
            )
            for item in row.get("usage", [])
        ),
        routes=tuple(
            RouteDailyRow(
                day=day,
                route=item["route"],
                role=item["role"],
                device=item["device"],
                p50=_optional_float(item["p50"]),
                p75=_optional_float(item["p75"]),
                p95=_optional_float(item["p95"]),
                lcp75=_optional_float(item["lcp75"]),
                inp75=_optional_float(item["inp75"]),
                cls75=_optional_float(item["cls75"]),
                errors=int(item["errors"]),
                sessions=int(item["sessions"]),
            )
            for item in row.get("routes", [])
        ),
        queries=tuple(
            QueryStatDailyRow(
                day=day,
                query_id=item["query_id"],
                calls=int(item["calls"]),
                p50=_optional_float(item["p50"]),
                p95=_optional_float(item["p95"]),
                errors=int(item["errors"]),
            )
            for item in row.get("queries", [])
        ),
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
