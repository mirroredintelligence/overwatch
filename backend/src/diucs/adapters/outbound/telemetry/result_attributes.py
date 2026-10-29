"""The attributes a telemetry query result may carry (O07), from O01's allow-list.

`clean_attributes` (redaction.py) keeps only the keys `is_allowed_key` passes (attributes.py) and
scans every value for phone numbers, postcodes, link tokens and support codes. This module adds
two rules for the console: the tenant and session ids are not result attributes (the console
already has them), and only scalar values are kept.
"""

from collections.abc import Mapping
from typing import Any, Final

from diucs.adapters.outbound.telemetry.redaction import clean_attributes
from diucs.application.ports.outbound.telemetry_query import AttributeValue

# The ids a row carries for its own filter. Not shown in a result.
_NOT_RESULT_KEYS: Final[frozenset[str]] = frozenset({"tenant.id", "session.id"})


def result_attributes(raw: Mapping[str, Any]) -> dict[str, AttributeValue]:
    cleaned = clean_attributes(raw)
    kept: dict[str, AttributeValue] = {}
    for key, value in cleaned.items():
        if key in _NOT_RESULT_KEYS:
            continue
        if isinstance(value, bool | int | float | str):
            kept[key] = value
    return kept
