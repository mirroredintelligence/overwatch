"""Tests for the SMTP email adapter (I09, DEC-109).

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

from diucs.adapters.outbound.email_smtp.smtp_email import SmtpEmail, build_message, text_to_html
from diucs.application.ports.outbound.messaging import (
    SendFailedError,
    SendReceipt,
    TransientSendError,
)
from diucs.bootstrap.settings import Settings
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


def settings_for(port: int) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        smtp_host="127.0.0.1",
        smtp_port=port,
        smtp_starttls=False,
        email_from=FROM,
    )


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


async def test_send_delivers_one_message_with_both_parts(smtp_server: Any) -> None:
    handler, port = smtp_server

    receipt = await SmtpEmail(settings_for(port)).send(TO, SUBJECT, TEXT, HTML)

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
    sender = SmtpEmail(settings_for(port))

    first = await sender.send(TO, SUBJECT, TEXT, HTML)
    second = await sender.send(TO, SUBJECT, TEXT, HTML)

    assert first.provider_message_id != second.provider_message_id


async def test_a_text_only_message_gets_a_generated_html_part(smtp_server: Any) -> None:
    handler, port = smtp_server

    await SmtpEmail(settings_for(port)).send(TO, "Review request", "Review request: " + LINK, None)

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
        await SmtpEmail(settings_for(port)).send(TO, SUBJECT, TEXT, HTML)

    assert handler.messages == []


async def test_a_550_refused_recipient_is_not_accepted(smtp_server: Any) -> None:
    handler, port = smtp_server
    handler.rcpt_reply = "550 5.1.1 mailbox unavailable"

    receipt = await SmtpEmail(settings_for(port)).send(TO, SUBJECT, TEXT, HTML)

    assert receipt == SendReceipt(provider_message_id="", accepted=False)
    assert handler.messages == []


async def test_a_5xx_answer_to_the_message_is_a_failure_and_is_not_retried(
    smtp_server: Any,
) -> None:
    handler, port = smtp_server
    handler.data_reply = "554 5.7.1 message rejected"

    with pytest.raises(SendFailedError):
        await SmtpEmail(settings_for(port)).send(TO, SUBJECT, TEXT, HTML)

    assert handler.messages == []


async def test_no_server_listening_is_transient() -> None:
    port = _free_port()

    with pytest.raises(TransientSendError):
        await SmtpEmail(settings_for(port)).send(TO, SUBJECT, TEXT, HTML)


async def test_logs_hold_neither_the_address_nor_the_body(
    smtp_server: Any, caplog: pytest.LogCaptureFixture
) -> None:
    _, port = smtp_server
    caplog.set_level(logging.DEBUG)

    receipt = await SmtpEmail(settings_for(port)).send(
        MARKER_ADDRESS,
        SUBJECT,
        f"{MARKER_BODY} text",
        f"<p>{MARKER_BODY} html</p>",
    )

    assert receipt.accepted is True
    assert MARKER_ADDRESS not in caplog.text
    assert MARKER_BODY not in caplog.text
    assert receipt.provider_message_id in caplog.text


async def test_an_unconfigured_relay_is_a_failure_and_sends_nothing() -> None:
    # No SMTP host in settings: the adapter must refuse, never fall back to a local relay.
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    with pytest.raises(SendFailedError):
        await SmtpEmail(settings).send(TO, SUBJECT, TEXT, HTML)
