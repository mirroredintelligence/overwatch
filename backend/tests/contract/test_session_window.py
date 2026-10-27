"""The session receive window in the Service Bus factory stays inside the contract budget (I02)."""

from datetime import timedelta

from tests.contract.factories import SESSION_OPEN_LIMIT, session_open_window


def test_a_session_open_window_never_exceeds_the_budget() -> None:
    assert session_open_window(timedelta(hours=1)) <= SESSION_OPEN_LIMIT.total_seconds()


def test_a_short_wait_gets_the_minimum_session_open_window() -> None:
    assert session_open_window(timedelta(milliseconds=200)) == 5.0
