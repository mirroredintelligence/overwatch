"""The shape a Web Push endpoint must have (R11, I14).

The endpoint of a push subscription is a URL the client chose, and the server posts the push to it.
A bad one would make the server a way to reach an inside address (server-side request forgery), so
it is checked before it is ever stored: https, no credentials, no fragment, the default port, and a
real DNS name (at least two labels, never an IP address in any form, never a name that is local by
convention). The check is structural and does no lookup; a name that resolves to an inside address
is a gap the sender's network policy closes (known issue). Nothing the client sent is put in a
refusal.
"""

import re
from typing import Final
from urllib.parse import urlsplit

from diucs.domain.errors import ValidationFailed

MAX_ENDPOINT_LENGTH: Final = 2048
_REFUSED: Final = "must hold an https endpoint of a push service"
_LABEL: Final = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_NUMERIC_LABEL: Final = re.compile(r"(0x[0-9a-f]+|[0-9]+)")
_LOCAL_SUFFIXES: Final = (
    ".local",
    ".localhost",
    ".internal",
    ".lan",
    ".home",
    ".corp",
    ".intranet",
)
_PRINTABLE_URL: Final = re.compile(r"[\x21-\x7e]+")


def _refuse() -> ValidationFailed:
    return ValidationFailed("subscription", _REFUSED)


def check_push_endpoint(endpoint: object) -> str:
    """The endpoint unchanged when acceptable; otherwise ValidationFailed on `subscription`."""
    if not isinstance(endpoint, str) or not 0 < len(endpoint) <= MAX_ENDPOINT_LENGTH:
        raise _refuse()
    if _PRINTABLE_URL.fullmatch(endpoint) is None:
        raise _refuse()
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        raise _refuse() from None
    if parts.scheme.lower() != "https" or parts.fragment or "@" in parts.netloc:
        raise _refuse()
    if port not in (None, 443):
        raise _refuse()
    host = (parts.hostname or "").lower().rstrip(".")
    labels = host.split(".")
    if len(labels) < 2 or any(_LABEL.fullmatch(label) is None for label in labels):
        raise _refuse()
    if host.endswith(_LOCAL_SUFFIXES) or host == "localhost":
        raise _refuse()
    # An address in any form (dotted, hex, a single number) has a numeric last label.
    if _NUMERIC_LABEL.fullmatch(labels[-1]):
        raise _refuse()
    return endpoint
