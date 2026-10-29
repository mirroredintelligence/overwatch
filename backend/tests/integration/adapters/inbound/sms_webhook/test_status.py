"""The delivery-receipt route (I07): the same signature check, then one message on
inbound.receipts with the id MessageSid:MessageStatus. The tenant comes from the AccountSid of the
verified request (DEC-131 item 2)."""

import json

import pytest
from httpx import AsyncClient

from diucs.adapters.testing.memory_event_bus import ManualEventBus
from tests.support.sms import (
    INTERNAL_STATUS_URL,
    SENDER_E164,
    STATUS_URL,
    TENANT_A,
    TENANT_B,
    post_signed,
    sign,
    status_params,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'
QUEUE = "inbound.receipts"


async def test_a_delivered_receipt_is_queued_with_the_sid_and_status_as_its_id(
    sms_client: AsyncClient, sms_bus: ManualEventBus
) -> None:
    response = await post_signed(
        sms_client, status_params(), signed_url=STATUS_URL, send_to=INTERNAL_STATUS_URL
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/xml"
    assert response.text == TWIML
    [queued] = sms_bus.enqueued_to(QUEUE)
    assert queued.id == "SM1:delivered"
    assert queued.topic == QUEUE
    assert queued.event_type == "SmsDeliveryReceived"
    assert queued.tenant_id == "tenant-a"
    assert queued.payload == {
        "provider_message_id": "SM1",
        "status": "delivered",
        "error_code": None,
    }
    assert sms_bus.enqueued_to("inbound.replies") == []


async def test_an_undelivered_receipt_carries_its_error_code_and_the_failed_status(
    sms_client: AsyncClient, sms_bus: ManualEventBus
) -> None:
    params = {**status_params(status="undelivered"), "ErrorCode": "30003"}

    response = await post_signed(
        sms_client, params, signed_url=STATUS_URL, send_to=INTERNAL_STATUS_URL
    )

    assert response.status_code == 200
    [queued] = sms_bus.enqueued_to(QUEUE)
    assert queued.id == "SM1:undelivered"
    assert queued.payload == {
        "provider_message_id": "SM1",
        "status": "failed",
        "error_code": "30003",
    }


async def test_the_recipients_number_is_never_queued(
    sms_client: AsyncClient, sms_bus: ManualEventBus
) -> None:
    await post_signed(
        sms_client, status_params(), signed_url=STATUS_URL, send_to=INTERNAL_STATUS_URL
    )

    [queued] = sms_bus.enqueued_to(QUEUE)
    everything = json.dumps([queued.id, queued.payload])
    assert "7700900123" not in everything
    assert SENDER_E164 not in everything


@pytest.mark.parametrize("case", ["wrong-token", "no-header", "reply-url", "body-changed"])
async def test_a_receipt_that_does_not_verify_is_refused_and_nothing_is_queued(
    sms_client: AsyncClient, sms_bus: ManualEventBus, case: str
) -> None:
    params = status_params()
    signature = {
        "wrong-token": sign(STATUS_URL, params, TENANT_B.token),
        "no-header": None,
        "reply-url": sign("https://diucs.example/webhooks/sms/twilio", params, TENANT_A.token),
        "body-changed": sign(STATUS_URL, {**params, "MessageStatus": "failed"}, TENANT_A.token),
    }[case]
    headers = {} if signature is None else {"X-Twilio-Signature": signature}

    response = await sms_client.post(INTERNAL_STATUS_URL, data=params, headers=headers)

    assert response.status_code == 403
    assert response.text == "Forbidden"
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_an_unknown_account_is_refused_like_a_bad_signature(
    sms_client: AsyncClient, sms_bus: ManualEventBus
) -> None:
    params = {**status_params(), "AccountSid": "AC" + "9" * 32}

    response = await post_signed(
        sms_client, params, signed_url=STATUS_URL, send_to=INTERNAL_STATUS_URL
    )

    assert (response.status_code, response.text) == (403, "Forbidden")
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_a_receipt_of_the_other_tenant_is_queued_for_that_tenant_only(
    sms_client: AsyncClient, sms_bus: ManualEventBus
) -> None:
    await post_signed(
        sms_client,
        status_params(TENANT_B),
        token=TENANT_B.token,
        signed_url=STATUS_URL,
        send_to=INTERNAL_STATUS_URL,
    )
    wrong = await post_signed(
        sms_client,
        status_params(TENANT_B),
        token=TENANT_A.token,
        signed_url=STATUS_URL,
        send_to=INTERNAL_STATUS_URL,
    )

    assert wrong.status_code == 403
    [queued] = sms_bus.enqueued_to(QUEUE)
    assert queued.tenant_id == "tenant-b"


@pytest.mark.parametrize("status", ["accepted", "scheduled", "received", "read", ""])
async def test_a_status_the_system_does_not_map_is_dropped_with_a_200(
    sms_client: AsyncClient, sms_bus: ManualEventBus, status: str
) -> None:
    response = await post_signed(
        sms_client, status_params(status=status), signed_url=STATUS_URL, send_to=INTERNAL_STATUS_URL
    )

    assert (response.status_code, response.text) == (200, TWIML)
    assert sms_bus.enqueued_to(QUEUE) == []


@pytest.mark.parametrize("sid", ["", "SM:1", "SM" + "9" * 70])
async def test_a_receipt_with_no_usable_sid_is_dropped_with_a_200(
    sms_client: AsyncClient, sms_bus: ManualEventBus, sid: str
) -> None:
    response = await post_signed(
        sms_client, status_params(sid=sid), signed_url=STATUS_URL, send_to=INTERNAL_STATUS_URL
    )

    assert (response.status_code, response.text) == (200, TWIML)
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_a_failed_queue_send_gives_a_500_so_twilio_can_send_the_receipt_again(
    sms_client: AsyncClient, sms_bus: ManualEventBus, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(queue: str, message: object) -> None:
        raise ConnectionError("bus down")

    monkeypatch.setattr(sms_bus, "enqueue", down)

    response = await post_signed(
        sms_client, status_params(), signed_url=STATUS_URL, send_to=INTERNAL_STATUS_URL
    )

    assert response.status_code == 500
