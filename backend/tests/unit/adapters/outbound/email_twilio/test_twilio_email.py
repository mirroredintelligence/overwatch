"""Twilio Email adapter (deployment-plan item 6, DEC-131 correction, DEC-1130).

Twilio is an external provider, so every call goes through an httpx MockTransport: no network, no
Twilio account, no real email. All values are placeholders. The send answers 202 (queued), not
delivered: delivery comes from the Operation read, which maps to the same delivered or failed
model as a text.
"""

import base64
import json
import logging

import httpx
import pytest

from diucs.adapters.outbound.email_twilio.twilio_email import (
    EMAILS_URL,
    OPERATION_URL,
    TwilioEmail,
    map_operation,
)
from diucs.application.ports.outbound.messaging import (
    DeliveryUpdate,
    SendFailedError,
    SendReceipt,
    TransientSendError,
)

ACCOUNT = "AC" + "0" * 32  # placeholder, not a real account SID
TOKEN = "placeholder-auth-token-canary-7"
FROM = "capacity@example-icb.test"
NAME = "Example capacity"
TO = "west-ucr@example-icb.test"
SUBJECT = "Capacity: please confirm"
TEXT = "Confirm or update: https://diucs.example/l/abc\n\nReplies to this address are not read."
HTML = "<p>Confirm</p>"
OPERATION = "op_0123456789abcdef"


def _email(client: httpx.AsyncClient, name: str | None = NAME) -> TwilioEmail:
    return TwilioEmail(client, ACCOUNT, TOKEN, FROM, name)


def _recording(response: httpx.Response) -> tuple[list[httpx.Request], httpx.MockTransport]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return seen, httpx.MockTransport(handler)


def _accepted() -> httpx.Response:
    return httpx.Response(
        202,
        json={"operationId": OPERATION, "operationLocation": f"{OPERATION_URL}{OPERATION}"},
    )


async def test_send_posts_json_to_the_emails_endpoint_with_basic_auth() -> None:
    seen, transport = _recording(_accepted())
    async with httpx.AsyncClient(transport=transport) as client:
        receipt = await _email(client).send(TO, SUBJECT, TEXT, HTML)

    assert receipt == SendReceipt(OPERATION, True)
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == "https://comms.twilio.com/v1/Emails" == EMAILS_URL
    assert request.headers["content-type"].startswith("application/json")
    expected = "Basic " + base64.b64encode(f"{ACCOUNT}:{TOKEN}".encode()).decode()
    assert request.headers["authorization"] == expected


async def test_the_body_names_the_sender_the_one_recipient_the_subject_and_both_parts() -> None:
    seen, transport = _recording(_accepted())
    async with httpx.AsyncClient(transport=transport) as client:
        await _email(client).send(TO, SUBJECT, TEXT, HTML)

    body = json.loads(seen[0].content)
    assert body["from"] == {"address": FROM, "name": NAME}
    assert body["to"] == [{"address": TO}]
    assert body["content"]["subject"] == SUBJECT
    assert body["content"]["text"] == TEXT
    assert body["content"]["html"] == HTML


async def test_with_no_html_the_text_is_sent_alone_and_with_no_name_the_address_is() -> None:
    seen, transport = _recording(_accepted())
    async with httpx.AsyncClient(transport=transport) as client:
        await _email(client, name=None).send(TO, SUBJECT, TEXT, None)

    body = json.loads(seen[0].content)
    assert body["from"] == {"address": FROM}
    assert "html" not in body["content"]


