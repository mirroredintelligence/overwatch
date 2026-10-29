"""The pairing limits, pinned by their literal values (U10, DEC-160 item 4). The behavioural
tests in tests/integration/application/test_pair_wall_screen.py also count with literals, so a
change of either number fails a named test and is a decision, not an edit."""

from datetime import timedelta

from diucs.application.use_cases.pair_wall_screen import (
    CODE_ATTEMPTS,
    CONFIRM_FAILURE_LIMIT,
    LIMIT_WINDOW,
    START_LIMIT,
)


def test_a_lead_may_fail_five_times_in_ten_minutes() -> None:
    assert CONFIRM_FAILURE_LIMIT == 5
    assert timedelta(minutes=10) == LIMIT_WINDOW


def test_a_tenant_may_start_twenty_pairings_in_ten_minutes() -> None:
    assert START_LIMIT == 20
    assert timedelta(minutes=10) == LIMIT_WINDOW


def test_a_start_draws_a_code_ten_times_before_it_gives_up() -> None:
    assert CODE_ATTEMPTS == 10
