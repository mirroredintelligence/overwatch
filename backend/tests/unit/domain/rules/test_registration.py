"""Service registration state machine and approval gate (D22).

Rules: docs/spec/domain-rules.md section 6 (6.1 states, 6.2 rules). Names: docs/spec/contracts.md.
"""

import itertools
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import CriteriaStatus, RegistrationStatus, ScopeFlag
from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.rules.registration import (
    INVITATION_VALID_FOR,
    ApprovalChecks,
    approve_registration,
    can_invite,
    invitation_valid,
    missing_for_approval,
    transition_registration,
)

R = RegistrationStatus

# domain-rules.md 6.1: the only legal moves. A tuple, not a set, so test ids are stable.
LEGAL_MOVES: tuple[tuple[RegistrationStatus, RegistrationStatus], ...] = (
    (R.INVITED, R.DRAFT),
    (R.DRAFT, R.SUBMITTED),
    (R.SUBMITTED, R.IN_REVIEW),
    (R.IN_REVIEW, R.NEEDS_CHANGES),
    (R.IN_REVIEW, R.APPROVED),
    (R.IN_REVIEW, R.NOT_APPROVED),
    (R.NEEDS_CHANGES, R.SUBMITTED),
    (R.APPROVED, R.LIVE),
    (R.LIVE, R.PAUSED),
    (R.LIVE, R.REVERIFY),
    (R.PAUSED, R.LIVE),
    (R.REVERIFY, R.LIVE),
    (R.NOT_APPROVED, R.IN_REVIEW),
)

ILLEGAL_MOVES = tuple(pair for pair in itertools.product(R, R) if pair not in LEGAL_MOVES)

COMPLETE = ApprovalChecks(
    automatic_ok=True,
    callback_confirmed=True,
    scope=ScopeFlag.IN_PILOT,
    criteria_approved=True,
)

# Screen wording, ui-screens.md artboard "ApprovalStates", in the order the screen lists them.
MISSING_TEXT = (
    "Automatic checks passed or explained",
    "Call-back done",
    "Scope decided: in pilot",
    "Criteria second approval",
)


# --- transitions -------------------------------------------------------------------------


@pytest.mark.parametrize(("current", "target"), LEGAL_MOVES)
def test_each_legal_move_succeeds(current: RegistrationStatus, target: RegistrationStatus) -> None:
    assert transition_registration(current, target) is target


@pytest.mark.parametrize(("current", "target"), ILLEGAL_MOVES)
def test_every_other_move_raises_invalid_transition(
    current: RegistrationStatus, target: RegistrationStatus
) -> None:
    with pytest.raises(InvalidTransition):
        transition_registration(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (R.DRAFT, R.APPROVED),
        (R.LIVE, R.DRAFT),
        (R.INVITED, R.SUBMITTED),
    ],
)
def test_named_illegal_moves_from_the_brief_raise(
    current: RegistrationStatus, target: RegistrationStatus
) -> None:
    with pytest.raises(InvalidTransition):
        transition_registration(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        # CriteriaStatus.DRAFT and RegistrationStatus.DRAFT are both "draft" and compare equal.
        # Lesson L3: the transition must refuse a member of the wrong enum, not match it by value.
        (CriteriaStatus.DRAFT, R.SUBMITTED),
        (R.INVITED, CriteriaStatus.DRAFT),
    ],
)
def test_a_member_of_another_enum_with_the_same_value_is_refused(
    current: object, target: object
) -> None:
    with pytest.raises(ValidationFailed):
        transition_registration(current, target)  # type: ignore[arg-type]


# --- approval gate: what is missing ---------------------------------------------------------


def test_complete_checks_leave_nothing_missing() -> None:
    assert missing_for_approval(COMPLETE) == []


def test_nothing_done_lists_all_four_in_screen_order() -> None:
    checks = ApprovalChecks(
        automatic_ok=False, callback_confirmed=False, scope=None, criteria_approved=False
    )
    assert missing_for_approval(checks) == list(MISSING_TEXT)


@pytest.mark.parametrize("scope", [None, ScopeFlag.LATER, ScopeFlag.OUT_OF_SCOPE])
def test_scope_not_in_pilot_is_the_only_missing_item(scope: ScopeFlag | None) -> None:
    checks = ApprovalChecks(True, True, scope, True)
    assert missing_for_approval(checks) == ["Scope decided: in pilot"]


