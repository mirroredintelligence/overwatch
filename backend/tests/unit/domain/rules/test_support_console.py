"""The pure rules of the support console (R18): what a session event may carry, the filter names
and which events stand out. Routes and the Neo4j-backed reads are in the integration suite."""

from datetime import UTC, datetime

import pytest

from diucs.application.ports.outbound.telemetry_query import TimelineKind
from diucs.domain.rules.support_console import (
    ALLOWED_EVENT_KEYS,
    EVENT_FILTERS,
    public_event,
    standout_events,
)

START = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def test_the_allowed_keys_are_the_spec_list_and_nothing_else() -> None:
    assert (
        frozenset({"kind", "elementId", "route", "outcome", "durationMs", "status", "offsetMs"})
        == ALLOWED_EVENT_KEYS
    )


def test_a_public_event_keeps_the_allowed_keys_and_drops_a_field_value() -> None:
    event = public_event(
        kind="field",
        name="ADV-POSTCODE-INPUT",
        at=START,
        start=START,
        duration_ms=None,
        status=None,
        attributes={
            "element.id": "ADV-POSTCODE-INPUT",
            "fieldValue": "sample-postcode-text",
            "page.route": "/advisor/call",
        },
    )

    assert set(event) <= ALLOWED_EVENT_KEYS
    assert event["elementId"] == "ADV-POSTCODE-INPUT"
    assert event["kind"] == "field"
    assert "sample-postcode-text" not in repr(event)
    assert "fieldValue" not in event


def test_the_offset_is_the_time_since_the_start_of_the_session_in_milliseconds() -> None:
    event = public_event(
        kind="api_call",
        name="POST /api/bff/bookings",
        at=datetime(2026, 10, 29, 9, 0, 3, tzinfo=UTC),
        start=START,
        duration_ms=480.0,
        status="201",
        attributes={"http.route": "/api/bff/bookings"},
    )

    assert event["offsetMs"] == 3000
    assert event["durationMs"] == 480.0
    assert event["status"] == "201"


def test_the_filter_names_map_to_the_timeline_kinds() -> None:
    assert EVENT_FILTERS["all"] == frozenset(kind.value for kind in TimelineKind)
    assert EVENT_FILTERS["errors"] == frozenset({"error"})
    assert EVENT_FILTERS["friction"] == frozenset({"friction"})
    assert EVENT_FILTERS["api"] == frozenset({"api_call"})
    assert EVENT_FILTERS["navigation"] == frozenset({"page_view"})


def test_a_filter_outside_the_list_is_refused() -> None:
    with pytest.raises(KeyError):
        _ = EVENT_FILTERS["everything-typed"]


def test_standout_is_the_friction_and_error_events_in_time_order_up_to_five() -> None:
    events = [
        {"kind": "page_view", "offsetMs": 0},
        {"kind": "friction", "offsetMs": 2000},
        {"kind": "error", "offsetMs": 4000},
        {"kind": "click", "offsetMs": 5000},
    ]

    assert [event["offsetMs"] for event in standout_events(events)] == [2000, 4000]
    assert len(standout_events([{"kind": "error", "offsetMs": i} for i in range(9)])) == 5
