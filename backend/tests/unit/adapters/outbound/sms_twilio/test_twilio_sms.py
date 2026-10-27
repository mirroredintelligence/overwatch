"""Twilio SMS adapter (I06, DEC-002). Twilio is an external provider, so every call goes through
an httpx MockTransport: no network, no Twilio account, no real message. All values are placeholders.
"""

import base64
import logging
from collections.abc import Iterator
from urllib.parse import parse_qs

import httpx
import pytest

from diucs.adapters.outbound.sms_twilio.twilio_sms import (
    TwilioSms,
    parse_status_callback,
    to_e164_uk,
)
from diucs.application.ports.outbound.messaging import (
    DeliveryUpdate,
    SendFailedError,
    SendReceipt,
    TransientSendError,
)

ACCOUNT = "AC" + "0" * 32  # placeholder, not a real account SID
TOKEN = "placeholder-auth-token"
SENDER = "DIUCS-TEST"
CALLBACK = "https://diucs.example/webhooks/sms/twilio/status"
MESSAGES_URL = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Messages.json"
NUMBER = "07700 900123"
E164 = "+447700900123"
BODY = "DIUCS: test message for the adapter"
SID = "SM" + "1" * 32


def _sms(client: httpx.AsyncClient) -> TwilioSms:
    return TwilioSms(client, ACCOUNT, TOKEN, SENDER, CALLBACK)


@pytest.fixture(autouse=True)
def _restore_httpx_log_level() -> Iterator[None]:
    """The httpx logger is process-wide; each test starts and ends with it unset (DEC-103 item 2)."""
    logger = logging.getLogger("httpx")
    saved = logger.level
    logger.setLevel(logging.NOTSET)
    yield
    logger.setLevel(saved)


def _recording(response: httpx.Response) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return seen, httpx.MockTransport(handler)


async def test_send_posts_the_form_with_basic_auth_and_returns_the_sid() -> None:
    seen, transport = _recording(httpx.Response(201, json={"sid": SID, "status": "queued"}))
    async with httpx.AsyncClient(transport=transport) as client:
        receipt = await _sms(client).send(NUMBER, BODY, "C1")
    assert receipt == SendReceipt(SID, True)
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == MESSAGES_URL
    assert parse_qs(request.content.decode()) == {
        "To": [E164],
        "From": [SENDER],
        "Body": [BODY],
        "StatusCallback": [CALLBACK],
    }
    expected = "Basic " + base64.b64encode(f"{ACCOUNT}:{TOKEN}".encode()).decode()
    assert request.headers["authorization"] == expected


@pytest.mark.parametrize("code", [21211, 21614, 21610])
async def test_a_listed_refusal_is_not_accepted(code: int) -> None:
    _, transport = _recording(
        httpx.Response(400, json={"code": code, "message": "refused", "status": 400})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        receipt = await _sms(client).send(NUMBER, BODY, "C1")
    assert receipt == SendReceipt("", False)


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_busy_or_failing_provider_raises_transient(status: int) -> None:
    _, transport = _recording(httpx.Response(status, json={"status": status}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(TransientSendError):
            await _sms(client).send(NUMBER, BODY, "C1")


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
async def test_a_timeout_or_dropped_connection_raises_transient(
    error: type[httpx.TransportError],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error("no answer", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TransientSendError):
            await _sms(client).send(NUMBER, BODY, "C1")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"code": 20003, "status": 401}),
        httpx.Response(400, json={"code": 21602, "status": 400}),
    ],
)
async def test_an_unlisted_refusal_is_a_failure_not_a_receipt(response: httpx.Response) -> None:
    _, transport = _recording(response)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _sms(client).send(NUMBER, BODY, "C1")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(201, json={"status": "queued"}),
        httpx.Response(201, text="accepted"),
    ],
)
async def test_an_accepted_send_with_no_sid_is_a_failure_not_a_receipt(
    response: httpx.Response,
) -> None:
    _, transport = _recording(response)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _sms(client).send(NUMBER, BODY, "C1")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, text="not json"),
        httpx.Response(400, json=["not", "a", "dict"]),
        httpx.Response(400, json={"status": 400}),
    ],
)
async def test_a_refusal_with_no_usable_code_is_a_failure_not_a_receipt(
    response: httpx.Response,
) -> None:
    _, transport = _recording(response)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _sms(client).send(NUMBER, BODY, "C1")


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("07700 900123", "+447700900123"),
        ("07700900123", "+447700900123"),
        ("+44 7700 900123", "+447700900123"),
        ("+44 (0)7700 900123", "+447700900123"),
        ("0044 7700 900123", "+447700900123"),
        ("447700900123", "+447700900123"),
    ],
)
def test_a_uk_mobile_is_normalised_to_e164(number: str, expected: str) -> None:
    assert to_e164_uk(number) == expected


