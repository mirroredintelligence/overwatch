"""SMTP email adapter (I09). Stub for the red commit (DEC-010): names and signatures only."""

from email.message import EmailMessage
from typing import Protocol

from pydantic import SecretStr

from diucs.application.ports.outbound.messaging import SendReceipt


class SmtpSettings(Protocol):
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: SecretStr | None
    smtp_starttls: bool
    email_from: str


def build_message(
    to: str,
    subject: str,
    text: str,
    html: str,
    from_addr: str,
    message_id: str,
) -> EmailMessage:
    raise NotImplementedError


def text_to_html(text: str, link_label: str) -> str:
    raise NotImplementedError


class SmtpEmail:
    def __init__(self, settings: SmtpSettings) -> None:
        raise NotImplementedError

    async def send(self, to: str, subject: str, text: str, html: str | None) -> SendReceipt:
        raise NotImplementedError
