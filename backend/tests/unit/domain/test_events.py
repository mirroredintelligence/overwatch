"""Tests for diucs.domain.events: domain event payloads and Service Bus topics (D25).

Events are pure data: identifiers, counts and codes, never patient values. Sample values only.
"""

import dataclasses
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, get_args

import pytest

from diucs.domain.codes import AlertKind, BookingStatus, ReportSource, Status
from diucs.domain.errors import ValidationFailed
from diucs.domain.events import (
    AlertAcknowledged,
    AlertRaised,
    BookingExpired,
    BookingRequested,
    BookingResponded,
    CapacityReported,
    CriteriaApproved,
    DomainEvent,
    RegistrationApproved,
    RegistrationSubmitted,
    StatusChanged,
    from_payload,
    session_id_for,
    topic_for,
)

SERVICE_ID = "svc-ucr-west"
AT = datetime(2026, 10, 23, 10, 12, tzinfo=UTC)
AT_WITH_MICROSECONDS = datetime(2026, 10, 23, 10, 12, 30, 500000, tzinfo=UTC)

SAMPLES: tuple[DomainEvent, ...] = (
    CapacityReported(SERVICE_ID, "obs-1", 4, ReportSource.TEXT, AT),
    StatusChanged(SERVICE_ID, Status.ACCEPTING, Status.LIMITED, AT),
    StatusChanged(SERVICE_ID, None, Status.NOT_UPDATED, AT),
    BookingRequested("bk-1", SERVICE_ID, "REF-2K7Q", AT),
    BookingResponded("bk-1", SERVICE_ID, BookingStatus.CONFIRMED, AT),
    BookingExpired("bk-1", SERVICE_ID, AT),
    RegistrationSubmitted("reg-1", AT),
    RegistrationApproved("reg-1", SERVICE_ID, AT),
    CriteriaApproved("crit-1", SERVICE_ID, 2, AT),
    AlertRaised("alert-1", AlertKind.OVER_CAPACITY, SERVICE_ID, AT),
    AlertAcknowledged("alert-1", "prac-lead-1", AT),
)

EXPECTED_TOPIC: dict[type, str] = {
    CapacityReported: "capacity.events",
    StatusChanged: "capacity.events",
    BookingRequested: "booking.events",
    BookingResponded: "booking.events",
    BookingExpired: "booking.events",
    RegistrationSubmitted: "registration.events",
    RegistrationApproved: "registration.events",
    CriteriaApproved: "criteria.events",
    AlertRaised: "alerts.events",
    AlertAcknowledged: "alerts.events",
}


def test_capacity_reported_payload_matches_the_contract() -> None:
    event = CapacityReported(SERVICE_ID, "obs-1", 4, ReportSource.TEXT, AT)
    assert event.to_payload() == {
        "service_id": "svc-ucr-west",
        "report_id": "obs-1",
        "value": 4,
        "source": "text",
        "at": "2026-10-23T10:12:00Z",
    }


def test_status_changed_with_no_before_keeps_none_in_the_payload() -> None:
    event = StatusChanged(SERVICE_ID, None, Status.NOT_UPDATED, AT)
    payload = event.to_payload()
    assert payload["before"] is None
    assert payload["after"] == "not-updated"
    assert from_payload("StatusChanged", payload) == event


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: type(e).__name__)
def test_event_type_is_the_class_name(event: DomainEvent) -> None:
    assert event.event_type == type(event).__name__


def test_every_event_class_has_a_topic() -> None:
    assert set(EXPECTED_TOPIC) == set(get_args(DomainEvent))


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: type(e).__name__)
def test_topic_for_each_family(event: DomainEvent) -> None:
    assert topic_for(event) == EXPECTED_TOPIC[type(event)]


def test_session_id_is_the_service_id_for_capacity_events() -> None:
    assert (
        session_id_for(StatusChanged(SERVICE_ID, Status.ACCEPTING, Status.LIMITED, AT))
        == SERVICE_ID
    )
    assert (
        session_id_for(CapacityReported(SERVICE_ID, "obs-1", 4, ReportSource.TEXT, AT))
        == SERVICE_ID
    )


def test_session_id_is_none_for_booking_events() -> None:
    assert session_id_for(BookingRequested("bk-1", SERVICE_ID, "REF-2K7Q", AT)) is None


@pytest.mark.parametrize("event", SAMPLES, ids=lambda e: type(e).__name__)
def test_payload_is_json_safe_and_round_trips(event: DomainEvent) -> None:
    payload = event.to_payload()
    assert json.loads(json.dumps(payload)) == payload
    assert from_payload(event.event_type, payload) == event


def test_datetimes_keep_their_microseconds_and_end_in_z() -> None:
    event = CapacityReported(SERVICE_ID, "obs-1", 4, ReportSource.TEXT, AT_WITH_MICROSECONDS)
    assert event.to_payload()["at"] == "2026-10-23T10:12:30.500000Z"
    assert from_payload("CapacityReported", event.to_payload()) == event


def test_no_event_has_a_patient_field() -> None:
    forbidden = {"postcode", "name", "nhs_number", "needs"}
    for cls in get_args(DomainEvent):
        names = {field.name for field in dataclasses.fields(cls)}
        assert names.isdisjoint(forbidden), cls.__name__


def test_unknown_event_type_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        from_payload("Unknown", {})


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(ValidationFailed) as info:
        CapacityReported(SERVICE_ID, "obs-1", 4, ReportSource.TEXT, datetime(2026, 10, 23, 10, 12))
    assert info.value.field == "at"


def test_non_utc_offset_is_refused() -> None:
    bst = timezone(timedelta(hours=1))
    with pytest.raises(ValidationFailed) as info:
        CapacityReported(
            SERVICE_ID, "obs-1", 4, ReportSource.TEXT, datetime(2026, 10, 23, 11, 12, tzinfo=bst)
        )
    assert info.value.field == "at"


def test_payload_timestamp_with_an_offset_is_refused() -> None:
    payload: dict[str, Any] = {
        "service_id": SERVICE_ID,
        "report_id": "obs-1",
        "value": 4,
        "source": "text",
        "at": "2026-10-23T11:12:00+01:00",
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("CapacityReported", payload)
    assert info.value.field == "at"


def test_missing_payload_field_is_refused() -> None:
    payload: dict[str, Any] = {
        "service_id": SERVICE_ID,
        "report_id": "obs-1",
        "source": "text",
        "at": "2026-10-23T10:12:00Z",
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("CapacityReported", payload)
    assert info.value.field == "value"


@pytest.mark.parametrize("value", ["4", True, 4.0])
def test_value_must_be_an_integer(value: object) -> None:
    payload: dict[str, Any] = {
        "service_id": SERVICE_ID,
        "report_id": "obs-1",
        "value": value,
        "source": "text",
        "at": "2026-10-23T10:12:00Z",
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("CapacityReported", payload)
    assert info.value.field == "value"


def test_a_code_from_another_enum_is_refused() -> None:
    # "full" is a DeclineReason, not a BookingStatus, even though the value is a plain string.
    payload: dict[str, Any] = {
        "booking_id": "bk-1",
        "service_id": SERVICE_ID,
        "status": "full",
        "at": "2026-10-23T10:12:00Z",
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("BookingResponded", payload)
    assert info.value.field == "code"


def test_refused_code_is_not_echoed() -> None:
    payload: dict[str, Any] = {
        "service_id": SERVICE_ID,
        "report_id": "obs-1",
        "value": 4,
        "source": "jane-smith-0001",
        "at": "2026-10-23T10:12:00Z",
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("CapacityReported", payload)
    assert "jane-smith" not in str(info.value)
