"""Criteria version workflow and review dates (D21, docs/spec/domain-rules.md section 4.2).

Synthetic fixtures only: the UCR West sample service from the D20 prompt. No patient data.
Dates are calendar dates (the London day). Nothing here reads the clock.
"""

import itertools
from dataclasses import replace
from datetime import UTC, date, datetime
from enum import StrEnum

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import CriteriaStatus
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.rules.criteria_workflow import (
    REVIEW_REMINDER_BEFORE,
    approve,
    is_review_overdue,
    next_review_by,
    review_reminder_due,
    transition_criteria,
)
from tests.unit.domain.model.test_criteria import ucr_west

C = CriteriaStatus

# domain-rules 4.2 and the D21 prompt: the only legal moves. Retiring is allowed from every
# status except retired. A tuple, not a set, so test ids are stable.
ALLOWED_MOVES: tuple[tuple[CriteriaStatus, CriteriaStatus], ...] = (
    (C.DRAFT, C.PENDING_APPROVAL),
    (C.PENDING_APPROVAL, C.CURRENT),
    (C.PENDING_APPROVAL, C.DRAFT),
    (C.CURRENT, C.SUPERSEDED),
    (C.DRAFT, C.RETIRED),
    (C.PENDING_APPROVAL, C.RETIRED),
    (C.CURRENT, C.RETIRED),
    (C.SUPERSEDED, C.RETIRED),
)


class _OtherStatus(StrEnum):
    """A different enum whose member has the same value as a criteria status (lesson L3)."""

    DRAFT = "draft"


@pytest.mark.parametrize(("current", "target"), ALLOWED_MOVES, ids=lambda s: s.value)
def test_every_allowed_transition_succeeds(current: CriteriaStatus, target: CriteriaStatus) -> None:
    assert transition_criteria(current, target) is target


REFUSED_MOVES = tuple(
    pair for pair in itertools.product(CriteriaStatus, CriteriaStatus) if pair not in ALLOWED_MOVES
)


@pytest.mark.parametrize(("current", "target"), REFUSED_MOVES, ids=lambda s: s.value)
def test_every_other_transition_raises(current: CriteriaStatus, target: CriteriaStatus) -> None:
    with pytest.raises(InvalidTransition):
        transition_criteria(current, target)


def test_current_cannot_be_sent_back_to_draft() -> None:
    with pytest.raises(InvalidTransition):
        transition_criteria(C.CURRENT, C.DRAFT)


def test_superseded_cannot_become_current_again() -> None:
    with pytest.raises(InvalidTransition):
        transition_criteria(C.SUPERSEDED, C.CURRENT)


def test_retired_cannot_be_retired_again() -> None:
    with pytest.raises(InvalidTransition):
        transition_criteria(C.RETIRED, C.RETIRED)


def test_a_member_of_another_enum_with_the_same_value_is_refused() -> None:
    # Lesson L3 and L38: "draft" in another enum must not pass as CriteriaStatus.DRAFT.
    with pytest.raises(ValidationFailed):
        transition_criteria(_OtherStatus.DRAFT, C.PENDING_APPROVAL)  # type: ignore[arg-type]


def test_a_plain_string_status_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        transition_criteria("draft", C.PENDING_APPROVAL)  # type: ignore[arg-type]


# Review by 12 Dec 2026 (the D21 prompt's example).
REVIEW_BY = date(2026, 12, 12)


@pytest.mark.parametrize(
    ("today", "reminder_due"),
    [
        (date(2026, 11, 27), False),
        (date(2026, 11, 28), True),
        (date(2026, 12, 12), True),
        (date(2026, 12, 13), False),
    ],
)
def test_reminder_is_due_from_14_days_before_up_to_and_including_review_by(
    today: date, reminder_due: bool
) -> None:
    criteria = ucr_west(review_by=REVIEW_BY)
    assert review_reminder_due(criteria, today) is reminder_due


@pytest.mark.parametrize(
    ("today", "overdue"),
    [
        (date(2026, 11, 27), False),
        (date(2026, 12, 12), False),
        (date(2026, 12, 13), True),
    ],
)
def test_review_is_overdue_only_after_review_by_passes(today: date, overdue: bool) -> None:
    criteria = ucr_west(review_by=REVIEW_BY)
    assert is_review_overdue(criteria, today) is overdue


def test_the_reminder_window_is_fourteen_days() -> None:
    assert REVIEW_REMINDER_BEFORE.days == 14


@given(
    review_by=st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31)),
    today=st.dates(min_value=date(1999, 12, 1), max_value=date(2100, 1, 31)),
)
def test_reminder_and_overdue_never_both_hold_and_follow_the_window(
    review_by: date, today: date
) -> None:
    criteria = ucr_west(review_by=review_by)
    reminder = review_reminder_due(criteria, today)
    overdue = is_review_overdue(criteria, today)
    assert not (reminder and overdue)
    assert overdue is (today > review_by)
    assert reminder is (review_by - REVIEW_REMINDER_BEFORE <= today <= review_by)


