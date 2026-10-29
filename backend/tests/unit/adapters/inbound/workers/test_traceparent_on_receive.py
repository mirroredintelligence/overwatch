"""A received message carries the traceparent the publisher stamped (O01)."""

from types import SimpleNamespace
from typing import Any

import pytest

from diucs.adapters.inbound.workers.servicebus_runner import to_bus_message

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def _raw(properties: dict[Any, Any]) -> Any:
    return SimpleNamespace(
        message_id="m-1",
        body=iter([b'{"service": "svc-1"}']),
        subject="CapacityReported",
        session_id=None,
        application_properties=properties,
    )


def test_the_traceparent_property_becomes_the_message_traceparent() -> None:
    message = to_bus_message(_raw({"traceparent": TRACEPARENT}), "capacity.events")

    assert message.traceparent == TRACEPARENT


def test_a_bytes_keyed_traceparent_property_is_read_too() -> None:
    message = to_bus_message(_raw({b"traceparent": TRACEPARENT.encode()}), "capacity.events")

    assert message.traceparent == TRACEPARENT


@pytest.mark.parametrize("properties", [{}, {"traceparent": 42}])
def test_a_missing_or_non_text_traceparent_is_none(properties: dict[Any, Any]) -> None:
    message = to_bus_message(_raw(properties), "capacity.events")

    assert message.traceparent is None