@pytest.mark.parametrize("number", ["12345", "02079460000", "", "07700 90012X"])
def test_a_number_that_is_not_a_uk_mobile_is_refused(number: str) -> None:
    with pytest.raises(ValueError):
        to_e164_uk(number)


def test_the_refusal_does_not_echo_the_number() -> None:
    with pytest.raises(ValueError) as refused:
        to_e164_uk("07700 90012X")
    assert "90012X" not in str(refused.value)


async def test_an_invalid_number_or_empty_text_makes_no_request() -> None:
    seen, transport = _recording(httpx.Response(201, json={"sid": SID}))
    async with httpx.AsyncClient(transport=transport) as client:
        sms = _sms(client)
        with pytest.raises(ValueError):
            await sms.send("12345", BODY, "C1")
        with pytest.raises(ValueError):
            await sms.send(NUMBER, "", "C1")
    assert seen == []


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        (
            {"MessageSid": "SM1", "MessageStatus": "undelivered", "ErrorCode": "30003"},
            DeliveryUpdate("SM1", "failed", "30003"),
        ),
        ({"MessageSid": "SM2", "MessageStatus": "failed"}, DeliveryUpdate("SM2", "failed", None)),
        (
            {"MessageSid": "SM3", "MessageStatus": "failed", "ErrorCode": ""},
            DeliveryUpdate("SM3", "failed", None),
        ),
        ({"MessageSid": "SM4", "MessageStatus": "queued"}, DeliveryUpdate("SM4", "queued", None)),
        ({"MessageSid": "SM5", "MessageStatus": "sending"}, DeliveryUpdate("SM5", "queued", None)),
        ({"MessageSid": "SM6", "MessageStatus": "sent"}, DeliveryUpdate("SM6", "sent", None)),
        (
            {"MessageSid": "SM7", "MessageStatus": "delivered"},
            DeliveryUpdate("SM7", "delivered", None),
        ),
    ],
)
def test_a_status_callback_maps_to_a_delivery_update(
    form: dict[str, str], expected: DeliveryUpdate
) -> None:
    assert parse_status_callback(form) == expected


@pytest.mark.parametrize(
    "form",
    [
        {"MessageSid": "SM1", "MessageStatus": "accepted"},
        {"MessageStatus": "sent"},
        {"MessageSid": "SM1"},
    ],
)
def test_an_unknown_or_incomplete_status_callback_is_refused(form: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        parse_status_callback(form)


async def test_the_log_holds_the_message_id_and_sid_but_never_the_number_or_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, transport = _recording(httpx.Response(201, json={"sid": SID}))
    async with httpx.AsyncClient(transport=transport) as client:
        await _sms(client).send(NUMBER, BODY, "C1")
    assert SID in caplog.text
    assert "C1" in caplog.text
    assert "07700" not in caplog.text
    assert E164 not in caplog.text
    assert BODY not in caplog.text


async def test_a_refusal_is_logged_without_the_number_or_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    _, transport = _recording(httpx.Response(400, json={"code": 21211, "status": 400}))
    async with httpx.AsyncClient(transport=transport) as client:
        await _sms(client).send(NUMBER, BODY, "C1")
    assert "C1" in caplog.text
    assert "21211" in caplog.text
    assert "07700" not in caplog.text
    assert E164 not in caplog.text
    assert BODY not in caplog.text
    assert TOKEN not in caplog.text


def test_constructing_the_adapter_holds_httpx_logging_at_warning() -> None:
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    _, transport = _recording(httpx.Response(201, json={"sid": SID}))
    _sms(httpx.AsyncClient(transport=transport))
    assert logging.getLogger("httpx").level == logging.WARNING


async def test_a_send_logs_no_info_line_that_carries_the_account_sid(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    _, transport = _recording(httpx.Response(201, json={"sid": SID}))
    async with httpx.AsyncClient(transport=transport) as client:
        await _sms(client).send(NUMBER, BODY, "C1")
    assert SID in caplog.text
    for record in caplog.records:
        if record.levelno <= logging.INFO:
            assert ACCOUNT not in record.getMessage()
