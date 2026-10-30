"""Tests for the SMTP email adapter (I09, DEC-110).

The SMTP server is an in-process aiosmtpd controller on 127.0.0.1, so no mail leaves the machine.
Neo4j is not needed. Test addresses and bodies are synthetic markers, never patient data.
"""

import email
import logging
import re
import socket
from email import policy
from email.message import EmailMessage
from typing import Any

import pytest
from aiosmtpd.controller import Controller
from pydantic import SecretStr

from diucs.adapters.outbound.email_smtp.smtp_email import (
    SmtpEmail,
    SmtpIdentity,
    SmtpRelay,
    build_message,
    text_to_html,
)
from diucs.application.ports.outbound.messaging import (
    SendFailedError,
    SendReceipt,
    TransientSendError,
)
from diucs.domain.codes import Channel
from diucs.domain.messages.templates import MessageId, render

FROM = "DIUCS Capacity <capacity@diucs.example>"
TO = "role.inbox-7731@diucs.example"
SUBJECT = "UCR West: confirm or update by 10:30"
TEXT = "DIUCS: UCR West. Confirm or update: https://diucs.example/l/Qk3-x9_Tz0aBc12345abc"
HTML = "<p>DIUCS: UCR West.</p>"
LINK = "https://diucs.example/l/Qk3-x9_Tz0aBc12345abc"
MSG_ID = "<7f1c2a84-9d3e-4b6a-8c21-5e0f4d9a7b33@diucs.example>"
MARKER_BODY = "marker-body-7731"
MARKER_ADDRESS = "role.marker-7731@diucs.example"


class RecordingHandler:
    """Records each message the in-process server accepts. A reply attribute, when set, is sent
    instead of accepting the step, so a test can make the server refuse or defer it."""

    def __init__(self) -> None:
        self.messages: list[tuple[list[str], bytes]] = []
        self.rcpt_reply: str | None = None
        self.data_reply: str | None = None

    async def handle_RCPT(  # noqa: N802 - aiosmtpd hook name
        self,
        server: Any,
        session: Any,
        envelope: Any,
        address: str,
        rcpt_options: list[str],
    ) -> str:
        if self.rcpt_reply is not None:
            return self.rcpt_reply
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:  # noqa: N802
        if self.data_reply is not None:
            return self.data_reply
        self.messages.append((list(envelope.rcpt_tos), bytes(envelope.content)))
        return "250 Message accepted for delivery"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def smtp_server() -> Any:
    handler = RecordingHandler()
    port = _free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield handler, port
    finally:
        controller.stop()


IDENTITY = SmtpIdentity(from_address="capacity@diucs.example", display_name="DIUCS Capacity")


def relay_for(port: int) -> SmtpRelay:
    return SmtpRelay(host="127.0.0.1", port=port, starttls=False)


def test_build_message_is_multipart_alternative_with_text_then_html() -> None:
    msg = build_message(
        to=TO, subject=SUBJECT, text=TEXT, html=HTML, from_addr=FROM, message_id=MSG_ID
    )

    assert isinstance(msg, EmailMessage)
    assert msg.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in msg.iter_parts()] == ["text/plain", "text/html"]
    assert msg["From"] == FROM
    assert msg["To"] == TO
    assert msg["Subject"] == SUBJECT
    assert msg["Message-ID"] == MSG_ID
    assert msg["Auto-Submitted"] == "auto-generated"


def test_text_to_html_escapes_and_turns_the_one_link_into_one_labelled_anchor() -> None:
    text = f"Ward 3 < 4 & 5 beds.\n\nConfirm or update: {LINK}\n\nThe link works once."

    html = text_to_html(text, "Confirm or update")

    assert "&lt;" in html
    assert "&amp;" in html
    assert "< 4" not in html
    assert "& 5" not in html
    assert html.count("<a ") == 1
    assert f'href="{LINK}"' in html
    assert ">Confirm or update</a>" in html
    assert html.count("Confirm or update") == 1


def test_the_capacity_email_for_ucr_west_has_its_subject_and_footer() -> None:
    rendered = render(
        MessageId.C1,
        Channel.EMAIL,
        service="UCR West",
        value=3,
        unit="referrals",
        as_of="10:10",
        reply_by="10:30",
        link=LINK,
    )

    assert rendered.subject == "UCR West: confirm or update by 10:30"
    assert rendered.html is not None
    assert "The link works once, needs no login, and expires at 10:30." in rendered.text
    assert "This email has no patient information." in rendered.text
    assert "Replies to this address are not read." in rendered.text


