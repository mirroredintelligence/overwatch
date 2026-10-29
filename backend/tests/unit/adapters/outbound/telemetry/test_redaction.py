"""Redaction for telemetry and logs (O01): the attribute allow-list, and no phone number, link
token, support code, postcode or NHS number in a value or a log line. Sample values only."""

import logging

import pytest

from diucs.adapters.outbound.telemetry.attributes import is_allowed_key
from diucs.adapters.outbound.telemetry.redaction import (
    RedactingLogFilter,
    clean_attributes,
    redact_text,
    redact_value,
)

ALLOWED = [
    "session.id",
    "user.role",
    "service.id",
    "page.route",
    "component.id",
    "element.id",
    "release",
    "device.type",
    "app.mode",
    "net.effective_type",
    "tenant.id",
    "usecase.outcome",
    "usecase.idempotent_replay",
    "db.system",
    "db.query.id",
    "db.access_mode",
    "db.row_count",
    "messaging.system",
    "messaging.destination.name",
    "messaging.message.id",
    "http.request.method",
    "http.route",
    "http.response.status_code",
    "url.scheme",
    "server.address",
    "error.type",
    "booking.id",
]

DROPPED = [
    "patient.postcode",
    "patient.name",
    "nhs.number",
    "http.request.body",
    "http.target",
    "http.url",
    "url.full",
    "url.path",
    "net.peer.ip",
    "user_agent.original",
    "field.value",
    "field.text",
    "user.email",
    "tenant.name",
    "link.token",
    "sms.phone.id",
    "link_token.id",
    "support.code.id",
    "exception.message",
    "exception.stacktrace",
]


@pytest.mark.parametrize("key", ALLOWED)
def test_allowed_keys_survive(key: str) -> None:
    assert is_allowed_key(key)


@pytest.mark.parametrize("key", DROPPED)
def test_keys_off_the_allow_list_are_dropped(key: str) -> None:
    assert not is_allowed_key(key)


def test_clean_attributes_drops_unlisted_keys_and_keeps_listed_ones() -> None:
    cleaned = clean_attributes(
        {
            "service.id": "SVC-0042",
            "patient.postcode": "DT4 8XX",
            "http.request.body": '{"name": "Sample Patient"}',
            "usecase.outcome": "ok",
        }
    )

    assert cleaned == {"service.id": "SVC-0042", "usecase.outcome": "ok"}


def test_a_phone_number_inside_an_allowed_value_is_redacted() -> None:
    cleaned = clean_attributes({"session.id": "+447700900123", "service.id": "SVC-0042"})

    assert cleaned == {"session.id": "[redacted]", "service.id": "SVC-0042"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call from +447700900123 failed", "call from [redacted] failed"),
        ("sent to +44 7700 900123", "sent to [redacted]"),
        ("sent to 07700 900123", "sent to [redacted]"),
        ("NHS 943 476 5919 in the record", "NHS [redacted] in the record"),
        ("link AbcdEfghIjklMnopQrstUvw used", "link [redacted] used"),
        ("code K7MQ-3WXR entered", "code [redacted] entered"),
        ("pairing 482 913 shown", "pairing [redacted] shown"),
        ("ship to DT4 8XX today", "ship to [redacted] today"),
    ],
)
def test_patient_identifiers_and_secrets_are_redacted(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Capacity 4 beds",
        "HTTP 500 from the query",
        "usecase.ReportCapacity took 12 ms",
        "AbcdEfghIjklMnopQrstUv",  # 22 letters: not a link token length
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert redact_text(text) == text


def test_redact_value_passes_numbers_and_redacts_strings_in_a_list() -> None:
    assert redact_value(7) == 7
    assert redact_value(True) is True
    assert redact_value(["SVC-0042", "+447700900123"]) == ["SVC-0042", "[redacted]"]


def test_a_log_line_is_redacted_before_any_handler_formats_it() -> None:
    record = logging.LogRecord(
        "diucs.test",
        logging.INFO,
        __file__,
        1,
        "sent to %s with token %s",
        ("+447700900123", "AbcdEfghIjklMnopQrstUvw"),
        None,
    )

    assert RedactingLogFilter().filter(record) is True
    assert record.getMessage() == "sent to [redacted] with token [redacted]"


def test_an_exception_message_never_reaches_the_formatted_log() -> None:
    try:
        raise ValueError("no such patient at DT4 8XX, phone +447700900123")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "diucs.test", logging.ERROR, __file__, 1, "reply failed", (), sys.exc_info()
        )

    RedactingLogFilter().filter(record)
    formatted = logging.Formatter().format(record)

    assert "DT4 8XX" not in formatted
    assert "+447700900123" not in formatted
    assert "ValueError" in formatted


@pytest.mark.parametrize(
    "key",
    [
        "db.statement",
        "db.query.text",
        "db.query.parameter.postcode",
        "db.query.parameters",
        "db.cypher",
        "db.sql.table",
    ],
)
def test_a_db_key_that_carries_query_text_or_its_parameters_is_dropped(key: str) -> None:
    """The `db.` prefix admits the structured names only: the Cypher text and its parameters can
    carry a value a patient or a person supplied, so they never reach telemetry."""
    assert not is_allowed_key(key)
