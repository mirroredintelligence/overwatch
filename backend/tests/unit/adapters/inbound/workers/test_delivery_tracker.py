"""DeliveryTracker payload rules (I08). No Docker: every case is refused before the unit of work is
touched. The behaviour on real Neo4j is in
tests/integration/adapters/inbound/workers/test_delivery_tracker.py."""

from typing import Any

import pytest

from diucs.adapters.inbound.sms_webhook import routes
from diucs.adapters.inbound.workers.consumer import PermanentError
from diucs.adapters.inbound.workers.delivery_tracker import (
    CONSUMER_NAME,
    RECEIPT_EVENT,
    RECEIPT_STATUSES,
    DeliveryTracker,
)
from diucs.adapters.outbound.sms_twilio.twilio_sms import parse_status_callback
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import DELIVERY_STATUSES


class _Untouched:
    """A unit of work whose every attribute is a failure: a refused receipt must not reach it."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work must not be used: {name}")


def _message(payload: dict[str, Any], event_type: str = RECEIPT_EVENT) -> BusMessage:
    return BusMessage(
        id="SM123:delivered",
        topic="inbound.receipts",
        event_type=event_type,
        payload=payload,
        tenant_id="tenant-a",
    )


def _payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider_message_id": "SM123",
        "status": "delivered",
        "error_code": None,
    }
    payload.update(changes)
    return {name: value for name, value in payload.items() if value is not ...}


def test_the_names_are_the_ones_the_webhook_and_the_prompt_fix() -> None:
    assert CONSUMER_NAME == "delivery-tracker"
    assert RECEIPT_EVENT == routes.RECEIPT_EVENT


def test_the_statuses_are_the_ones_the_sender_adapter_maps_and_the_store_knows() -> None:
    mapped = {
        parse_status_callback({"MessageSid": "SM1", "MessageStatus": provider}).status
        for provider in ("queued", "sent", "delivered", "undelivered", "failed")
    }

    assert mapped == set(RECEIPT_STATUSES)
    assert RECEIPT_STATUSES <= DELIVERY_STATUSES


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_message_id": ...},
        {"provider_message_id": ""},
        {"provider_message_id": 12},
        {"status": ...},
        {"status": "grouped"},
        {"status": "received"},
        {"status": "read"},
        {"status": 3},
        {"error_code": 30003},
    ],
)
async def test_a_receipt_that_cannot_be_applied_is_dead_lettered(changes: dict[str, Any]) -> None:
    with pytest.raises(PermanentError):
        await DeliveryTracker()(_message(_payload(**changes)), _Untouched())  # type: ignore[arg-type]


async def test_a_message_of_another_kind_is_dead_lettered() -> None:
    with pytest.raises(PermanentError):
        await DeliveryTracker()(_message(_payload(), "SmsReceived"), _Untouched())  # type: ignore[arg-type]


async def test_a_refusal_never_repeats_the_provider_id() -> None:
    with pytest.raises(PermanentError) as raised:
        await DeliveryTracker()(
            _message(_payload(status="SECRET-STATUS")),
            _Untouched(),  # type: ignore[arg-type]
        )

    assert "SECRET-STATUS" not in str(raised.value)
    assert "SM123" not in str(raised.value)