@pytest.mark.parametrize(
    "instant",
    [datetime(2026, 12, 13, 0, 30, tzinfo=UTC), datetime(2026, 12, 13)],
)
def test_a_datetime_is_refused_as_today(instant: datetime) -> None:
    # The caller passes the London calendar date (to_london(instant).date()), never an instant.
    criteria = ucr_west(review_by=REVIEW_BY)
    with pytest.raises(ValidationFailed):
        is_review_overdue(criteria, instant)  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        review_reminder_due(criteria, instant)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("confirmed_on", "months", "expected"),
    [
        (date(2026, 8, 31), 6, date(2027, 2, 28)),
        (date(2027, 8, 31), 6, date(2028, 2, 29)),
        (date(2028, 2, 29), 12, date(2029, 2, 28)),
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2026, 12, 31), 12, date(2027, 12, 31)),
    ],
)
def test_next_review_by_clamps_to_the_last_day_of_the_month(
    confirmed_on: date, months: int, expected: date
) -> None:
    assert next_review_by(confirmed_on, months) == expected


@pytest.mark.parametrize("months", [0, 1, 4, 9, 24, -3, True, 6.0])
def test_next_review_by_refuses_any_period_other_than_3_6_or_12(months: object) -> None:
    with pytest.raises(ValidationFailed):
        next_review_by(date(2026, 8, 31), months)  # type: ignore[arg-type]


def test_next_review_by_refuses_a_datetime() -> None:
    with pytest.raises(ValidationFailed):
        next_review_by(datetime(2026, 8, 31, tzinfo=UTC), 6)  # type: ignore[arg-type]


@given(
    confirmed_on=st.dates(min_value=date(2000, 1, 1), max_value=date(2090, 12, 31)),
    months=st.sampled_from([3, 6, 12]),
)
def test_next_review_by_is_later_and_never_past_the_same_day_of_month(
    confirmed_on: date, months: int
) -> None:
    result = next_review_by(confirmed_on, months)
    assert result > confirmed_on
    total = (result.year - confirmed_on.year) * 12 + (result.month - confirmed_on.month)
    assert total == months
    assert result.day <= confirmed_on.day


def test_approving_the_next_version_supersedes_the_current_one() -> None:
    v3 = ucr_west()
    v4 = ucr_west(
        id="crit-ucr-west-4",
        version=4,
        status=C.PENDING_APPROVAL,
        supersedes_id="crit-ucr-west-3",
    )
    old, new = approve(v3, v4)
    assert old == replace(v3, status=C.SUPERSEDED)
    assert new == replace(v4, status=C.CURRENT)


def test_approving_a_version_that_skips_a_number_is_refused() -> None:
    v3 = ucr_west()
    v5 = ucr_west(
        id="crit-ucr-west-5",
        version=5,
        status=C.PENDING_APPROVAL,
        supersedes_id="crit-ucr-west-3",
    )
    with pytest.raises(ValidationFailed):
        approve(v3, v5)


def test_approving_a_version_that_supersedes_another_record_is_refused() -> None:
    v3 = ucr_west()
    v4 = ucr_west(
        id="crit-ucr-west-4",
        version=4,
        status=C.PENDING_APPROVAL,
        supersedes_id="crit-ucr-west-2",
    )
    with pytest.raises(ValidationFailed):
        approve(v3, v4)


def test_approving_a_version_of_another_service_is_refused() -> None:
    v3 = ucr_west()
    other = ucr_west(
        id="crit-other-4",
        service_id="svc-other",
        version=4,
        status=C.PENDING_APPROVAL,
        supersedes_id="crit-ucr-west-3",
    )
    with pytest.raises(ValidationFailed):
        approve(v3, other)


def test_approving_the_first_version_with_no_current_one() -> None:
    v1 = ucr_west(
        id="crit-ucr-west-1",
        version=1,
        status=C.PENDING_APPROVAL,
        supersedes_id=None,
    )
    old, new = approve(None, v1)
    assert old is None
    assert new == replace(v1, status=C.CURRENT)


def test_approving_a_draft_is_refused() -> None:
    v3 = ucr_west()
    v4_draft = ucr_west(
        id="crit-ucr-west-4",
        version=4,
        status=C.DRAFT,
        supersedes_id="crit-ucr-west-3",
    )
    with pytest.raises(InvalidTransition):
        approve(v3, v4_draft)


def test_approving_a_version_that_is_already_current_is_refused() -> None:
    v3 = ucr_west()
    with pytest.raises(InvalidTransition):
        approve(None, v3)


def test_approving_over_a_superseded_current_is_refused() -> None:
    v3 = ucr_west(status=C.SUPERSEDED)
    v4 = ucr_west(
        id="crit-ucr-west-4",
        version=4,
        status=C.PENDING_APPROVAL,
        supersedes_id="crit-ucr-west-3",
    )
    with pytest.raises(InvalidTransition):
        approve(v3, v4)
