"""Tests for diucs.domain.events: domain event payloads and Service Bus topics (D25).

Events are pure data: identifiers, counts and codes, never patient values. Sample values only.
"""

import dataclasses
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, get_args

import pytest

from diucs.domain.codes import (
    AlertKind,
    BookingStatus,
    DeclineReason,
    ReportFlagReason,
    ReportSource,
    Role,
    Status,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.events import (
    AlertAcknowledged,
    AlertRaised,
    BookingExpired,
    BookingPhonePrompt,
    BookingRequested,
    BookingResponded,
    CapacityReported,
    CriteriaApproved,
    DomainEvent,
    PhoneTaskRaised,
    RegistrationApproved,
    RegistrationSubmitted,
    ReportEscalated,
    ReportFlagged,
    ServiceActivated,
    StatusChanged,
    from_payload,
    session_id_for,
    topic_for,
)

SERVICE_ID = "svc-ucr-west"
AT = datetime(2026, 10, 23, 10, 12, tzinfo=UTC)
AT_WITH_MICROSECONDS = datetime(2026, 10, 23, 10, 12, 30, 500000, tzinfo=UTC)
DUE_AT = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)

SAMPLES: tuple[DomainEvent, ...] = (
    CapacityReported(SERVICE_ID, "obs-1", 4, ReportSource.TEXT, AT),
    StatusChanged(SERVICE_ID, Status.ACCEPTING, Status.LIMITED, AT),
    StatusChanged(SERVICE_ID, None, Status.NOT_UPDATED, AT),
    BookingRequested("bk-1", SERVICE_ID, "4821", AT),
    BookingResponded("bk-1", SERVICE_ID, BookingStatus.CONFIRMED, AT),
    BookingExpired("bk-1", SERVICE_ID, AT),
    BookingPhonePrompt("bk-1", SERVICE_ID, "4821", AT),
    RegistrationSubmitted("reg-1", AT),
    RegistrationApproved("reg-1", SERVICE_ID, AT),
    ServiceActivated(SERVICE_ID, AT),
    CriteriaApproved("crit-1", SERVICE_ID, 2, AT),
    AlertRaised("alert-1", AlertKind.OVER_CAPACITY, SERVICE_ID, AT),
    AlertAcknowledged("alert-1", Role.LEAD, AT),
    ReportFlagged("flag-1", SERVICE_ID, "obs-1", ReportFlagReason.MANY_CHANGES, AT),
    PhoneTaskRaised(SERVICE_ID, DUE_AT, AT),
    ReportEscalated(SERVICE_ID, DUE_AT, AT),
)

