"""The link pages' adapter, without a server (L01, DEC-167): the log filter that hides a token, the
shape of an answer in the body, and a route with nothing configured. All values are synthetic."""

import logging
from typing import Any

import pytest

from diucs.adapters.inbound.link_pages import capacity_links as pages
from diucs.adapters.inbound.link_pages.capacity_links import (
    RedactLinkTokens,
    install_log_redaction,
)
from diucs.domain.errors import ValidationFailed

TOKEN = "AbCdEfGhIjKlMnOpQrStUvW"


def _record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, "x", 1, msg, args or None, None)


# -- the access log never shows a token ------------------------------------------------------------


def test_a_token_in_the_path_of_an_access_log_line_is_hidden() -> None:
    record = _record('%s - "%s %s HTTP/%s" %d', "10.0.0.1:5", "GET", f"/links/{TOKEN}", "1.1", 200)

    assert RedactLinkTokens().filter(record) is True

    assert TOKEN not in record.getMessage()
    assert "/links/[token]" in record.getMessage()


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        (f"/links/{TOKEN}/renew", "/links/[token]/renew"),
        (f"/links/{TOKEN}?a=1&b=2", "/links/[token]?a=1&b=2"),
        (f"https://alpha.example.org/links/{TOKEN}", "https://alpha.example.org/links/[token]"),
        ("/links/", "/links/"),
        ("/fhir/Observation/x", "/fhir/Observation/x"),
    ],
)
def test_only_the_token_part_of_a_link_path_is_hidden(path: str, shown: str) -> None:
    record = _record("%s", path)

    RedactLinkTokens().filter(record)

    assert record.getMessage() == shown


def test_a_token_in_the_message_itself_is_hidden() -> None:
    record = _record(f"GET /links/{TOKEN} 200")

    RedactLinkTokens().filter(record)

    assert record.getMessage() == "GET /links/[token] 200"


def test_arguments_that_are_not_text_and_records_with_a_dict_are_left_alone() -> None:
    record = _record("%s %d", "x", 200)
    mapping = logging.LogRecord("n", logging.INFO, "x", 1, "%(a)s", ({"a": "b"},), None)

    assert RedactLinkTokens().filter(record) is True
    assert RedactLinkTokens().filter(mapping) is True
    assert record.getMessage() == "x 200"
    assert mapping.getMessage() == "b"


def test_the_filter_is_installed_on_the_access_log_once() -> None:
    install_log_redaction()
    install_log_redaction()

    filters = [
        f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, RedactLinkTokens)
    ]
    assert len(filters) == 1


def test_a_real_access_line_through_the_logger_shows_no_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    install_log_redaction()
    caplog.set_level(logging.INFO, logger="uvicorn.access")

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "10.0.0.1:5", "POST", f"/links/{TOKEN}/renew", "1.1", 202
    )

    assert TOKEN not in caplog.text
    assert "/links/[token]/renew" in caplog.text


def test_a_logger_of_its_own_gets_the_filter_too() -> None:
    install_log_redaction("test.link.pages")
    install_log_redaction("test.link.pages")

    filters = logging.getLogger("test.link.pages").filters
    assert sum(isinstance(f, RedactLinkTokens) for f in filters) == 1


# -- the answer in the body ------------------------------------------------------------------------


def test_the_answer_is_read_from_a_json_object_and_nothing_else() -> None:
    action = pages._action_of({"action": "number", "value": 7, "confirmOutOfRange": True})

    assert (action.action, action.value, action.confirm_out_of_range) == ("number", 7, True)
    plain = pages._action_of({"action": "confirm"})
    assert (plain.action, plain.value, plain.confirm_out_of_range) == ("confirm", None, False)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        (None, "body"),
        ({"action": "confirm", "tenantId": "x"}, "body"),
        ({"value": 3}, "action"),
        ({"action": None}, "action"),
        ({"action": 7}, "action"),
    ],
)
def test_a_body_that_is_not_an_answer_is_refused_by_field(body: Any, field: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        pages._action_of(body)

    assert refused.value.field == field


def test_the_page_paths_are_the_ones_the_front_end_and_the_prompt_use() -> None:
    assert pages.LINKS_PATH_PREFIX == "/links"
    assert pages.LINK_PAGE_PATH == "/l"
    assert pages.LINK_SCHEME == "https"
    assert pages.MAX_BODY_BYTES == 1024
    assert pages.SEND_THE_NUMBER_TEXT == "Please send the number"
