"""Azure Monitor adapter for the telemetry query port (O07). Stub: the tests are written first."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.telemetry_query import (
    SessionFilters,
    SessionSummary,
    SpanRecord,
    TimelineEvent,
)


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


class AzureMonitorTelemetryQuery:
    def __init__(
        self,
        client: LogsQueryClient,
        workspace_id: str,
        clock: Clock,
        allowed_attributes: Iterable[str],
    ) -> None:
        raise NotImplementedError

    async def session_timeline(
        self, session_id: str, start: datetime, end: datetime
    ) -> list[TimelineEvent]:
        raise NotImplementedError

    async def trace(self, trace_id: str) -> list[SpanRecord]:
        raise NotImplementedError

    async def search_sessions(self, filters: SessionFilters) -> list[SessionSummary]:
        raise NotImplementedError
