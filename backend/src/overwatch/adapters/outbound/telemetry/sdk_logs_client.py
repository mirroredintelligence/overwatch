"""Wraps the Azure Monitor logs client (azure-monitor-query) to the `LogsQueryClient` shape the
telemetry adapter uses (O07).

Two rules. First, a query with parameters is refused: the SDK's `query_workspace` takes no
parameters, and the way to bind them in Log Analytics is not verified (a known issue for the
verification stage). A refused read answers TelemetryUnavailable; nothing is concatenated into the
text. Second, a partial result is refused rather than shown as whole: a partly answered query would
make a timeline look shorter than it was.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from azure.monitor.query import LogsQueryPartialResult

from diucs.adapters.outbound.telemetry.azure_monitor_query import LogsTable
from diucs.application.ports.outbound.telemetry_query import TelemetryUnavailable


class SdkLogsQueryClient:
    def __init__(self, sdk_client: Any) -> None:
        """`sdk_client` is an `azure.monitor.query.aio.LogsQueryClient` (or a stand-in with the same
        `query_workspace` method)."""
        self._sdk = sdk_client

    async def query_workspace(
        self,
        workspace_id: str,
        query: str,
        *,
        parameters: Mapping[str, str],
        timespan: tuple[datetime, datetime] | timedelta,
    ) -> LogsTable:
        if parameters:
            raise TelemetryUnavailable
        result = await self._sdk.query_workspace(workspace_id, query, timespan=timespan)
        if isinstance(result, LogsQueryPartialResult):
            raise TelemetryUnavailable
        tables = list(result.tables)
        if len(tables) != 1:
            raise TelemetryUnavailable
        table = tables[0]
        return LogsTable(
            columns=tuple(str(column) for column in table.columns),
            rows=tuple(tuple(row) for row in table.rows),
        )
