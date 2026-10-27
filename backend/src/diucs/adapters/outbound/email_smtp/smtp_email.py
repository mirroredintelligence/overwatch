"""SMTP email adapter (I09): sends a capacity or booking email through an SMTP relay (DEC-110).

Only role inboxes are addressed (architecture: "Role inboxes only"). The message is multipart
alternative, text first, HTML second, with an Auto-Submitted header. Nothing here logs an address,
a body or an exception's text: the server's reply can echo the address (H-09).
"""

import html as _html
import logging
import re
import uuid
from email.message import EmailMessage
from typing import Final, Protocol

import aiosmtplib
from pydantic import SecretStr

from diucs.application.ports.outbound.messaging import (
    SendFailedError,
    SendReceipt,
    TransientSendError,
)

_log = logging.getLogger(__name__)

_MESSAGE_ID_DOMAIN: Final = "diucs.example"
# [ASSUMED] Bounded wait for each SMTP step. A slow relay is transient, not a success.
_TIMEOUT_S: Final = 30.0
_FALLBACK_LABEL: Final = "Open link"
_URL: Final = re.compile(r"https?://\S+")
_BUTTON_STYLE: Final = (
    "display:inline-block;padding:12px 18px;background:#1d4ed8;color:#ffffff;"
    "text-decoration:none;border-radius:4px;font-size:18px;"
)
_HTML_FRAME: Final = (
    '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="utf-8"></head>\n'
    '<body style="font-family:Arial,Helvetica,sans-serif;font-size:18px;line-height:1.4;'
    'color:#111111;background:#ffffff;">\n{body}\n</body>\n</html>\n'
)


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
    """Return a multipart/alternative message: the text part first, then the HTML part."""
    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = message_id
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def _escape_lines(text: str) -> str:
    return "<br>".join(_html.escape(line) for line in text.split("\n"))


def text_to_html(text: str, link_label: str) -> str:
    """Build an HTML body from plain text. Every URL becomes one button-style anchor labelled
    link_label, and the label words that introduced it in the text are not repeated."""
    parts: list[str] = []
    for paragraph in (p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()):
        match = _URL.search(paragraph)
        if match is None:
            parts.append(f"<p>{_escape_lines(paragraph)}</p>")
            continue
        url = match.group(0).rstrip(".,;)")
        before = paragraph[: match.start()].rstrip().rstrip(":").rstrip()
        if before.endswith(link_label):
            before = before[: -len(link_label)].rstrip().rstrip(":").rstrip()
        after = paragraph[match.start() + len(url) :].strip()
        if before:
            parts.append(f"<p>{_escape_lines(before)}</p>")
        parts.append(
            f'<p><a href="{_html.escape(url, quote=True)}" style="{_BUTTON_STYLE}">'
            f"{_html.escape(link_label)}</a></p>"
        )
        if after:
            parts.append(f"<p>{_escape_lines(after)}</p>")
    return _HTML_FRAME.format(body="\n".join(parts))


def _link_label(text: str) -> str:
    """The visible label of the link in a plain-text body: the words before the URL in its
    sentence, without the colon ("Confirm or update" in "Confirm or update: <url>")."""
    match = _URL.search(text)
    if match is None:
        return _FALLBACK_LABEL
    sentence = re.split(r"\. |\n", text[: match.start()])[-1]
    return sentence.strip().rstrip(":").strip() or _FALLBACK_LABEL


class SmtpEmail:
    """EmailSender over SMTP. A 4xx answer or a lost connection is transient (the consumer
    retries). A 5xx answer to the recipient is a refusal (accepted False, no provider id). Any
    other 5xx answer is a configuration or contract fault and is not retried."""

    def __init__(self, settings: SmtpSettings) -> None:
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._user = settings.smtp_user
        self._password = settings.smtp_password
        self._starttls = settings.smtp_starttls
        self._from = settings.email_from

    async def send(self, to: str, subject: str, text: str, html: str | None) -> SendReceipt:
        if self._host is None:
            raise SendFailedError("the SMTP relay is not configured")
        message_id = f"<{uuid.uuid4()}@{_MESSAGE_ID_DOMAIN}>"
        body = html if html is not None else text_to_html(text, _link_label(text))
        message = build_message(to, subject, text, body, self._from, message_id)
        try:
            await aiosmtplib.send(
                message,
                hostname=self._host,
                port=self._port,
                username=self._user,
                password=None if self._password is None else self._password.get_secret_value(),
                start_tls=self._starttls,
                timeout=_TIMEOUT_S,
            )
        except aiosmtplib.SMTPRecipientsRefused as refused:
            codes = [entry.code for entry in refused.recipients]
            if codes and all(500 <= code < 600 for code in codes):
                _log.warning("email recipient refused message_id=%s", message_id)
                return SendReceipt(provider_message_id="", accepted=False)
            _log.warning("email recipient deferred message_id=%s", message_id)
            raise TransientSendError() from None
        except aiosmtplib.SMTPResponseException as failed:
            if 400 <= failed.code < 500:
                _log.warning("email deferred code=%s message_id=%s", failed.code, message_id)
                raise TransientSendError() from None
            _log.error("email failed code=%s message_id=%s", failed.code, message_id)
            raise SendFailedError(f"SMTP answered {failed.code}") from None
        except (aiosmtplib.SMTPException, OSError) as lost:
            _log.warning("email transient failure kind=%s", type(lost).__name__)
            raise TransientSendError() from None
        _log.info("email accepted message_id=%s", message_id)
        return SendReceipt(provider_message_id=message_id, accepted=True)
