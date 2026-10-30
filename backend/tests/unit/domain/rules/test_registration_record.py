"""Tests for the registration record: each step of a registration with who and when (U29).

The approval steps are kept in the registration's draft as typed text fields (DEC-407), `<step>_at`
and `<step>_by`. Submission has its own time. The call-back, scope and criteria steps are judged
from the stored checks and carry no time of their own (known issue). Sample values only.
"""

from datetime import UTC, datetime

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.registration_record import RECORD_STEP, registration_steps


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 29, hour, minute, tzinfo=UTC)


def test_the_record_step_has_a_stable_name() -> None:
    assert RECORD_STEP == "record"


def test_timed_steps_are_listed_in_time_order_with_who_and_when() -> None:
    record = {
        "test_answered_at": at(15, 5).isoformat(),
        "test_answered_by": "role-1",
        "approved_at": at(14, 40).isoformat(),
        "approved_by": "prac-lead",
    }
    steps = registration_steps(at(10, 0), "prac-applicant", record)
    timed = [(s.step, s.at, s.by) for s in steps if s.at is not None]
    assert timed == [
        ("submitted", at(10, 0), "prac-applicant"),
        ("approved", at(14, 40), "prac-lead"),
        ("test-answered", at(15, 5), "role-1"),
    ]


def test_the_untimed_steps_come_last_with_no_time() -> None:
    steps = registration_steps(at(10, 0), "prac-applicant", {})
    assert [s.step for s in steps] == ["submitted", "call-back", "scope", "criteria"]
    assert all(s.at is None for s in steps[1:])


def test_a_step_that_was_never_recorded_is_not_listed_as_done() -> None:
    steps = registration_steps(None, None, {"live_at": at(16, 0).isoformat()})
    names = [s.step for s in steps]
    assert "approved" not in names
    assert "set-live" in names


def test_a_naive_time_in_the_record_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        registration_steps(None, None, {"approved_at": "2026-10-29T14:40:00"})


def test_an_unreadable_time_in_the_record_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        registration_steps(None, None, {"approved_at": "soon"})
