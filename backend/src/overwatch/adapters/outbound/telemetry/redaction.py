"""Redaction of patient data, tokens and secrets from telemetry and logs (O01).

Two layers. The attribute allow-list (attributes.py) decides which keys survive. Then every value
that survives is scanned: a phone number, an NHS number, a UK postcode, a link token (23 letters,
DEC-154), a support code (XXXX-XXXX) or a pairing code is replaced with `[redacted]`. The scan
catches what a key cannot say, such as a phone number inside a session id.

Logs use the same scan. RedactingLogFilter rewrites each record before a handler formats it, and
an exception is logged as its class name only, because an exception message can carry a postcode
or a phone number (lesson L111).
"""

import logging
import re
from collections.abc import Mapping
from typing import Any, Final

from diucs.adapters.outbound.telemetry.attributes import is_allowed_key

REDACTED: Final = "[redacted]"

_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # Phone numbers and NHS numbers: ten or more digits, with optional single spaces or hyphens,
    # and an optional leading plus.
    re.compile(r"\+?\d(?:[ -]?\d){9,}"),
    # A UK postcode, such as DT4 8XX.
    re.compile(r"(?i)\b[a-z]{1,2}\d[a-z\d]?\s?\d[a-z]{2}\b"),
    # A link token: exactly 23 letters, with no digit (DEC-154).
    re.compile(r"(?<![A-Za-z])[A-Za-z]{23}(?![A-Za-z])"),
    # A support code, XXXX-XXXX, drawn from the support alphabet (no 0, 1, I, L or O).
    re.compile(
        r"(?<![A-Z0-9])[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-"
        r"[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}(?![A-Z0-9])"
    ),
    # A pairing code, shown as 482 913.
    re.compile(r"(?<!\d)\d{3} \d{3}(?!\d)"),
)


def redact_text(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def clean_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """The attributes an exporter may see: only allowed keys, with every value scanned."""
    return {key: redact_value(value) for key, value in attributes.items() if is_allowed_key(key)}


class RedactingLogFilter(logging.Filter):
    """Rewrites a record so its message holds no patient data, token or secret. An exception is
    replaced by its class name."""

    def filter(self, record: logging.LogRecord) -> bool:
        suffix = ""
        if record.exc_info and record.exc_info[0] is not None:
            suffix = f" [{record.exc_info[0].__name__}]"
            record.exc_info = None
            record.exc_text = None
        record.msg = redact_text(record.getMessage()) + suffix
        record.args = ()
        return True


def install_log_redaction() -> None:
    """Put the filter on every handler of the root logger, once. A process calls this after it has
    configured logging, because a handler added later is not filtered."""
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, RedactingLogFilter) for item in handler.filters):
            handler.addFilter(RedactingLogFilter())
