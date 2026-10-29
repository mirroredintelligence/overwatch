"""Telemetry query port (O07): the fixture fake, the Azure Monitor adapter and the shared rules.

No Docker and no live Azure call: the Azure adapter gets a recording stub client, and the fixture
fake reads tests/fixtures/telemetry/s-7f3a.json. Both take O01's attribute cleaner
(`result_attributes`), so the allow-list under test is the real one. Sample values only.
"""

import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from diucs.adapters.outbound.telemetry.azure_monitor_query import (
    AzureMonitorTelemetryQuery,
    LogsTable,
)
from diucs.adapters.outbound.telemetry.kql import SESSIONS_QUERY, SPANS_QUERY, TIMELINE_QUERY
from diucs.adapters.outbound.telemetry.result_attributes import result_attributes
from diucs.adapters.testing.fixture_telemetry import FixtureTelemetryQuery
from diucs.application.ports.outbound.telemetry_query import (
    SessionFilters,
    SessionSummary,
    SpanRecord,
    TelemetryQuery,
    TimelineEvent,
    TimelineKind,
    check_limit,
    check_session_id,
    check_trace_id,
)
from diucs.application.tenancy import TenantNotBound, bind_tenant
from diucs.domain.errors import ValidationFailed

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "telemetry" / "s-7f3a.json"
TRACE_ID = "7c1e9a2b5d4f48e0a3b6c9d2e1f0a8b7"
SESSION_ID = "s-7f3a"
WORKSPACE = "00000000-0000-0000-0000-000000000000"
WINDOW_START = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _fake() -> FixtureTelemetryQuery:
    return FixtureTelemetryQuery(FIXTURE, result_attributes)


@dataclass
class StubLogsClient:
    """A LogsQueryClient that records every call and returns canned tables, keyed by query text."""

    tables: dict[str, LogsTable]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def query_workspace(
        self,
        workspace_id: str,
        query: str,
        *,
        parameters: Mapping[str, str],
        timespan: tuple[datetime, datetime] | timedelta,
    ) -> LogsTable:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "query": query,
                "parameters": dict(parameters),
                "timespan": timespan,
            }
        )
        known = {"timeline": TIMELINE_QUERY, "spans": SPANS_QUERY, "sessions": SESSIONS_QUERY}
        for kind, text in known.items():
            if query == text and kind in self.tables:
                return self.tables[kind]
        raise AssertionError("the stub has no table for this query")


class _FixedClockStub:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


def _table_for_fixture(tenant: str) -> dict[str, LogsTable]:
    """The rows a KQL query scoped to `tenant` would return, in the column shapes the adapter
    reads. The KQL does the tenant filter on the server; this stub returns only that tenant's rows,
    which is what the server would send. The customDimensions carry the tenant and session ids, as
    the KQL projects them, and the attributes the fixture holds."""
    data = _fixture()
    timeline_rows = [
        (
            row["at"],
            row["kind"],
            row["name"],
            row["duration_ms"],
            row["status"],
            {**row["attributes"], "tenant.id": row["tenant_id"], "session.id": row["session_id"]},
        )
        for row in data["timeline"]
        if row["tenant_id"] == tenant and row["session_id"] == SESSION_ID
    ]
    span_rows = [
        (
            row["span_id"],
            row["parent_span_id"],
            row["name"],
            row["start"],
            row["duration_ms"],
            row["status"],
            {**row["attributes"], "tenant.id": row["tenant_id"]},
        )
        for row in data["spans"]
        if row["tenant_id"] == tenant and row["trace_id"] == TRACE_ID
    ]
    session_rows = [
        (
            row["session_id"],
            row["role"],
            row["device"],
            row["release"],
            row["started"],
            row["event_count"],
            row["friction_count"],
            row["error_count"],
        )
        for row in sorted(data["sessions"], key=lambda row: row["started"], reverse=True)
        if row["tenant_id"] == tenant
    ]
    return {
        "timeline": LogsTable(
            columns=("TimeGenerated", "kind", "name", "DurationMs", "status", "customDimensions"),
            rows=tuple(timeline_rows),
        ),
        "spans": LogsTable(
            columns=(
                "SpanId",
                "ParentSpanId",
                "SpanName",
                "StartTime",
                "DurationMs",
                "Status",
                "customDimensions",
            ),
            rows=tuple(span_rows),
        ),
        "sessions": LogsTable(
            columns=(
                "session_id",
                "role",
                "device",
                "release",
                "started",
                "event_count",
                "friction_count",
                "error_count",
            ),
            rows=tuple(session_rows),
        ),
    }


