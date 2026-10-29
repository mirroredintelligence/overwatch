"""Redaction of patient data, tokens and secrets from telemetry and logs (O01).

Stub for the red commit: nothing is redacted yet.
"""

import logging
from collections.abc import Mapping
from typing import Any


def redact_text(text: str) -> str:
    return text


def redact_value(value: Any) -> Any:
    return value


def clean_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return dict(attributes)


class RedactingLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return True