async def test_send_delivers_one_message_with_both_parts(smtp_server: Any) -> None:
    handler, port = smtp_server

    receipt = await SmtpEmail(relay_for(port), IDENTITY).send(TO, SUBJECT, TEXT, HTML)

    assert receipt.accepted is True
    assert re.fullmatch(r"<[0-9a-f-]{36}@diucs\.example>", receipt.provider_message_id)
    assert len(handler.messages) == 1
    recipients, raw = handler.messages[0]
    assert recipients == [TO]
    received = email.message_from_bytes(raw, policy=policy.default)
    assert received.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in received.iter_parts()] == [
        "text/plain",
        "text/html",
    ]
    assert received["Message-ID"] == receipt.provider_message_id
    assert received["Auto-Submitted"] == "auto-generated"
    assert received["From"] == FROM


async def test_each_send_gets_its_own_message_id(smtp_server: Any) -> None:
    _, port = smtp_server
    sender = SmtpEmail(relay_for(port), IDENTITY)

    first = await sender.send(TO, SUBJECT, TEXT, HTML)
    second = await sender.send(TO, SUBJECT, TEXT, HTML)

    assert first.provider_message_id != second.provider_message_id


async def test_a_text_only_message_gets_a_generated_html_part(smtp_server: Any) -> None:
    handler, port = smtp_server

    await SmtpEmail(relay_for(port), IDENTITY).send(
        TO, "Review request", "Review request: " + LINK, None
    )

    _, raw = handler.messages[0]
    received = email.message_from_bytes(raw, policy=policy.default)
    html_part = received.get_body(("html",))
    assert html_part is not None
    html = html_part.get_content()
    assert html.count("<a ") == 1
    assert f'href="{LINK}"' in html
    assert ">Review request</a>" in html


async def test_a_4xx_answer_is_transient_and_nothing_is_stored(smtp_server: Any) -> None:
    handler, port = smtp_server
    handler.rcpt_reply = "451 4.3.0 try again later"

    with pytest.raises(TransientSendError):
        await SmtpEmail(relay_for(port), IDENTITY).send(TO, SUBJECT, TEXT, HTML)

    assert handler.messages == []


async def test_a_550_refused_recipient_is_not_accepted(smtp_server: Any) -> None:
    handler, port = smtp_server
    handler.rcpt_reply = "550 5.1.1 mailbox unavailable"

    receipt = await SmtpEmail(relay_for(port), IDENTITY).send(TO, SUBJECT, TEXT, HTML)

    assert receipt == SendReceipt(provider_message_id="", accepted=False)
    assert handler.messages == []


async def test_a_5xx_answer_to_the_message_is_a_failure_and_is_not_retried(
    smtp_server: Any,
) -> None:
    handler, port = smtp_server
    handler.data_reply = "554 5.7.1 message rejected"

    with pytest.raises(SendFailedError):
        await SmtpEmail(relay_for(port), IDENTITY).send(TO, SUBJECT, TEXT, HTML)

    assert handler.messages == []


async def test_no_server_listening_is_transient() -> None:
    port = _free_port()

    with pytest.raises(TransientSendError):
        await SmtpEmail(relay_for(port), IDENTITY).send(TO, SUBJECT, TEXT, HTML)


async def test_logs_hold_neither_the_address_nor_the_body(
    smtp_server: Any, caplog: pytest.LogCaptureFixture
) -> None:
    _, port = smtp_server
    caplog.set_level(logging.DEBUG)

    receipt = await SmtpEmail(relay_for(port), IDENTITY).send(
        MARKER_ADDRESS,
        SUBJECT,
        f"{MARKER_BODY} text",
        f"<p>{MARKER_BODY} html</p>",
    )

    # The in-process server stands in for the relay and logs what it receives under "mail.log".
    # Its log is not the adapter's, so only the other records are checked.
    adapter_log = "\n".join(
        f"{record.name} {record.getMessage()}"
        for record in caplog.records
        if not record.name.startswith("mail.log")
    )
    assert receipt.accepted is True
    assert MARKER_ADDRESS not in adapter_log
    assert MARKER_BODY not in adapter_log
    assert receipt.provider_message_id in adapter_log