def _azure(tables: dict[str, LogsTable]) -> tuple[AzureMonitorTelemetryQuery, StubLogsClient]:
    stub = StubLogsClient(tables=tables)
    clock = _FixedClockStub(datetime(2026, 10, 28, 12, 0, tzinfo=UTC))
    adapter = AzureMonitorTelemetryQuery(client=stub, workspace_id=WORKSPACE, clock=clock)
    return adapter, stub


def _assert_timeline_contract(events: list[TimelineEvent]) -> None:
    """The assertions every implementation must pass, on the same sample session."""
    assert [event.at for event in events] == sorted(event.at for event in events)
    assert [event.name for event in events] == [
        "/advisor/call",
        "ADV-CALL-80-BTN",
        "ADV-POSTCODE-INPUT",
        "GET /api/bff/options",
        "ADV-OPT-REQUEST-BTN",
        "ADV-OPT-REQUEST-BTN",
        "BFF_TIMEOUT",
        "POST /api/bff/bookings",
    ]
    friction = [event for event in events if event.kind is TimelineKind.FRICTION]
    assert len(friction) == 1
    assert friction[0].name == "ADV-OPT-REQUEST-BTN"
    assert friction[0].attributes == {"element.id": "ADV-OPT-REQUEST-BTN"}
    for event in events:
        assert "fieldValue" not in event.attributes
        assert "tenant.id" not in event.attributes
        assert "session.id" not in event.attributes
    api = [event for event in events if event.kind is TimelineKind.API_CALL]
    assert [(event.duration_ms, event.status) for event in api] == [
        (212.4, "200"),
        (480.0, "201"),
    ]


def _assert_trace_contract(spans: list[SpanRecord]) -> None:
    assert len(spans) == 8
    parents = {span.parent_span_id for span in spans}
    leaves = [span for span in spans if span.span_id not in parents]
    slowest_leaf = max(leaves, key=lambda span: span.duration_ms)
    assert slowest_leaf.name == "neo4j Q-TASK-BOOK-CREATE"
    assert slowest_leaf.duration_ms == 480.5
    for span in spans:
        assert "tenant.id" not in span.attributes
        assert "fieldValue" not in span.attributes
    neo4j = next(span for span in spans if span.name == "neo4j Q-TASK-BOOK-CREATE")
    assert neo4j.attributes == {
        "db.query.id": "Q-TASK-BOOK-CREATE",
        "db.access_mode": "write",
        "db.row_count": 1,
        "db.system.name": "neo4j",
    }


def _assert_sessions_contract(sessions: list[SessionSummary]) -> None:
    # Most recent first: s-4c81 started at 10:02, s-7f3a at 09:12.
    assert [session.session_id for session in sessions] == ["s-4c81", SESSION_ID]
    first = sessions[1]
    assert (first.role, first.device, first.release) == ("advisor", "desktop", "2026.10.1")
    assert (first.event_count, first.friction_count, first.error_count) == (8, 1, 1)


# ---- Shared rules: identifiers and the result limit ----------------------------------------


@pytest.mark.parametrize("value", ["s-7f3a", "a", "A_b-9", "x" * 64])
def test_a_plain_session_id_is_accepted(value: str) -> None:
    assert check_session_id(value) == value