@pytest.mark.parametrize(
    ("checks", "expected"),
    [
        (ApprovalChecks(False, True, ScopeFlag.IN_PILOT, True), MISSING_TEXT[0]),
        (ApprovalChecks(True, False, ScopeFlag.IN_PILOT, True), MISSING_TEXT[1]),
        (ApprovalChecks(True, True, ScopeFlag.LATER, True), MISSING_TEXT[2]),
        (ApprovalChecks(True, True, ScopeFlag.IN_PILOT, False), MISSING_TEXT[3]),
    ],
)
def test_each_single_failure_reports_only_its_own_item(
    checks: ApprovalChecks, expected: str
) -> None:
    assert missing_for_approval(checks) == [expected]


@given(
    automatic_ok=st.booleans(),
    callback_confirmed=st.booleans(),
    scope=st.none() | st.sampled_from(list(ScopeFlag)),
    criteria_approved=st.booleans(),
)
def test_nothing_missing_exactly_when_all_four_hold(
    automatic_ok: bool,
    callback_confirmed: bool,
    scope: ScopeFlag | None,
    criteria_approved: bool,
) -> None:
    checks = ApprovalChecks(automatic_ok, callback_confirmed, scope, criteria_approved)
    all_hold = (
        automatic_ok and callback_confirmed and scope is ScopeFlag.IN_PILOT and criteria_approved
    )
    assert (missing_for_approval(checks) == []) is all_hold


# --- approval gate: approve ----------------------------------------------------------------


def test_complete_checks_from_in_review_approve() -> None:
    assert approve_registration(R.IN_REVIEW, COMPLETE) is R.APPROVED


def test_incomplete_checks_raise_not_allowed_naming_the_missing_item() -> None:
    checks = ApprovalChecks(True, False, ScopeFlag.IN_PILOT, True)
    with pytest.raises(NotAllowed, match="Call-back done"):
        approve_registration(R.IN_REVIEW, checks)


def test_not_allowed_message_lists_every_missing_item_in_order() -> None:
    checks = ApprovalChecks(False, False, None, False)
    with pytest.raises(NotAllowed) as raised:
        approve_registration(R.IN_REVIEW, checks)
    message = str(raised.value)
    positions = [message.index(text) for text in MISSING_TEXT]
    assert positions == sorted(positions)


def test_complete_checks_from_submitted_raise_invalid_transition() -> None:
    with pytest.raises(InvalidTransition):
        approve_registration(R.SUBMITTED, COMPLETE)


def test_incomplete_checks_from_submitted_raise_invalid_transition() -> None:
    # The state is checked before the checks, so the wrong state is reported first.
    with pytest.raises(InvalidTransition):
        approve_registration(R.SUBMITTED, ApprovalChecks(False, False, None, False))


@pytest.mark.parametrize("current", [s for s in R if s is not R.IN_REVIEW])
def test_approve_from_any_other_state_raises_invalid_transition(
    current: RegistrationStatus,
) -> None:
    with pytest.raises(InvalidTransition):
        approve_registration(current, COMPLETE)


# --- invitations ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", list(ScopeFlag))
def test_can_invite_only_when_in_pilot(flag: ScopeFlag) -> None:
    assert can_invite(flag) is (flag is ScopeFlag.IN_PILOT)


def test_invitation_lasts_48_hours() -> None:
    assert timedelta(hours=48) == INVITATION_VALID_FOR


def test_invitation_sent_23_oct_0900_utc_is_valid_until_25_oct_0900_utc() -> None:
    sent = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    assert invitation_valid(sent, datetime(2026, 10, 24, 9, 0, tzinfo=UTC)) is True
    assert invitation_valid(sent, datetime(2026, 10, 25, 8, 59, 59, tzinfo=UTC)) is True
    assert invitation_valid(sent, datetime(2026, 10, 25, 9, 0, tzinfo=UTC)) is False


def test_invitation_compares_instants_not_wall_clock_times() -> None:
    # 10:00 at UTC+1 is 09:00 UTC, so the window must close at 09:00 UTC on 25 Oct.
    bst = timezone(timedelta(hours=1))
    sent = datetime(2026, 10, 23, 10, 0, tzinfo=bst)
    assert invitation_valid(sent, datetime(2026, 10, 25, 8, 59, 59, tzinfo=UTC)) is True
    assert invitation_valid(sent, datetime(2026, 10, 25, 9, 0, tzinfo=UTC)) is False


def test_naive_sent_at_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        invitation_valid(datetime(2026, 10, 23, 9, 0), datetime(2026, 10, 24, 9, 0, tzinfo=UTC))


def test_naive_now_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        invitation_valid(datetime(2026, 10, 23, 9, 0, tzinfo=UTC), datetime(2026, 10, 24, 9, 0))
