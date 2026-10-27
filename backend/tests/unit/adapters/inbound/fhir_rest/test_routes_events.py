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


def test_a_projector_message_with_no_service_id_is_dropped() -> None:
    message = {"type": "board-changed", "service_id": None, "at": CHANGED_AT}

    assert to_sse(message) is None


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