@pytest.mark.parametrize("value", ["", "s'); DROP", "s 7f3a", "x" * 65, "s/7f3a", "s\n"])
def test_a_session_id_with_other_characters_is_refused_before_any_query(value: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_session_id(value)
    assert refused.value.field == "session_id"
    assert value == "" or value not in str(refused.value)


def test_a_trace_id_is_32_lower_case_hex() -> None:
    assert check_trace_id(TRACE_ID) == TRACE_ID
    for bad in ("7C1E9A2B5D4F48E0A3B6C9D2E1F0A8B7", "7c1e9a2b", "z" * 32, ""):
        with pytest.raises(ValidationFailed):
            check_trace_id(bad)


@pytest.mark.parametrize("value", [0, 201, -1, True])
def test_a_result_limit_outside_1_to_200_is_refused(value: int) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_limit(value)
    assert refused.value.field == "limit"


# ---- O01's attribute rules, as the results apply them -------------------------------------


def test_result_attributes_keeps_o01_keys_and_drops_the_rest() -> None:
    raw = {
        "page.route": "/advisor/call",
        "element.id": "ADV-CALL-80-BTN",
        "fieldValue": "sample-postcode-text",
        "http.response.status_code": 200,
        "db.query.id": "Q-CASE-LOAD",
        "span.kind": "client",
        "tenant.id": "test-a",
        "session.id": "s-7f3a",
        "user.role": ["a", "list"],
        "device.type": {"nested": "object"},
        "release": True,
    }
    assert result_attributes(raw) == {
        "page.route": "/advisor/call",
        "element.id": "ADV-CALL-80-BTN",
        "http.response.status_code": 200,
        "db.query.id": "Q-CASE-LOAD",
        "release": True,
    }


def test_result_attributes_redacts_a_value_that_looks_like_a_phone_number() -> None:
    kept = result_attributes({"element.id": "07700 900123"})
    assert kept == {"element.id": "[redacted]"}


# ---- 1. Fixture fake: timeline ----------------------------------------------------------


async def test_fixture_timeline_for_s_7f3a_is_in_time_order_with_the_friction_event() -> None:
    with bind_tenant("test-a"):
        events = await _fake().session_timeline(SESSION_ID, WINDOW_START, WINDOW_END)
    _assert_timeline_contract(events)


async def test_fixture_timeline_is_limited_to_the_window() -> None:
    with bind_tenant("test-a"):
        events = await _fake().session_timeline(
            SESSION_ID, WINDOW_START, datetime(2026, 10, 28, 9, 12, 5, tzinfo=UTC)
        )
    assert [event.name for event in events] == ["/advisor/call", "ADV-CALL-80-BTN"]


async def test_fixture_timeline_for_tenant_b_session_is_not_shown_to_tenant_a() -> None:
    with bind_tenant("test-a"):
        events = await _fake().session_timeline("s-b102", WINDOW_START, WINDOW_END)
    assert events == []


# ---- 2. Fixture fake: trace -------------------------------------------------------------


async def test_fixture_trace_has_8_spans_and_the_task_book_query_is_the_slowest_leaf() -> None:
    with bind_tenant("test-a"):
        spans = await _fake().trace(TRACE_ID)
    _assert_trace_contract(spans)


async def test_fixture_trace_never_returns_a_span_of_another_tenant() -> None:
    with bind_tenant("test-a"):
        spans = await _fake().trace(TRACE_ID)
    assert "Q-PERSON-PHONE-FIND" not in " ".join(span.name for span in spans)


# ---- 3. Azure adapter: the session id is a parameter, not text ----------------------------


async def test_azure_timeline_sends_the_session_id_as_a_parameter_not_in_the_kql() -> None:
    adapter, stub = _azure(_table_for_fixture("test-a"))
    with bind_tenant("test-a"):
        await adapter.session_timeline(SESSION_ID, WINDOW_START, WINDOW_END)
    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert call["parameters"]["session_id"] == SESSION_ID
    assert SESSION_ID not in call["query"]
    assert "declare query_parameters" in call["query"]
    assert call["workspace_id"] == WORKSPACE


async def test_azure_sends_the_bound_tenant_as_a_parameter_and_never_in_the_text() -> None:
    adapter, stub = _azure(_table_for_fixture("test-a"))
    with bind_tenant("test-a"):
        await adapter.session_timeline(SESSION_ID, WINDOW_START, WINDOW_END)
        await adapter.trace(TRACE_ID)
        await adapter.search_sessions(SessionFilters())
    for call in stub.calls:
        assert call["parameters"]["tenant_id"] == "test-a"
        assert "test-a" not in call["query"]
        assert "tenant.id" in call["query"]


async def test_azure_refuses_an_invalid_session_id_before_calling_the_client() -> None:
    adapter, stub = _azure(_table_for_fixture("test-a"))
    with bind_tenant("test-a"), pytest.raises(ValidationFailed):
        await adapter.session_timeline("s'); drop", WINDOW_START, WINDOW_END)
    assert stub.calls == []


async def test_azure_refuses_to_run_with_no_tenant_bound() -> None:
    adapter, stub = _azure(_table_for_fixture("test-a"))
    with pytest.raises(TenantNotBound):
        await adapter.session_timeline(SESSION_ID, WINDOW_START, WINDOW_END)
    assert stub.calls == []


async def test_azure_search_sends_each_filter_as_a_parameter() -> None:
    adapter, stub = _azure(_table_for_fixture("test-a"))
    filters = SessionFilters(role="advisor", device="desktop", release="2026.10.1", limit=10)
    with bind_tenant("test-a"):
        await adapter.search_sessions(filters)
    params = stub.calls[0]["parameters"]
    assert params["role"] == "advisor"
    assert params["device"] == "desktop"
    assert params["release"] == "2026.10.1"
    assert params["limit"] == "10"
    assert "advisor" not in stub.calls[0]["query"]


# ---- 4. Azure adapter: mapping and the dropped column -------------------------------------


async def test_azure_maps_a_canned_table_to_timeline_events_and_drops_field_value() -> None:
    table = LogsTable(
        columns=("TimeGenerated", "kind", "name", "DurationMs", "status", "customDimensions"),
        rows=(
            (
                "2026-10-28T09:12:08Z",
                "field",
                "ADV-POSTCODE-INPUT",
                None,
                None,
                {
                    "element.id": "ADV-POSTCODE-INPUT",
                    "fieldValue": "sample-postcode-text",
                    "tenant.id": "test-a",
                    "session.id": "s-7f3a",
                },
            ),
            (
                "2026-10-28T09:12:15Z",
                "api_call",
                "GET /api/bff/options",
                212.4,
                "200",
                {
                    "http.route": "/api/bff/options",
                    "http.response.status_code": 200,
                    "tenant.id": "test-a",
                },
            ),
        ),
    )
    adapter, _ = _azure({"timeline": table})
    with bind_tenant("test-a"):
        events = await adapter.session_timeline(SESSION_ID, WINDOW_START, WINDOW_END)
    assert events == [
        TimelineEvent(
            at=datetime(2026, 10, 28, 9, 12, 8, tzinfo=UTC),
            kind=TimelineKind.FIELD,
            name="ADV-POSTCODE-INPUT",
            duration_ms=None,
            status=None,
            attributes={"element.id": "ADV-POSTCODE-INPUT"},
        ),
        TimelineEvent(
            at=datetime(2026, 10, 28, 9, 12, 15, tzinfo=UTC),
            kind=TimelineKind.API_CALL,
            name="GET /api/bff/options",
            duration_ms=212.4,
            status="200",
            attributes={"http.route": "/api/bff/options", "http.response.status_code": 200},
        ),
    ]


async def test_azure_drops_a_row_whose_tenant_is_not_the_bound_one_even_if_the_server_sent_it() -> (
    None
):
    table = LogsTable(
        columns=("TimeGenerated", "kind", "name", "DurationMs", "status", "customDimensions"),
        rows=(
            (
                "2026-10-28T09:30:05Z",
                "page_view",
                "/advisor/call",
                None,
                None,
                {"page.route": "/advisor/call", "tenant.id": "test-b", "session.id": "s-7f3a"},
            ),
        ),
    )
    adapter, _ = _azure({"timeline": table})
    with bind_tenant("test-a"):
        events = await adapter.session_timeline(SESSION_ID, WINDOW_START, WINDOW_END)
    assert events == []


async def test_azure_drops_a_row_with_an_unknown_kind() -> None:
    table = LogsTable(
        columns=("TimeGenerated", "kind", "name", "DurationMs", "status", "customDimensions"),
        rows=(("2026-10-28T09:12:00Z", "replay_frame", "x", None, None, {"tenant.id": "test-a"}),),
    )
    adapter, _ = _azure({"timeline": table})
    with bind_tenant("test-a"):
        assert await adapter.session_timeline(SESSION_ID, WINDOW_START, WINDOW_END) == []


# ---- 5. Contract: the same assertions on the fake and on the Azure adapter ----------------


async def test_contract_timeline_holds_on_the_fake_and_on_azure_with_fixture_rows() -> None:
    with bind_tenant("test-a"):
        _assert_timeline_contract(
            await _fake().session_timeline(SESSION_ID, WINDOW_START, WINDOW_END)
        )
        adapter, _ = _azure(_table_for_fixture("test-a"))
        _assert_timeline_contract(
            await adapter.session_timeline(SESSION_ID, WINDOW_START, WINDOW_END)
        )


async def test_contract_trace_holds_on_the_fake_and_on_azure_with_fixture_rows() -> None:
    with bind_tenant("test-a"):
        _assert_trace_contract(await _fake().trace(TRACE_ID))
        adapter, _ = _azure(_table_for_fixture("test-a"))
        _assert_trace_contract(await adapter.trace(TRACE_ID))


async def test_contract_sessions_hold_on_the_fake_and_on_azure_with_fixture_rows() -> None:
    with bind_tenant("test-a"):
        _assert_sessions_contract(await _fake().search_sessions(SessionFilters()))
        adapter, _ = _azure(_table_for_fixture("test-a"))
        _assert_sessions_contract(await adapter.search_sessions(SessionFilters()))


async def test_fixture_search_applies_filters_and_the_limit_within_the_tenant() -> None:
    with bind_tenant("test-a"):
        advisors = await _fake().search_sessions(SessionFilters(role="advisor"))
        limited = await _fake().search_sessions(SessionFilters(limit=1))
        desktop_only = await _fake().search_sessions(SessionFilters(device="desktop"))
    assert [session.session_id for session in advisors] == [SESSION_ID]
    assert [session.session_id for session in limited] == ["s-4c81"]
    assert [session.session_id for session in desktop_only] == [SESSION_ID]


async def test_fixture_reads_as_tenant_b_show_only_tenant_b() -> None:
    with bind_tenant("test-b"):
        sessions = await _fake().search_sessions(SessionFilters())
        events = await _fake().session_timeline("s-b102", WINDOW_START, WINDOW_END)
        spans = await _fake().trace(TRACE_ID)
    assert [session.session_id for session in sessions] == ["s-b102"]
    assert [event.name for event in events] == ["/advisor/call"]
    assert [span.name for span in spans] == ["neo4j Q-PERSON-PHONE-FIND"]


async def test_fixture_refuses_to_run_with_no_tenant_bound() -> None:
    with pytest.raises(TenantNotBound):
        await _fake().search_sessions(SessionFilters())


async def test_fixture_refuses_a_naive_time_window() -> None:
    with bind_tenant("test-a"), pytest.raises(ValueError):
        await _fake().session_timeline(SESSION_ID, datetime(2026, 10, 28, 9, 0), WINDOW_END)


# ---- Port shape ----------------------------------------------------------------------------


def test_no_query_takes_a_tenant_argument() -> None:
    for name in ("session_timeline", "trace", "search_sessions"):
        for impl in (FixtureTelemetryQuery, AzureMonitorTelemetryQuery):
            signature = inspect.signature(getattr(impl, name))
            assert not any("tenant" in parameter for parameter in signature.parameters)
    assert "tenant" not in " ".join(inspect.signature(TelemetryQuery.trace).parameters)


async def test_the_fake_and_the_adapter_both_satisfy_the_port() -> None:
    query: TelemetryQuery = _fake()
    adapter, _ = _azure({})
    other: TelemetryQuery = adapter
    assert isinstance(query, FixtureTelemetryQuery)
    assert isinstance(other, AzureMonitorTelemetryQuery)