async def test_the_202_with_no_operation_id_is_a_fault_not_a_success() -> None:
    _, transport = _recording(httpx.Response(202, json={"operationLocation": "x"}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _email(client).send(TO, SUBJECT, TEXT, None)


@pytest.mark.parametrize(
    "body", [b"not json", b"[]", b'{"operationId": 7}', b'{"operationId": ""}']
)
async def test_a_202_body_that_cannot_be_read_is_a_fault(body: bytes) -> None:
    _, transport = _recording(httpx.Response(202, content=body))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _email(client).send(TO, SUBJECT, TEXT, None)


@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_a_busy_or_failing_provider_is_transient(status: int) -> None:
    _, transport = _recording(httpx.Response(status, json={"status": status}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(TransientSendError):
            await _email(client).send(TO, SUBJECT, TEXT, None)


async def test_a_lost_connection_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TransientSendError):
            await _email(client).send(TO, SUBJECT, TEXT, None)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_any_other_refusal_is_a_fault_that_a_retry_will_not_fix(status: int) -> None:
    # An unverified sender, bad credentials or a bad request: the tenant's set-up, not the message.
    _, transport = _recording(httpx.Response(status, json={"code": 99999, "message": TO}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError) as failed:
            await _email(client).send(TO, SUBJECT, TEXT, None)

    assert TO not in str(failed.value)
    assert str(status) in str(failed.value)


@pytest.mark.parametrize(
    "address",
    [
        "",
        "no-at-sign",
        "a@b",
        "a b@example.test",
        "a@example.test, b@example.test",
        "<a@example.test>",
    ],
)
async def test_an_address_that_is_not_one_role_inbox_is_refused_before_any_call(
    address: str,
) -> None:
    seen, transport = _recording(_accepted())
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _email(client).send(address, SUBJECT, TEXT, None)

    assert seen == []


@pytest.mark.parametrize("subject", ["", "  ", "Line\nbreak", "Tab\there"])
async def test_a_subject_that_is_empty_or_has_a_line_break_is_refused(subject: str) -> None:
    seen, transport = _recording(_accepted())
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _email(client).send(TO, subject, TEXT, None)

    assert seen == []


async def test_an_empty_text_is_refused() -> None:
    seen, transport = _recording(_accepted())
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _email(client).send(TO, SUBJECT, "  ", None)

    assert seen == []


def test_a_sender_address_that_is_not_an_address_is_refused_when_built() -> None:
    with pytest.raises(ValueError):
        TwilioEmail(httpx.AsyncClient(), ACCOUNT, TOKEN, "not-an-address", None)
    with pytest.raises(ValueError):
        TwilioEmail(httpx.AsyncClient(), ACCOUNT, TOKEN, FROM, "Bad\nName")


def test_the_adapter_does_not_show_the_token_in_repr_or_str() -> None:
    email = TwilioEmail(httpx.AsyncClient(), ACCOUNT, TOKEN, FROM, NAME)

    assert TOKEN not in repr(email) + str(email)
    assert ACCOUNT not in repr(email) + str(email)


async def test_nothing_that_identifies_a_person_or_a_secret_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    for response in (_accepted(), httpx.Response(503), httpx.Response(401, json={"code": 1})):
        _, transport = _recording(response)
        async with httpx.AsyncClient(transport=transport) as client:
            try:
                await _email(client).send(TO, SUBJECT, TEXT, HTML)
            except SendFailedError, TransientSendError:
                pass

    logged = caplog.text
    for secret in (TO, TOKEN, TEXT, SUBJECT, "diucs.example/l/abc", ACCOUNT):
        assert secret not in logged
    assert OPERATION in logged  # the provider id of the one accepted send


# The Operation read: GET /v1/Emails/Operations/{id}, mapped to the model of a text


def _operation(status: str, **counts: int) -> dict[str, object]:
    return {"operationId": OPERATION, "status": status, "counts": counts}


@pytest.mark.parametrize("status", ["SCHEDULED", "PROCESSING"])
def test_an_operation_still_to_run_is_queued(status: str) -> None:
    assert map_operation(_operation(status, total=1, queued=1)) == DeliveryUpdate(
        OPERATION, "queued", None
    )


def test_a_completed_operation_with_a_delivered_email_is_delivered() -> None:
    body = _operation("COMPLETED", total=1, delivered=1)

    assert map_operation(body) == DeliveryUpdate(OPERATION, "delivered", None)


def test_a_completed_operation_the_server_accepted_but_not_confirmed_is_sent() -> None:
    assert map_operation(_operation("COMPLETED", total=1, sent=1)) == DeliveryUpdate(
        OPERATION, "sent", None
    )


@pytest.mark.parametrize(
    ("counts", "code"),
    [({"total": 1, "undelivered": 1}, "undelivered"), ({"total": 1, "failed": 1}, "failed")],
)
def test_a_completed_operation_with_a_failure_is_failed_with_a_fixed_code(
    counts: dict[str, int], code: str
) -> None:
    assert map_operation(_operation("COMPLETED", **counts)) == DeliveryUpdate(
        OPERATION, "failed", code
    )


def test_a_failure_wins_over_a_delivery_so_a_lost_email_is_never_called_delivered() -> None:
    body = _operation("COMPLETED", total=2, delivered=1, failed=1)

    assert map_operation(body).status == "failed"


def test_a_canceled_operation_is_failed() -> None:
    assert map_operation(_operation("CANCELED", total=1, canceled=1)) == DeliveryUpdate(
        OPERATION, "failed", "canceled"
    )


def test_a_completed_operation_with_no_count_that_says_anything_is_still_queued() -> None:
    assert map_operation(_operation("COMPLETED", total=1)).status == "queued"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"operationId": OPERATION},
        {"status": "COMPLETED"},
        {"operationId": OPERATION, "status": "WEIRD"},
        {"operationId": OPERATION, "status": "completed"},
        {"operationId": OPERATION, "status": "COMPLETED", "counts": {"delivered": "1"}},
        {"operationId": OPERATION, "status": "COMPLETED", "counts": {"delivered": -1}},
        {"operationId": 7, "status": "COMPLETED"},
        [],
    ],
)
def test_an_operation_that_cannot_be_read_is_a_value_error(body: object) -> None:
    with pytest.raises(ValueError):
        map_operation(body)


async def test_operation_update_reads_the_operation_with_basic_auth() -> None:
    seen, transport = _recording(httpx.Response(200, json=_operation("COMPLETED", delivered=1)))
    async with httpx.AsyncClient(transport=transport) as client:
        update = await _email(client).operation_update(OPERATION)

    assert update == DeliveryUpdate(OPERATION, "delivered", None)
    (request,) = seen
    assert request.method == "GET"
    assert str(request.url) == f"https://comms.twilio.com/v1/Emails/Operations/{OPERATION}"
    assert request.headers["authorization"].startswith("Basic ")


@pytest.mark.parametrize("operation_id", ["", "../Emails", "a/b", "a b", "x" * 65, "op?x=1"])
async def test_an_operation_id_that_could_change_the_path_is_refused_before_any_call(
    operation_id: str,
) -> None:
    seen, transport = _recording(httpx.Response(200, json=_operation("COMPLETED", delivered=1)))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError):
            await _email(client).operation_update(operation_id)

    assert seen == []


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_busy_provider_on_the_operation_read_is_transient(status: int) -> None:
    _, transport = _recording(httpx.Response(status))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(TransientSendError):
            await _email(client).operation_update(OPERATION)


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_a_refused_operation_read_is_a_fault(status: int) -> None:
    _, transport = _recording(httpx.Response(status))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _email(client).operation_update(OPERATION)


async def test_an_operation_read_whose_answer_is_not_an_operation_is_a_fault() -> None:
    _, transport = _recording(httpx.Response(200, json={"status": "WEIRD"}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SendFailedError):
            await _email(client).operation_update(OPERATION)