def _adapter_log(caplog: pytest.LogCaptureFixture) -> str:
    # The in-process server logs under "mail.log" (it stands in for the relay). Only the
    # adapter's own records are checked.
    return "\n".join(
        f"{record.name} {record.getMessage()}"
        for record in caplog.records
        if not record.name.startswith("mail.log")
    )


async def test_the_refusal_log_holds_neither_the_address_nor_the_body(
    smtp_server: Any, caplog: pytest.LogCaptureFixture
) -> None:
    # The relay's reply echoes the address and the body text; neither may reach the adapter's log.
    handler, port = smtp_server
    handler.rcpt_reply = f"550 5.1.1 <{MARKER_ADDRESS}> no such mailbox {MARKER_BODY}"
    caplog.set_level(logging.DEBUG)

    receipt = await SmtpEmail(relay_for(port), IDENTITY).send(
        MARKER_ADDRESS, SUBJECT, f"{MARKER_BODY} text", f"<p>{MARKER_BODY} html</p>"
    )

    assert receipt.accepted is False
    assert MARKER_ADDRESS not in _adapter_log(caplog)
    assert MARKER_BODY not in _adapter_log(caplog)


async def test_the_deferral_log_holds_neither_the_address_nor_the_body(
    smtp_server: Any, caplog: pytest.LogCaptureFixture
) -> None:
    handler, port = smtp_server
    handler.rcpt_reply = f"451 4.3.0 <{MARKER_ADDRESS}> try later {MARKER_BODY}"
    caplog.set_level(logging.DEBUG)

    with pytest.raises(TransientSendError):
        await SmtpEmail(relay_for(port), IDENTITY).send(
            MARKER_ADDRESS, SUBJECT, f"{MARKER_BODY} text", f"<p>{MARKER_BODY} html</p>"
        )

    assert MARKER_ADDRESS not in _adapter_log(caplog)
    assert MARKER_BODY not in _adapter_log(caplog)


async def test_the_failure_log_holds_neither_the_address_nor_the_body(
    smtp_server: Any, caplog: pytest.LogCaptureFixture
) -> None:
    handler, port = smtp_server
    handler.data_reply = f"554 5.7.1 rejected {MARKER_BODY} for {MARKER_ADDRESS}"
    caplog.set_level(logging.DEBUG)

    with pytest.raises(SendFailedError):
        await SmtpEmail(relay_for(port), IDENTITY).send(
            MARKER_ADDRESS, SUBJECT, f"{MARKER_BODY} text", f"<p>{MARKER_BODY} html</p>"
        )

    assert MARKER_ADDRESS not in _adapter_log(caplog)
    assert MARKER_BODY not in _adapter_log(caplog)


async def test_an_unconfigured_relay_is_a_failure_and_sends_nothing() -> None:
    # No SMTP host: the adapter must refuse, never fall back to a local relay.
    with pytest.raises(SendFailedError):
        await SmtpEmail(SmtpRelay(host=None), IDENTITY).send(TO, SUBJECT, TEXT, HTML)


def test_text_on_either_side_of_the_link_becomes_its_own_paragraph() -> None:
    text = f"Ward summary line. {LINK} Thanks for your time."

    html = text_to_html(text, "Confirm or update")

    assert "<p>Ward summary line.</p>" in html
    assert "<p>Thanks for your time.</p>" in html
    assert html.count("<a ") == 1


def test_a_text_without_a_link_gets_no_anchor() -> None:
    html = text_to_html("No link here.", "Confirm or update")

    assert "<p>No link here.</p>" in html
    assert "<a " not in html


async def test_a_4xx_answer_to_the_message_is_transient(smtp_server: Any) -> None:
    handler, port = smtp_server
    handler.data_reply = "451 4.3.0 try again later"

    with pytest.raises(TransientSendError):
        await SmtpEmail(relay_for(port), IDENTITY).send(TO, SUBJECT, TEXT, HTML)

    assert handler.messages == []


async def test_a_text_only_message_without_a_link_still_gets_an_html_part(
    smtp_server: Any,
) -> None:
    handler, port = smtp_server

    await SmtpEmail(relay_for(port), IDENTITY).send(TO, "Notice", "No link here.", None)

    _, raw = handler.messages[0]
    received = email.message_from_bytes(raw, policy=policy.default)
    html_part = received.get_body(("html",))
    assert html_part is not None
    assert "<a " not in html_part.get_content()


