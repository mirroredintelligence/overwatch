"""The inbound text route (I07): signature, allow-list, replay, queue and the answer to Twilio.

Runs on the harness Neo4j through the FHIR app (R01), with a recording bus and an in-memory cache.
Every request is signed by the independent signer in tests/support/sms.py, over the public URL,
and arrives at http://internal:8000 as it would behind a proxy.
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.sms_webhook import routes
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.bootstrap.container import Container
from tests.integration.adapters.inbound.sms_webhook.conftest import seed_practitioner
from tests.support.sms import (
    FORM,
    INTERNAL_REPLY_URL,
    LANDLINE_E164,
    REPLY_TEXT,
    REPLY_URL,
    SENDER_E164,
    TENANT_A,
    TENANT_B,
    UNKNOWN_SENDER_E164,
    phone_hash,
    post_signed,
    reply_params,
    sign,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

SID = "SM" + "1" * 32
TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'
REFUSED_BODY = "Forbidden"
QUEUE = "inbound.replies"


def _assert_empty_twiml(status: int, content_type: str, body: str) -> None:
    assert status == 200
    assert content_type == "text/xml"
    assert body == TWIML


async def test_a_valid_reply_is_answered_with_empty_twiml_and_queued_once(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    response = await post_signed(sms_client, reply_params(sid=SID))

    _assert_empty_twiml(response.status_code, response.headers["content-type"], response.text)
    [queued] = sms_bus.enqueued_to(QUEUE)
    assert queued.id == SID
    assert queued.topic == QUEUE
    assert queued.event_type == "SmsReceived"
    assert queued.tenant_id == "tenant-a"
    assert queued.payload == {
        "phone_hash": phone_hash(SENDER_E164),
        "text": REPLY_TEXT,
        "received_at": "2026-10-23T13:12:00+00:00",
        "provider_message_id": SID,
    }


async def test_the_raw_number_is_never_queued(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    await post_signed(sms_client, reply_params(sid=SID))

    [queued] = sms_bus.enqueued_to(QUEUE)
    everything = json.dumps([queued.id, queued.topic, queued.event_type, queued.payload])
    assert "7700900123" not in everything.replace(" ", "")
    assert "07700" not in everything


async def test_the_reply_goes_to_the_replies_queue_and_nothing_else_is_published(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    await post_signed(sms_client, reply_params(sid=SID))

    assert len(sms_bus.enqueued_to(QUEUE)) == 1
    assert sms_bus.published == []
    assert sms_bus.enqueued_to("inbound.receipts") == []


# Signature


@pytest.mark.parametrize(
    "case",
    ["wrong-token", "no-header", "empty-header", "body-changed-after-signing", "internal-url"],
)
async def test_a_request_that_does_not_verify_is_refused_and_nothing_is_queued(
    sms_client: AsyncClient,
    sms_bus: ManualEventBus,
    sms_cache: InMemoryCache,
    reporter: None,
    case: str,
) -> None:
    params = reply_params(sid=SID)
    headers: dict[str, str]
    signed = {
        "wrong-token": sign(REPLY_URL, params, TENANT_B.token),
        "no-header": None,
        "empty-header": "",
        "body-changed-after-signing": sign(REPLY_URL, {**params, "Body": "5"}, TENANT_A.token),
        "internal-url": sign(INTERNAL_REPLY_URL, params, TENANT_A.token),
    }[case]
    headers = {} if signed is None else {"X-Twilio-Signature": signed}

    response = await sms_client.post(INTERNAL_REPLY_URL, data=params, headers=headers)

    assert response.status_code == 403
    assert response.text == REFUSED_BODY
    assert sms_bus.enqueued_to(QUEUE) == []
    assert await sms_cache.get(f"idem:sms:tenant-a:{SID}") is None


async def test_the_signature_is_over_the_public_url_from_settings_not_the_url_the_app_saw(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    # The app is reached at http://internal:8000 and Twilio signed https://diucs.example/...
    response = await post_signed(
        sms_client, reply_params(sid=SID), signed_url=REPLY_URL, send_to=INTERNAL_REPLY_URL
    )

    assert response.status_code == 200
    assert len(sms_bus.enqueued_to(QUEUE)) == 1


async def test_a_query_string_changes_the_url_and_so_fails_the_signature(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    params = reply_params(sid=SID)
    response = await sms_client.post(
        INTERNAL_REPLY_URL + "?tenant=tenant-b",
        data=params,
        headers={"X-Twilio-Signature": sign(REPLY_URL, params, TENANT_A.token)},
    )

    assert response.status_code == 403
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_the_signature_is_compared_in_constant_time(
    sms_client: AsyncClient, reporter: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = routes.hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(routes.hmac, "compare_digest", spy)
    await post_signed(sms_client, reply_params(sid=SID))

    assert len(calls) == 1


@pytest.mark.parametrize(
    "send",
    [
        "json-body",
        "text-plain-form",
        "duplicate-field",
        "too-large",
        "too-large-chunked",
        "too-many-fields",
        "not-utf8",
    ],
)
async def test_a_body_that_is_not_one_plain_twilio_form_is_refused(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None, send: str
) -> None:
    params = reply_params(sid=SID)
    signature = {"X-Twilio-Signature": sign(REPLY_URL, params, TENANT_A.token)}
    if send == "json-body":
        response = await sms_client.post(INTERNAL_REPLY_URL, json=params, headers=signature)
    elif send == "text-plain-form":
        # A correctly signed form, but not sent as a urlencoded form.
        response = await sms_client.post(
            INTERNAL_REPLY_URL,
            content=urlencode(params),
            headers={"content-type": "text/plain", **signature},
        )
    elif send == "duplicate-field":
        # Body is sent twice. The signature is valid over the value a reader keeping the last
        # one would see, so only the duplicate check can refuse it.
        content = "&".join(f"{name}={value}" for name, value in params.items()) + "&Body=5"
        last_wins = {**params, "Body": "5"}
        response = await sms_client.post(
            INTERNAL_REPLY_URL,
            content=content.replace("+", "%2B"),
            headers={**FORM, "X-Twilio-Signature": sign(REPLY_URL, last_wins, TENANT_A.token)},
        )
    elif send == "too-large":
        big = {**params, "Padding": "x" * 70_000}
        response = await sms_client.post(
            INTERNAL_REPLY_URL,
            data=big,
            headers={"X-Twilio-Signature": sign(REPLY_URL, big, TENANT_A.token)},
        )
    elif send == "too-large-chunked":
        # No Content-Length: the size is checked as the body arrives. The form is signed, so only
        # its size can refuse it.
        big = {**params, "Padding": "x" * 70_000}
        encoded = urlencode(big).encode()

        async def chunks() -> AsyncIterator[bytes]:
            for start in range(0, len(encoded), 4096):
                yield encoded[start : start + 4096]

        response = await sms_client.post(
            INTERNAL_REPLY_URL,
            content=chunks(),
            headers={**FORM, "X-Twilio-Signature": sign(REPLY_URL, big, TENANT_A.token)},
        )
    elif send == "too-many-fields":
        many = {**params, **{f"Extra{n}": "1" for n in range(120)}}
        response = await sms_client.post(
            INTERNAL_REPLY_URL,
            data=many,
            headers={"X-Twilio-Signature": sign(REPLY_URL, many, TENANT_A.token)},
        )
    else:
        response = await sms_client.post(
            INTERNAL_REPLY_URL, content=b"Body=\xff\xfe", headers={**FORM, **signature}
        )

    assert response.status_code == 403
    assert response.text == REFUSED_BODY
    assert sms_bus.enqueued_to(QUEUE) == []


# Allow-list


async def test_a_sender_not_in_neo4j_gets_the_same_answer_and_nothing_is_queued(
    sms_client: AsyncClient,
    sms_bus: ManualEventBus,
    sms_cache: InMemoryCache,
    reporter: None,
) -> None:
    accepted = await post_signed(sms_client, reply_params(sid=SID))
    unknown = await post_signed(
        sms_client, reply_params(sid="SM" + "2" * 32, sender=UNKNOWN_SENDER_E164)
    )

    _assert_empty_twiml(unknown.status_code, unknown.headers["content-type"], unknown.text)
    assert (unknown.status_code, unknown.headers["content-type"], unknown.text) == (
        accepted.status_code,
        accepted.headers["content-type"],
        accepted.text,
    )
    assert [m.id for m in sms_bus.enqueued_to(QUEUE)] == [SID]
    assert await sms_cache.get("idem:sms:tenant-a:" + "SM" + "2" * 32) is None


async def test_a_sender_who_is_not_a_uk_mobile_is_dropped_without_a_queue_message(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    for sender in (LANDLINE_E164, "Shop", ""):
        response = await post_signed(sms_client, reply_params(sid=SID, sender=sender))
        _assert_empty_twiml(response.status_code, response.headers["content-type"], response.text)
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_two_active_people_on_one_phone_are_ambiguous_and_nothing_is_queued(
    sms_client: AsyncClient, sms_bus: ManualEventBus, neo4j_driver: AsyncDriver, reporter: None
) -> None:
    await seed_practitioner(neo4j_driver, "p-reporter-2", SENDER_E164)

    response = await post_signed(sms_client, reply_params(sid=SID))

    _assert_empty_twiml(response.status_code, response.headers["content-type"], response.text)
    assert sms_bus.enqueued_to(QUEUE) == []


# Replay


async def test_the_same_message_sid_twice_is_answered_twice_and_queued_once(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    first = await post_signed(sms_client, reply_params(sid=SID))
    second = await post_signed(sms_client, reply_params(sid=SID))

    assert (first.status_code, first.text) == (200, TWIML)
    assert (second.status_code, second.headers["content-type"], second.text) == (
        200,
        "text/xml",
        TWIML,
    )
    assert len(sms_bus.enqueued_to(QUEUE)) == 1


async def test_the_replay_marker_is_a_day_long_and_tenant_prefixed(
    sms_client: AsyncClient, sms_cache: InMemoryCache, test_container: Container, reporter: None
) -> None:
    await post_signed(sms_client, reply_params(sid=SID))

    assert await sms_cache.get(f"idem:sms:tenant-a:{SID}") == "1"
    assert await sms_cache.get(f"idem:sms:tenant-b:{SID}") is None
    clock = test_container.clock
    assert isinstance(clock, FixedClock)
    clock.advance(timedelta(hours=24) - timedelta(seconds=1))
    assert await sms_cache.get(f"idem:sms:tenant-a:{SID}") == "1"
    clock.advance(timedelta(seconds=1))
    assert await sms_cache.get(f"idem:sms:tenant-a:{SID}") is None


async def test_a_failed_queue_send_gives_a_500_and_frees_the_marker_so_the_retry_is_queued(
    sms_client: AsyncClient,
    sms_bus: ManualEventBus,
    sms_cache: InMemoryCache,
    reporter: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_enqueue = sms_bus.enqueue
    failing = True

    async def flaky(queue: str, message: BusMessage) -> None:
        if failing:
            raise ConnectionError("bus down")
        await real_enqueue(queue, message)

    monkeypatch.setattr(sms_bus, "enqueue", flaky)

    first = await post_signed(sms_client, reply_params(sid=SID))
    assert first.status_code == 500
    assert await sms_cache.get(f"idem:sms:tenant-a:{SID}") is None
    assert sms_bus.enqueued_to(QUEUE) == []

    failing = False
    retry = await post_signed(sms_client, reply_params(sid=SID))
    assert retry.status_code == 200
    assert len(sms_bus.enqueued_to(QUEUE)) == 1


async def test_a_marker_that_cannot_be_removed_is_logged_by_class_and_the_answer_is_still_500(
    sms_client: AsyncClient,
    sms_bus: ManualEventBus,
    sms_cache: InMemoryCache,
    reporter: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def down(queue: str, message: BusMessage) -> None:
        raise ConnectionError("bus down")

    async def cannot_delete(key: str) -> None:
        raise OSError("cache down")

    monkeypatch.setattr(sms_bus, "enqueue", down)
    monkeypatch.setattr(sms_cache, "delete", cannot_delete)
    caplog.set_level(logging.DEBUG)

    response = await post_signed(sms_client, reply_params(sid=SID))

    assert response.status_code == 500
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "the replay marker could not be removed: OSError" in logged
    assert "cache down" not in logged


# Fields that cannot be queued


@pytest.mark.parametrize(
    "change",
    [
        {"Body": ""},
        {"Body": "   "},
        {"Body": "x" * 1601},
        {"MessageSid": ""},
        {"MessageSid": "SM:1"},
        {"MessageSid": "SM" + "9" * 70},
        {"From": ""},
    ],
    ids=["blank", "spaces", "too-long", "no-sid", "colon-in-sid", "long-sid", "no-sender"],
)
async def test_a_verified_message_with_no_usable_field_is_dropped_without_a_queue_message(
    sms_client: AsyncClient,
    sms_bus: ManualEventBus,
    sms_cache: InMemoryCache,
    reporter: None,
    change: dict[str, str],
) -> None:
    params = {**reply_params(sid=SID), **change}

    response = await post_signed(sms_client, params)

    _assert_empty_twiml(response.status_code, response.headers["content-type"], response.text)
    assert sms_bus.enqueued_to(QUEUE) == []


async def test_a_body_of_exactly_1600_characters_is_queued_unchanged(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    text = "y" * 1600
    await post_signed(sms_client, reply_params(sid=SID, text=text))

    [queued] = sms_bus.enqueued_to(QUEUE)
    assert queued.payload["text"] == text


async def test_a_missing_message_sid_field_is_dropped(
    sms_client: AsyncClient, sms_bus: ManualEventBus, reporter: None
) -> None:
    params = reply_params(sid=SID)
    del params["MessageSid"]

    response = await post_signed(sms_client, params)

    assert response.status_code == 200
    assert sms_bus.enqueued_to(QUEUE) == []


# Method and wiring


async def test_a_get_is_not_allowed(sms_client: AsyncClient) -> None:
    response = await sms_client.get(INTERNAL_REPLY_URL)
    assert response.status_code == 405


async def test_a_text_form_is_not_refused_as_a_415_by_the_fhir_body_check(
    sms_client: AsyncClient, reporter: None
) -> None:
    response = await post_signed(sms_client, reply_params(sid=SID))
    assert response.status_code != 415


async def test_an_app_without_the_webhook_collaborators_fails_closed(api_app: FastAPI) -> None:
    assert not hasattr(api_app.state, "sms_webhook")
    async with AsyncClient(
        transport=ASGITransport(app=api_app, raise_app_exceptions=False),
        base_url="http://internal:8000",
    ) as client:
        response = await post_signed(client, reply_params(sid=SID))
    assert response.status_code == 500


# Logging


async def test_nothing_secret_or_personal_is_logged(
    sms_client: AsyncClient,
    sms_bus: ManualEventBus,
    reporter: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    secret_text = "private-words-in-a-reply"
    await post_signed(sms_client, reply_params(sid=SID, text=secret_text))
    await post_signed(sms_client, reply_params(sid="SM" + "3" * 32, sender=UNKNOWN_SENDER_E164))
    await post_signed(sms_client, reply_params(sid="SM" + "4" * 32), token=b"wrong")
    await post_signed(sms_client, reply_params(sid=SID, text=secret_text))

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert SID in logged  # the Twilio message id is what a log line may carry
    for forbidden in (
        secret_text,
        "7700900123",
        "7700 900123",
        "7700900456",
        phone_hash(SENDER_E164),
        TENANT_A.token.decode(),
        TENANT_B.token.decode(),
    ):
        assert forbidden not in logged
