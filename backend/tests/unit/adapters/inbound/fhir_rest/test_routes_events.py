"""Pure tests of the live-update stream's message rules (R06). No Docker, no HTTP.

Two message shapes reach the stream: the shape the task names (serviceId, kind, changedAt) and the
shape the board projector publishes (type "board-changed", service_id, at; DEC-099 item 8). Both
become the same event, with only the fields the page needs.
"""

import pytest

from diucs.adapters.inbound.fhir_rest.routes_events import parse_message, to_sse

CHANGED_AT = "2026-10-23T13:12:00Z"


def test_a_board_message_becomes_one_event_with_only_the_three_fields() -> None:
    message = {
        "serviceId": "svc-1",
        "kind": "capacity",
        "changedAt": CHANGED_AT,
        "extra": "x",
    }

    assert to_sse(message) == (
        'event: board\ndata: {"serviceId":"svc-1","kind":"capacity",'
        '"changedAt":"2026-10-23T13:12:00Z"}\n\n'
    )


@pytest.mark.parametrize("kind", ["weather", "Capacity", "", None])
def test_an_unknown_kind_is_dropped(kind: object) -> None:
    message = {"serviceId": "svc-1", "kind": kind, "changedAt": CHANGED_AT}

    assert to_sse(message) is None


@pytest.mark.parametrize("service_id", [None, "", 7])
def test_a_message_without_a_usable_service_id_is_dropped(service_id: object) -> None:
    message = {"serviceId": service_id, "kind": "status", "changedAt": CHANGED_AT}

    assert to_sse(message) is None


def test_a_message_with_no_service_id_key_is_dropped() -> None:
    assert to_sse({"kind": "booking", "changedAt": CHANGED_AT}) is None


def test_a_message_without_a_changed_time_is_dropped() -> None:
    assert to_sse({"serviceId": "svc-1", "kind": "capacity"}) is None


def test_a_projector_message_becomes_an_event_without_a_kind() -> None:
    message = {"type": "board-changed", "service_id": "svc-1", "at": CHANGED_AT}

    assert to_sse(message) == (
        'event: board\ndata: {"serviceId":"svc-1","changedAt":"2026-10-23T13:12:00Z"}\n\n'
    )


def test_a_projector_message_with_no_service_id_is_a_whole_board_event() -> None:
    # KI-55: a change that belongs to no one service (the pressure banner, an approved criteria
    # set) reaches the open page at once, as its own named event with the time and nothing else.
    message = {"type": "board-changed", "service_id": None, "at": CHANGED_AT}

    assert to_sse(message) == 'event: board-whole\ndata: {"changedAt":"2026-10-23T13:12:00Z"}\n\n'


def test_a_projector_message_with_no_service_id_key_is_dropped() -> None:
    # Only an explicit null is a whole-board change; a message that lacks the key is malformed.
    assert to_sse({"type": "board-changed", "at": CHANGED_AT}) is None


@pytest.mark.parametrize("changed_at", ["13:12", "2026-10-23T13:12:00", "2026-13-45T99:99:00Z", 7, None])
def test_a_whole_board_message_with_a_bad_time_is_dropped(changed_at: object) -> None:
    assert to_sse({"type": "board-changed", "service_id": None, "at": changed_at}) is None


def test_a_whole_board_message_sent_in_the_task_shape_is_still_dropped() -> None:
    # The task shape names a service; without one it is not a board message (R06).
    assert to_sse({"serviceId": None, "changedAt": CHANGED_AT}) is None


def test_the_heartbeat_is_a_named_event_with_the_time_only() -> None:
    # KI-54: a comment line cannot be read by the page; a named event can, so the page can tell
    # an open stream from a dead one.
    from datetime import UTC, datetime

    from diucs.adapters.inbound.fhir_rest.routes_events import heartbeat_sse

    assert heartbeat_sse(datetime(2026, 10, 23, 13, 12, tzinfo=UTC)) == (
        'event: heartbeat\ndata: {"changedAt":"2026-10-23T13:12:00Z"}\n\n'
    )


def test_the_heartbeat_time_is_written_in_utc_whatever_the_zone_of_the_clock() -> None:
    from datetime import datetime, timedelta, timezone

    from diucs.adapters.inbound.fhir_rest.routes_events import heartbeat_sse

    bst = timezone(timedelta(hours=1))

    assert heartbeat_sse(datetime(2026, 10, 23, 14, 12, tzinfo=bst)) == (
        'event: heartbeat\ndata: {"changedAt":"2026-10-23T13:12:00Z"}\n\n'
    )


def test_the_heartbeat_interval_is_well_inside_the_pages_silence_limit() -> None:
    # The page treats three missed beats as a dead stream; the interval is the shared constant.
    from diucs.adapters.inbound.fhir_rest.routes_events import KEEPALIVE_INTERVAL_SECONDS

    assert KEEPALIVE_INTERVAL_SECONDS <= 15


@pytest.mark.parametrize("message_type", ["board", "capacity-changed", "BOARD-CHANGED", ""])
def test_a_message_of_another_type_is_dropped(message_type: str) -> None:
    message = {"type": message_type, "service_id": "svc-1", "at": CHANGED_AT}

    assert to_sse(message) is None


@pytest.mark.parametrize("value", ["svc-1", 7, None, ["svc-1"]])
def test_a_value_that_is_not_an_object_is_dropped(value: object) -> None:
    assert to_sse(value) is None


def test_text_that_is_not_json_is_not_a_message() -> None:
    assert parse_message("{not json") is None


def test_text_that_is_json_is_parsed_as_the_message() -> None:
    assert parse_message('{"serviceId":"svc-1"}') == {"serviceId": "svc-1"}


@pytest.mark.parametrize(
    "service_id", ["Jane Smith", "DT4 8XX", "svc 1", "svc/1", "svc_1", "a" * 65]
)
def test_a_projector_message_with_a_malformed_service_id_is_dropped(service_id: str) -> None:
    message = {"type": "board-changed", "service_id": service_id, "at": CHANGED_AT}

    assert to_sse(message) is None


@pytest.mark.parametrize(
    "changed_at",
    [
        "2026-10-23 13:12:00Z",
        "23/10/2026 13:12",
        "2026-10-23T13:12:00+01:00",
        "2026-10-23T13:12:00",
        "2026-13-45T99:99:00Z",
        "13:12",
    ],
)
def test_a_projector_message_with_a_malformed_time_is_dropped(changed_at: str) -> None:
    message = {"type": "board-changed", "service_id": "svc-1", "at": changed_at}

    assert to_sse(message) is None


@pytest.mark.parametrize("service_id", ["Jane Smith", "DT4 8XX", "svc 1"])
def test_a_task_message_with_a_malformed_service_id_is_dropped(service_id: str) -> None:
    message = {"serviceId": service_id, "kind": "capacity", "changedAt": CHANGED_AT}

    assert to_sse(message) is None


def test_a_malformed_value_is_not_echoed_into_any_event() -> None:
    # A name or postcode in a bad field must never reach the stream, not even partly.
    message = {"serviceId": "Jane Smith", "kind": "capacity", "changedAt": CHANGED_AT}

    assert to_sse(message) is None


def test_a_projector_time_written_with_a_zero_offset_is_sent_with_z() -> None:
    # The projector writes isoformat(), which ends in +00:00. The event carries the Z form.
    message = {"type": "board-changed", "service_id": "svc-1", "at": "2026-10-23T13:12:00+00:00"}

    assert to_sse(message) == (
        'event: board\ndata: {"serviceId":"svc-1","changedAt":"2026-10-23T13:12:00Z"}\n\n'
    )
