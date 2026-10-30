"""Unit tests for the scheduled-work records (P08, application/work.py)."""

from datetime import UTC, datetime

import pytest

from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.errors import ValidationFailed


def test_the_twelve_work_kinds_are_named_as_the_spec_names_them() -> None:
    assert {kind.value for kind in WorkKind} == {
        "prompt-due",
        "reminder",
        "phone-task",
        "escalate-to-lead",
        "booking-phone-prompt",
        "booking-expire",
        "criteria-review-reminder",
        "alert-escalate",
        "clinical-return",
        "reverify",
        "not-updated-check",
        "invariant-check",
    }


def test_scheduled_work_refuses_a_naive_due_time() -> None:
    with pytest.raises(ValidationFailed, match="due_at"):
        ScheduledWork(
            id="work-1",
            kind=WorkKind.BOOKING_EXPIRE,
            due_at=datetime(2026, 10, 24, 14, 21),
            about_id="booking-1",
            sequence_number=None,
            status="scheduled",
        )


def test_scheduled_work_refuses_a_status_outside_the_three_states() -> None:
    with pytest.raises(ValidationFailed, match="status"):
        ScheduledWork(
            id="work-1",
            kind=WorkKind.BOOKING_EXPIRE,
            due_at=datetime(2026, 10, 24, 14, 21, tzinfo=UTC),
            about_id="booking-1",
            sequence_number=None,
            status="pending",
        )


@pytest.mark.parametrize("status", ["scheduled", "done", "cancelled"])
def test_scheduled_work_accepts_each_of_the_three_states(status: str) -> None:
    work = ScheduledWork(
        id="work-1",
        kind=WorkKind.REVERIFY,
        due_at=datetime(2026, 10, 24, 14, 21, tzinfo=UTC),
        about_id="practitioner-1",
        sequence_number=7,
        status=status,
    )
    assert work.status == status
