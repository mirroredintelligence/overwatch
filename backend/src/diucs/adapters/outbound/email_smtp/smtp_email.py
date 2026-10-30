"""SMTP email adapter (I09): sends a capacity or booking email through an SMTP relay (DEC-110).

Only role inboxes are addressed (architecture: "Role inboxes only"). The message is multipart
alternative, text first, HTML second, with an Auto-Submitted header. Nothing here logs an address,
a body or an exception's text: the server's reply can echo the address (H-09).
"""

import html as _html
import logging
import re
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Final

import aiosmtplib
from pydantic import SecretStr

from diucs.application.ports.outbound.messaging import (
    SendFailedError,
    SendReceipt,
    TransientSendError,
)

_log = logging.getLogger(__name__)

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


_LABEL: Final = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
# One address, no display name, no comment, no quoting: the shape a role inbox has. A domain needs a
# dot, so "a@b" is not an address. Anything that could carry a header break or a second recipient
# (white space, angle brackets, a comma, a second at sign) does not match.
_ADDRESS: Final = re.compile(rf"[A-Za-z0-9._%+-]{{1,64}}@{_LABEL}(?:\.{_LABEL})+")
_ADDRESS_MAX_LENGTH: Final = 254
_DISPLAY_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .'&()_-]{0,79}")


@dataclass(frozen=True, slots=True)
class SmtpRelay:
    """The platform's SMTP relay: where mail is handed in, never who it is from. The endpoint is
    infrastructure and is shared; each tenant's identity and credential are its own (DEC-131
    item 1). `host` is None when no relay is configured, and nothing is then sent."""

    host: str | None
    port: int = 587
    starttls: bool = True

    def __post_init__(self) -> None:
        if self.host is not None and (type(self.host) is not str or not self.host.strip()):
            raise ValueError("the relay host is not a host name")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("the relay port is not a port")


@dataclass(frozen=True, slots=True)
class SmtpIdentity:
    """One tenant's sender: the address its mail is from (and the domain of its message ids), a
    display name, and the login it presents to the relay. The password is a secret that came from
    the secret store; it is hidden from `repr` and `str`, so no log line or error can print it."""

    from_address: str
    display_name: str | None = None
    username: str | None = None
    password: SecretStr | None = None

    def __post_init__(self) -> None:
        if (
            type(self.from_address) is not str
            or len(self.from_address) > _ADDRESS_MAX_LENGTH
            or _ADDRESS.fullmatch(self.from_address) is None
        ):
            raise ValueError("the sender address is not an address")
        if self.display_name is not None and (
            type(self.display_name) is not str or _DISPLAY_NAME.fullmatch(self.display_name) is None
        ):
            raise ValueError("the sender display name is not plain text")
        if self.username is not None and (
            type(self.username) is not str
            or not 1 <= len(self.username) <= _ADDRESS_MAX_LENGTH
            or not self.username.isprintable()
        ):
            raise ValueError("the login name is not plain text")

    def __repr__(self) -> str:
        return f"SmtpIdentity(domain={self.from_address.rsplit('@', 1)[1]})"

    __str__ = __repr__

    @property
    def domain(self) -> str:
        return self.from_address.rsplit("@", 1)[1].lower()

    @property
    def sender(self) -> str:
        """The From header: the display name and the address, or the address alone."""
        if self.display_name is None:
            return self.from_address
        return formataddr((self.display_name, self.from_address))


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

    def __init__(self, relay: SmtpRelay, identity: SmtpIdentity) -> None:
        self._relay = relay
        self._identity = identity

    async def send(self, to: str, subject: str, text: str, html: str | None) -> SendReceipt:
        relay, identity = self._relay, self._identity
        if relay.host is None:
            raise SendFailedError("the SMTP relay is not configured")
        message_id = f"<{uuid.uuid4()}@{identity.domain}>"
        body = html if html is not None else text_to_html(text, _link_label(text))
        message = build_message(to, subject, text, body, identity.sender, message_id)
        try:
            await aiosmtplib.send(
                message,
                hostname=relay.host,
                port=relay.port,
                username=identity.username,
                password=None
                if identity.password is None
                else identity.password.get_secret_value(),
                start_tls=relay.starttls,
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