EXPECTED_TOPIC: dict[type, str] = {
    CapacityReported: "capacity.events",
    StatusChanged: "capacity.events",
    BookingRequested: "booking.events",
    BookingResponded: "booking.events",
    BookingExpired: "booking.events",
    BookingPhonePrompt: "booking.events",
    RegistrationSubmitted: "registration.events",
    RegistrationApproved: "registration.events",
    ServiceActivated: "registration.events",
    CriteriaApproved: "criteria.events",
    AlertRaised: "alerts.events",
    AlertAcknowledged: "alerts.events",
    ReportFlagged: "capacity.events",
    PhoneTaskRaised: "capacity.events",
    ReportEscalated: "alerts.events",
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


def test_session_id_is_the_service_id_for_a_report_flag() -> None:
    event = ReportFlagged("flag-1", SERVICE_ID, "obs-1", ReportFlagReason.MANY_CHANGES, AT)
    assert session_id_for(event) == SERVICE_ID


def test_session_id_is_none_for_booking_events() -> None:
    assert session_id_for(BookingRequested("bk-1", SERVICE_ID, "4821", AT)) is None


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
    assert info.value.field == "status"


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


def booking_payload(reference: object) -> dict[str, Any]:
    return {
        "booking_id": "bk-1",
        "service_id": SERVICE_ID,
        "reference": reference,
        "at": "2026-10-23T10:12:00Z",
    }


@pytest.mark.parametrize(
    "reference",
    [
        "Jane Smith DT4 8XX",
        "DT4 8XX",
        "943 476 5919",
        "9434765919",
        "0482",
        "48210",
        "482",
        "4821 ",
        "",
        "REF-2K7Q",
    ],
)
def test_booking_reference_refuses_anything_but_a_four_digit_number(reference: str) -> None:
    with pytest.raises(ValidationFailed) as info:
        from_payload("BookingRequested", booking_payload(reference))
    assert info.value.field == "reference"
    assert reference.strip() == "" or reference not in str(info.value)


@pytest.mark.parametrize("reference", ["Jane Smith DT4 8XX", "943 476 5919", "0482"])
def test_booking_reference_is_checked_when_the_event_is_built(reference: str) -> None:
    with pytest.raises(ValidationFailed) as info:
        BookingRequested("bk-1", SERVICE_ID, reference, AT)
    assert info.value.field == "reference"


@pytest.mark.parametrize("reference", [None, 4821, b"4821"])
def test_booking_reference_must_be_text(reference: object) -> None:
    with pytest.raises(ValidationFailed) as info:
        BookingRequested("bk-1", SERVICE_ID, reference, AT)  # type: ignore[arg-type]
    assert info.value.field == "reference"


@pytest.mark.parametrize("reference", ["1000", "4821", "9999"])
def test_booking_reference_accepts_a_four_digit_number(reference: str) -> None:
    event = BookingRequested("bk-1", SERVICE_ID, reference, AT)
    assert event.reference == reference
    assert from_payload("BookingRequested", booking_payload(reference)) == event


@pytest.mark.parametrize(
    "by",
    ["943 476 5919", "9434765919", "Jane Smith", "prac-lead-1", "full", ""],
)
def test_alert_acknowledged_by_must_be_a_role(by: str) -> None:
    payload: dict[str, Any] = {
        "alert_id": "alert-1",
        "by": by,
        "at": "2026-10-23T10:12:00Z",
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("AlertAcknowledged", payload)
    assert info.value.field == "by"


def test_alert_acknowledged_by_refuses_a_member_of_another_enum() -> None:
    # DeclineReason.FULL is a str with the value "full". It is not a Role and must be refused.
    with pytest.raises(ValidationFailed) as info:
        AlertAcknowledged("alert-1", DeclineReason.FULL, AT)  # type: ignore[arg-type]
    assert info.value.field == "by"


def test_alert_acknowledged_by_a_role_round_trips_as_a_role() -> None:
    event = from_payload(
        "AlertAcknowledged",
        {"alert_id": "alert-1", "by": "lead", "at": "2026-10-23T10:12:00Z"},
    )
    assert isinstance(event, AlertAcknowledged)
    assert type(event.by) is Role
    assert event.by is Role.LEAD


@pytest.mark.parametrize("role", list(Role))
def test_every_role_is_accepted_for_alert_acknowledged(role: Role) -> None:
    event = AlertAcknowledged("alert-1", role, AT)
    assert from_payload("AlertAcknowledged", event.to_payload()) == event


def test_the_same_value_in_two_enums_is_parsed_by_the_field_enum() -> None:
    # "not-updated" is a Status and an AlertKind; "over-capacity" is too (lesson L3).
    alert = from_payload(
        "AlertRaised",
        {
            "alert_id": "alert-1",
            "kind": "not-updated",
            "service_id": SERVICE_ID,
            "at": "2026-10-23T10:12:00Z",
        },
    )
    assert isinstance(alert, AlertRaised)
    assert type(alert.kind) is AlertKind
    change = from_payload(
        "StatusChanged",
        {
            "service_id": SERVICE_ID,
            "before": None,
            "after": "over-capacity",
            "at": "2026-10-23T10:12:00Z",
        },
    )
    assert isinstance(change, StatusChanged)
    assert type(change.after) is Status


def test_a_status_value_is_not_an_alert_kind() -> None:
    # "accepting" is a Status only, so it is refused where an AlertKind is expected.
    with pytest.raises(ValidationFailed) as info:
        from_payload(
            "AlertRaised",
            {
                "alert_id": "alert-1",
                "kind": "accepting",
                "service_id": SERVICE_ID,
                "at": "2026-10-23T10:12:00Z",
            },
        )
    assert info.value.field == "kind"


@pytest.mark.parametrize(
    "at",
    ["2026-10-23T10:12:00", "2026-10-23T10:12:00+00:00", "2026-10-23 10:12:00Z"],
)
def test_decoded_timestamp_must_end_in_z(at: str) -> None:
    payload: dict[str, Any] = {
        "service_id": SERVICE_ID,
        "report_id": "obs-1",
        "value": 4,
        "source": "text",
        "at": at,
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("CapacityReported", payload)
    assert info.value.field == "at"


def test_decoded_timestamp_that_does_not_parse_is_refused() -> None:
    payload: dict[str, Any] = {
        "service_id": SERVICE_ID,
        "report_id": "obs-1",
        "value": 4,
        "source": "text",
        "at": "2026-13-45T10:12:00Z",
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("CapacityReported", payload)
    assert info.value.field == "at"


# --- ReportFlagged (U07) -------------------------------------------------------------------------


def test_report_flagged_payload_matches_the_contract() -> None:
    event = ReportFlagged("flag-1", SERVICE_ID, "obs-1", ReportFlagReason.DIFFERS_FROM_PHONED, AT)
    assert event.to_payload() == {
        "flag_id": "flag-1",
        "service_id": "svc-ucr-west",
        "report_id": "obs-1",
        "reason": "differs-from-phoned",
        "at": "2026-10-23T10:12:00Z",
    }


@pytest.mark.parametrize("reason", list(ReportFlagReason))
def test_every_flag_reason_round_trips_as_a_flag_reason(reason: ReportFlagReason) -> None:
    event = ReportFlagged("flag-1", SERVICE_ID, "obs-1", reason, AT)
    rebuilt = from_payload("ReportFlagged", event.to_payload())
    assert rebuilt == event
    assert isinstance(rebuilt, ReportFlagged)
    assert type(rebuilt.reason) is ReportFlagReason


@pytest.mark.parametrize(
    "reason",
    ["Jane Smith", "DT4 8XX", "943 476 5919", "07700 900123", "full", "", "MANY-CHANGES"],
)
def test_report_flagged_reason_must_be_a_flag_reason(reason: str) -> None:
    payload: dict[str, Any] = {
        "flag_id": "flag-1",
        "service_id": SERVICE_ID,
        "report_id": "obs-1",
        "reason": reason,
        "at": "2026-10-23T10:12:00Z",
    }
    with pytest.raises(ValidationFailed) as info:
        from_payload("ReportFlagged", payload)
    assert info.value.field == "reason"


def test_report_flagged_refuses_a_reason_that_is_a_plain_string_or_another_enum() -> None:
    with pytest.raises(ValidationFailed) as info:
        ReportFlagged("flag-1", SERVICE_ID, "obs-1", "many-changes", AT)  # type: ignore[arg-type]
    assert info.value.field == "reason"
    with pytest.raises(ValidationFailed) as other:
        ReportFlagged("flag-1", SERVICE_ID, "obs-1", Status.ACCEPTING, AT)  # type: ignore[arg-type]
    assert other.value.field == "reason"


@pytest.mark.parametrize("missing", ["flag_id", "service_id", "report_id", "reason", "at"])
def test_report_flagged_needs_every_field(missing: str) -> None:
    payload: dict[str, Any] = ReportFlagged(
        "flag-1", SERVICE_ID, "obs-1", ReportFlagReason.MANY_CHANGES, AT
    ).to_payload()
    del payload[missing]
    with pytest.raises(ValidationFailed) as info:
        from_payload("ReportFlagged", payload)
    assert info.value.field == missing


def test_report_flagged_refuses_a_time_that_is_not_utc() -> None:
    with pytest.raises(ValidationFailed) as info:
        ReportFlagged(
            "flag-1",
            SERVICE_ID,
            "obs-1",
            ReportFlagReason.MANY_CHANGES,
            datetime(2026, 10, 23, 10, 12),
        )
    assert info.value.field == "at"


@pytest.mark.parametrize("field", ["flag_id", "service_id", "report_id"])
@pytest.mark.parametrize("value", [7, None, ["flag-1"], b"flag-1"])
def test_report_flagged_ids_must_be_text(field: str, value: object) -> None:
    payload: dict[str, Any] = ReportFlagged(
        "flag-1", SERVICE_ID, "obs-1", ReportFlagReason.MANY_CHANGES, AT
    ).to_payload()
    payload[field] = value
    with pytest.raises(ValidationFailed) as info:
        from_payload("ReportFlagged", payload)
    assert info.value.field == field


# --- PhoneTaskRaised and ReportEscalated (U06) ---------------------------------------------------

LADDER_EVENTS = (PhoneTaskRaised, ReportEscalated)


@pytest.mark.parametrize("cls", LADDER_EVENTS)
def test_a_ladder_event_payload_matches_the_contract(cls: Any) -> None:
    # contracts.md: {service_id, due_at, at}, both instants as UTC text ending in Z.
    assert cls(SERVICE_ID, DUE_AT, AT).to_payload() == {
        "service_id": "svc-ucr-west",
        "due_at": "2026-10-23T11:00:00Z",
        "at": "2026-10-23T10:12:00Z",
    }


@pytest.mark.parametrize("cls", LADDER_EVENTS)
def test_a_ladder_event_round_trips_with_microseconds(cls: Any) -> None:
    event = cls(SERVICE_ID, DUE_AT + timedelta(microseconds=5), AT_WITH_MICROSECONDS)
    payload = event.to_payload()
    assert payload["due_at"] == "2026-10-23T11:00:00.000005Z"
    rebuilt = from_payload(cls.__name__, payload)
    assert rebuilt == event
    assert type(rebuilt) is cls


def test_the_phone_task_orders_by_service_and_the_escalation_has_no_session() -> None:
    # The phone task is on capacity.events with the other per-service events, so it is read in
    # order with the report that stops it. An escalation goes to alerts.events, which has no
    # session.
    assert session_id_for(PhoneTaskRaised(SERVICE_ID, DUE_AT, AT)) == SERVICE_ID
    assert session_id_for(ReportEscalated(SERVICE_ID, DUE_AT, AT)) is None


@pytest.mark.parametrize("cls", LADDER_EVENTS)
@pytest.mark.parametrize("field", ["due_at", "at"])
def test_a_ladder_event_refuses_a_time_that_is_not_utc(cls: Any, field: str) -> None:
    bst = timezone(timedelta(hours=1))
    times = {"due_at": DUE_AT, "at": AT}
    for bad in (datetime(2026, 10, 23, 11, 0), datetime(2026, 10, 23, 12, 0, tzinfo=bst)):
        with pytest.raises(ValidationFailed) as info:
            cls(SERVICE_ID, **{**times, field: bad})
        assert info.value.field == field


@pytest.mark.parametrize("cls", LADDER_EVENTS)
@pytest.mark.parametrize("missing", ["service_id", "due_at", "at"])
def test_a_ladder_event_needs_every_field(cls: Any, missing: str) -> None:
    payload = cls(SERVICE_ID, DUE_AT, AT).to_payload()
    del payload[missing]
    with pytest.raises(ValidationFailed) as info:
        from_payload(cls.__name__, payload)
    assert info.value.field == missing


@pytest.mark.parametrize("cls", LADDER_EVENTS)
@pytest.mark.parametrize("bad", ["2026-10-23T12:00:00+01:00", "2026-10-23 11:00:00Z", "11:00", 7])
def test_a_ladder_event_payload_due_time_must_be_utc_text(cls: Any, bad: object) -> None:
    payload = cls(SERVICE_ID, DUE_AT, AT).to_payload()
    payload["due_at"] = bad
    with pytest.raises(ValidationFailed) as info:
        from_payload(cls.__name__, payload)
    assert info.value.field == "due_at"


@pytest.mark.parametrize("cls", LADDER_EVENTS)
def test_a_ladder_event_service_must_be_text(cls: Any) -> None:
    payload = cls(SERVICE_ID, DUE_AT, AT).to_payload()
    payload["service_id"] = ["svc-ucr-west"]
    with pytest.raises(ValidationFailed) as info:
        from_payload(cls.__name__, payload)
    assert info.value.field == "service_id"