# One relay, one identity for each tenant (TEN-042, DEC-131 item 1)


class _CapturedSend:
    """Stands in for `aiosmtplib.send`: records what the adapter hands it, sends nothing."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, message: EmailMessage, **kwargs: Any) -> None:
        self.calls.append({"message": message, **kwargs})


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> _CapturedSend:
    captured_send = _CapturedSend()
    monkeypatch.setattr("aiosmtplib.send", captured_send)
    return captured_send


ALPHA = SmtpIdentity(
    from_address="capacity@alpha.example.test",
    display_name="Alpha Capacity",
    username="capacity@alpha.example.test",
    password=SecretStr("alpha-secret-canary-0001"),
)
BRAVO = SmtpIdentity(from_address="ops@bravo.example.test")
RELAY = SmtpRelay(host="relay.example.test", port=2525, starttls=True)


async def test_each_identity_sends_from_its_own_address_through_the_one_relay(
    captured: _CapturedSend,
) -> None:
    await SmtpEmail(RELAY, ALPHA).send(TO, SUBJECT, TEXT, HTML)
    await SmtpEmail(RELAY, BRAVO).send(TO, SUBJECT, TEXT, HTML)

    first, second = captured.calls
    assert first["message"]["From"] == "Alpha Capacity <capacity@alpha.example.test>"
    assert second["message"]["From"] == "ops@bravo.example.test"
    for call in (first, second):
        assert (call["hostname"], call["port"], call["start_tls"]) == (
            "relay.example.test",
            2525,
            True,
        )


async def test_the_message_id_is_in_the_domain_of_the_senders_own_address(
    captured: _CapturedSend,
) -> None:
    first = await SmtpEmail(RELAY, ALPHA).send(TO, SUBJECT, TEXT, HTML)
    second = await SmtpEmail(RELAY, BRAVO).send(TO, SUBJECT, TEXT, HTML)

    assert re.fullmatch(r"<[0-9a-f-]{36}@alpha\.example\.test>", first.provider_message_id)
    assert re.fullmatch(r"<[0-9a-f-]{36}@bravo\.example\.test>", second.provider_message_id)
    assert "diucs.example" not in first.provider_message_id


async def test_the_credentials_are_the_identitys_own_and_none_means_no_login(
    captured: _CapturedSend,
) -> None:
    await SmtpEmail(RELAY, ALPHA).send(TO, SUBJECT, TEXT, HTML)
    await SmtpEmail(RELAY, BRAVO).send(TO, SUBJECT, TEXT, HTML)

    first, second = captured.calls
    assert (first["username"], first["password"]) == (
        "capacity@alpha.example.test",
        "alpha-secret-canary-0001",
    )
    assert (second["username"], second["password"]) == (None, None)


def test_no_identity_or_sender_shows_its_password_in_a_repr_or_str() -> None:
    sender = SmtpEmail(RELAY, ALPHA)

    for text in (repr(ALPHA), str(ALPHA), repr(sender), str(sender)):
        assert "alpha-secret-canary-0001" not in text


async def test_the_password_is_not_in_the_log_of_a_send(
    captured: _CapturedSend, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    await SmtpEmail(RELAY, ALPHA).send(TO, SUBJECT, TEXT, HTML)

    assert "alpha-secret-canary-0001" not in _adapter_log(caplog)


@pytest.mark.parametrize("address", ["", "no-at-sign", "a@b", "x y@example.test", "a@b@c.test"])
def test_an_identity_with_an_address_that_is_not_one_is_refused(address: str) -> None:
    with pytest.raises(ValueError):
        SmtpIdentity(from_address=address)


def test_a_display_name_that_could_break_the_header_is_refused() -> None:
    for name in ("Alpha\r\nBcc: x@example.test", "Alpha <x@example.test>", "a" * 100):
        with pytest.raises(ValueError):
            SmtpIdentity(from_address="capacity@alpha.example.test", display_name=name)


def test_a_relay_port_outside_the_range_is_refused() -> None:
    for port in (0, 65536, -1):
        with pytest.raises(ValueError):
            SmtpRelay(host="relay.example.test", port=port)
