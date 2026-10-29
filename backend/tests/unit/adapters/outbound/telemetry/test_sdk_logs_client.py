"""The Azure Monitor SDK wrapper (O07), with a stand-in SDK client: no Azure call. The wrapper
refuses a parameterised query (the SDK takes no parameters; binding is unverified), refuses a
partial result and a result with other than one table, and maps the table it gets."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from azure.monitor.query import LogsQueryPartialResult

from diucs.adapters.outbound.telemetry.sdk_logs_client import SdkLogsQueryClient
from diucs.application.ports.outbound.telemetry_query import TelemetryUnavailable

WORKSPACE = "00000000-0000-0000-0000-000000000000"
START = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
END = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)


class StandInSdk:
    def __init__(self, result: Any) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def query_workspace(self, workspace_id: str, query: str, **kwargs: Any) -> Any:
        self.calls.append({"workspace_id": workspace_id, "query": query, **kwargs})
        return self._result


def _one_table(columns: list[str], rows: list[list[Any]]) -> SimpleNamespace:
    table = SimpleNamespace(columns=columns, rows=rows)
    return SimpleNamespace(tables=[table])


async def test_a_query_with_parameters_is_refused_before_the_sdk_is_called() -> None:
    sdk = StandInSdk(_one_table(["a"], [["x"]]))
    client = SdkLogsQueryClient(sdk)
    with pytest.raises(TelemetryUnavailable):
        await client.query_workspace(
            WORKSPACE, "AppEvents", parameters={"session_id": "s-7f3a"}, timespan=(START, END)
        )
    assert sdk.calls == []


async def test_a_query_with_no_parameters_passes_the_workspace_text_and_window_to_the_sdk() -> None:
    sdk = StandInSdk(_one_table(["a", "b"], [[1, "x"]]))
    client = SdkLogsQueryClient(sdk)
    table = await client.query_workspace(
        WORKSPACE, "AppEvents", parameters={}, timespan=(START, END)
    )
    assert sdk.calls == [
        {"workspace_id": WORKSPACE, "query": "AppEvents", "timespan": (START, END)}
    ]
    assert table.columns == ("a", "b")
    assert table.rows == ((1, "x"),)


async def test_a_window_given_as_a_duration_is_passed_through() -> None:
    sdk = StandInSdk(_one_table(["a"], []))
    client = SdkLogsQueryClient(sdk)
    await client.query_workspace(WORKSPACE, "AppEvents", parameters={}, timespan=timedelta(days=90))
    assert sdk.calls[0]["timespan"] == timedelta(days=90)


async def test_a_partial_result_is_refused_rather_than_shown_as_whole() -> None:
    partial = LogsQueryPartialResult(
        partial_data=[], partial_error=None, statistics=None, visualization=None, status=None
    )
    client = SdkLogsQueryClient(StandInSdk(partial))
    with pytest.raises(TelemetryUnavailable):
        await client.query_workspace(WORKSPACE, "AppEvents", parameters={}, timespan=(START, END))


async def test_a_result_with_other_than_one_table_is_refused() -> None:
    two = SimpleNamespace(
        tables=[SimpleNamespace(columns=[], rows=[]), SimpleNamespace(columns=[], rows=[])]
    )
    client = SdkLogsQueryClient(StandInSdk(two))
    with pytest.raises(TelemetryUnavailable):
        await client.query_workspace(WORKSPACE, "AppEvents", parameters={}, timespan=(START, END))
