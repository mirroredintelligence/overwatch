"""Fixture fake for the telemetry query port (O07): the support console's raw telemetry, served
from JSON fixtures instead of Azure Monitor. An external-provider fake (Azure Monitor is an external
provider). It writes nothing and holds no record of truth.
"""

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from diucs.application.ports.outbound.telemetry_query import (
    SessionFilters,
    SessionSummary,
    SpanRecord,
    TimelineEvent,
)


class FixtureTelemetryQuery:
    def __init__(self, fixture_path: Path, allowed_attributes: Iterable[str]) -> None:
        raise NotImplementedError

    async def session_timeline(
        self, session_id: str, start: datetime, end: datetime
    ) -> list[TimelineEvent]:
        raise NotImplementedError

    async def trace(self, trace_id: str) -> list[SpanRecord]:
        raise NotImplementedError

    async def search_sessions(self, filters: SessionFilters) -> list[SessionSummary]:
        raise NotImplementedError
