"""Capacity reply policy (D11): record, correct, refuse late, refuse a third Y, or ask again.

Rules: docs/spec/domain-rules.md section 2.2. Sample values only (UCR West), no patient data.
Service UCR West, usual range (0, 8), recorded value 3, unless a test says otherwise. Dates are
2026-10-23 (BST, UTC+1). The clock-change tests use 2026-10-25, when London goes from BST to GMT.
Every comparison in the rule is between instants (lesson L4).
"""

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import ReportFlagReason
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules import reply_policy as reply_policy_rules
from diucs.domain.rules.london_time import LONDON
from diucs.domain.rules.reply_parser import Confirm, Number
from diucs.domain.rules.reply_policy import (
    CORRECTION_WINDOW,
    MAX_CONSECUTIVE_CONFIRMS,
    AskRecheck,
    Decision,
    NeedNumber,
    PromptState,
    RecordConfirm,
    RecordNumber,
    RejectConfirmLimit,
    RejectLate,
    decide_capacity_reply,
)
from tests.support.policy_samples import policies, policy

SERVICE = "svc-ucr-west"
RANGE = (0, 8)
DAY = date(2026, 10, 23)
OUT_OF_RANGE_TWICE = ReportFlagReason.OUT_OF_RANGE_TWICE


def london(hour: int, minute: int = 0, day: date = DAY, fold: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=LONDON, fold=fold)


def state(**overrides: object) -> PromptState:
    fields: dict[str, object] = {
        "service_id": SERVICE,
        "reply_by": london(10, 30),
        "recorded_value": 3,
        "consecutive_confirms": 0,
        "last_accepted_at": None,
        "last_accepted_value": None,
        "pending_out_of_range": None,
        "usual_range": RANGE,
    }
    fields.update(overrides)
    return PromptState(**fields)  # type: ignore[arg-type]


def decide(reply: Confirm | Number, prompt: PromptState, now: datetime) -> Decision:
    return decide_capacity_reply(reply, prompt, now)


def record(
    value: int, *, correction: bool = False, flag: ReportFlagReason | None = None
) -> RecordNumber:
    return RecordNumber(value, correction, flag)


# Rule 1: a reply within an open prompt is recorded.


def test_number_inside_open_prompt_is_recorded() -> None:
    decision = decide(Number(4), state(reply_by=london(10, 30)), london(10, 12))
    assert decision == RecordNumber(4, False, None)


def test_reply_at_exactly_reply_by_is_on_time() -> None:
    decision = decide(Number(5), state(reply_by=london(12, 30)), london(12, 30))
    assert decision == RecordNumber(5, False, None)


def test_zero_means_closed_and_is_in_range() -> None:
    decision = decide(Number(0), state(), london(10, 12))
    assert decision == RecordNumber(0, False, None)


def test_top_of_usual_range_is_recorded_and_one_above_is_asked_again() -> None:
    assert decide(Number(8), state(), london(10, 12)) == RecordNumber(8, False, None)
    assert decide(Number(9), state(), london(10, 12)) == AskRecheck(9)


# Rule 2: Y confirms, at most two in a row.


@pytest.mark.parametrize("confirms", [0, 1])
def test_y_confirms_while_under_the_limit(confirms: int) -> None:
    decision = decide(Confirm(), state(consecutive_confirms=confirms), london(10, 12))
    assert decision == RecordConfirm()


def test_third_y_is_refused_at_the_limit() -> None:
    assert MAX_CONSECUTIVE_CONFIRMS == 2
    decision = decide(Confirm(), state(consecutive_confirms=2), london(10, 12))
    assert decision == RejectConfirmLimit()


# Rule 3: Y cannot confirm a figure that was never recorded.


def test_y_with_no_recorded_figure_asks_for_a_number() -> None:
    decision = decide(Confirm(), state(recorded_value=None), london(10, 12))
    assert decision == NeedNumber()


# Rule 4: a reply with no open prompt is late. Its value is not used.


def test_late_number_is_refused_with_a_fresh_reply_by() -> None:
    late = state(reply_by=london(12, 30), last_accepted_at=london(8, 15))
    decision = decide(Number(5), late, london(12, 41))
    assert decision == RejectLate(london(13, 11))


def test_late_y_is_refused_with_a_fresh_reply_by() -> None:
    late = state(reply_by=london(12, 30), last_accepted_at=london(8, 15))
    decision = decide(Confirm(), late, london(12, 41))
    assert decision == RejectLate(london(13, 11))


def test_no_prompt_and_no_recent_report_is_late() -> None:
    decision = decide(Number(2), state(reply_by=None, last_accepted_at=None), london(12, 0))
    assert decision == RejectLate(london(12, 30))


def test_late_out_of_range_number_is_refused_not_asked_again() -> None:
    late = state(reply_by=london(12, 30), last_accepted_at=london(8, 15))
    decision = decide(Number(40), late, london(12, 41))
    assert decision == RejectLate(london(13, 11))


# Rule 5: a correction replaces an accepted report within 15 minutes, even after the prompt closed.


def test_correction_within_fifteen_minutes_after_prompt_closed() -> None:
    closed = state(reply_by=london(14, 0), last_accepted_at=london(14, 10), last_accepted_value=4)
    assert decide(Number(3), closed, london(14, 14)) == record(3, correction=True)


def test_correction_at_exactly_fifteen_minutes_is_still_a_correction() -> None:
    closed = state(reply_by=london(14, 0), last_accepted_at=london(14, 10), last_accepted_value=4)
    assert decide(Number(3), closed, london(14, 25)) == record(3, correction=True)


def test_correction_one_minute_past_the_window_is_late() -> None:
    closed = state(reply_by=london(14, 0), last_accepted_at=london(14, 10), last_accepted_value=4)
    assert decide(Number(3), closed, london(14, 26)) == RejectLate(london(14, 56))


def test_correction_inside_an_open_prompt_is_marked_as_a_correction() -> None:
    open_prompt = state(
        reply_by=london(14, 30), last_accepted_at=london(14, 10), last_accepted_value=4
    )
    assert decide(Number(2), open_prompt, london(14, 15)) == record(2, correction=True)


def test_correction_window_is_fifteen_minutes() -> None:
    assert timedelta(minutes=15) == CORRECTION_WINDOW


def test_y_after_the_prompt_closed_is_late_even_inside_the_correction_window() -> None:
    # A Y is a confirmation, not a figure, so the correction window does not apply to it.
    closed = state(reply_by=london(14, 0), last_accepted_at=london(14, 10), last_accepted_value=4)
    assert decide(Confirm(), closed, london(14, 14)) == RejectLate(london(14, 44))


def test_correction_window_measured_between_instants_across_the_clock_change() -> None:
    # 2026-10-25: 01:59 BST (fold 0) is 00:59 UTC. 01:05 GMT (fold 1) is 01:05 UTC.
    # Six minutes apart in real time. Wall-clock subtraction would give minus 54 minutes.
    accepted = datetime(2026, 10, 25, 1, 59, tzinfo=LONDON, fold=0)
    now = datetime(2026, 10, 25, 1, 5, tzinfo=LONDON, fold=1)
    prompt = state(reply_by=None, last_accepted_at=accepted, last_accepted_value=4)
    assert decide(Number(4), prompt, now) == record(4, correction=True)


def test_correction_window_across_the_clock_change_is_not_stretched() -> None:
    # 01:00 BST (00:00 UTC) to 01:20 GMT (01:20 UTC) is 80 minutes, though the wall clock
    # shows only 20. It must be late.
    accepted = datetime(2026, 10, 25, 1, 0, tzinfo=LONDON, fold=0)
    now = datetime(2026, 10, 25, 1, 20, tzinfo=LONDON, fold=1)
    prompt = state(reply_by=None, last_accepted_at=accepted, last_accepted_value=4)
    decision = decide(Number(4), prompt, now)
    assert isinstance(decision, RejectLate)


# Rule 6: a number outside the usual range is asked again the first time, recorded the second.


def test_out_of_range_number_in_open_prompt_is_asked_again() -> None:
    assert decide(Number(40), state(), london(10, 12)) == AskRecheck(40)


def test_same_out_of_range_number_again_is_recorded_with_a_flag() -> None:
    prompt = state(pending_out_of_range=40)
    decision = decide(Number(40), prompt, london(10, 12))
    assert decision == record(40, flag=OUT_OF_RANGE_TWICE)


def test_different_out_of_range_number_is_asked_again() -> None:
    prompt = state(pending_out_of_range=40)
    assert decide(Number(41), prompt, london(10, 12)) == AskRecheck(41)


def test_out_of_range_correction_is_asked_again() -> None:
    corrected = state(
        reply_by=london(14, 0), last_accepted_at=london(14, 10), last_accepted_value=4
    )
    assert decide(Number(40), corrected, london(14, 14)) == AskRecheck(40)


def test_out_of_range_correction_repeated_is_recorded_as_correction_with_flag() -> None:
    corrected = state(
        reply_by=london(14, 0),
        last_accepted_at=london(14, 10),
        last_accepted_value=4,
        pending_out_of_range=40,
    )
    decision = decide(Number(40), corrected, london(14, 14))
    assert decision == record(40, correction=True, flag=OUT_OF_RANGE_TWICE)


# Letters: a reply must name the service this prompt is for. The policy checks it itself, so a
# caller that forgets to check cannot record a figure against the wrong service (DEC-031).


def test_letter_for_another_service_is_refused_not_recorded() -> None:
    prompt = state(letter="A")
    with pytest.raises(ValidationFailed):
        decide(Confirm(letter="B"), prompt, london(10, 12))
    with pytest.raises(ValidationFailed):
        decide(Number(4, letter="B"), prompt, london(10, 12))


def test_letter_refusal_comes_before_the_timing_rules() -> None:
    closed = state(letter="A", reply_by=london(9, 0))
    with pytest.raises(ValidationFailed):
        decide(Confirm(letter="B"), closed, london(10, 12))


def test_letter_matching_this_service_is_accepted() -> None:
    assert decide(Number(4, letter="A"), state(letter="A"), london(10, 12)) == RecordNumber(
        4, False, None
    )
    assert decide(Confirm(letter="A"), state(letter="A"), london(10, 12)) == RecordConfirm()


def test_letter_on_a_single_service_prompt_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        decide(Number(4, letter="A"), state(letter=None), london(10, 12))


def test_bare_number_on_a_lettered_prompt_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        decide(Number(4), state(letter="A"), london(10, 12))


def test_bare_y_on_a_lettered_prompt_confirms_the_prompt() -> None:
    # domain-rules 2.1: Y on a multi-service prompt confirms all services in the prompt.
    assert decide(Confirm(), state(letter="A"), london(10, 12)) == RecordConfirm()


# Fail closed: a naive datetime is refused. It is never read as the machine's local time.


@pytest.mark.parametrize("field", ["now", "reply_by", "last_accepted_at"])
def test_naive_datetime_is_refused_not_guessed(field: str) -> None:
    naive = datetime(2026, 10, 23, 12, 0)  # noqa: DTZ001 - the point of the test
    prompt = state(reply_by=london(12, 30), last_accepted_at=london(12, 0))
    now = london(12, 10)
    if field == "now":
        now = naive
    elif field == "reply_by":
        prompt = replace(prompt, reply_by=naive)
    else:
        prompt = replace(prompt, last_accepted_at=naive)
    with pytest.raises(ValidationFailed):
        decide(Number(4), prompt, now)


# Property tests: the decision is never a recorded figure outside the usual range, unless it is
# the second time the same figure has come in (flag out-of-range-twice).

ALL_REPLIES: st.SearchStrategy[Confirm | Number] = st.one_of(
    st.just(Confirm()), st.integers(min_value=0, max_value=999).map(Number)
)
MINUTES_BEFORE_NOW = st.integers(min_value=-60, max_value=120)


@given(
    reply=ALL_REPLIES,
    pending=st.one_of(st.none(), st.integers(min_value=0, max_value=999)),
    minutes_since_accept=st.one_of(st.none(), MINUTES_BEFORE_NOW),
    minutes_to_reply_by=st.integers(min_value=-60, max_value=60),
    confirms=st.integers(min_value=0, max_value=3),
)
def test_no_figure_outside_the_usual_range_is_recorded_without_the_flag(
    reply: Confirm | Number,
    pending: int | None,
    minutes_since_accept: int | None,
    minutes_to_reply_by: int,
    confirms: int,
) -> None:
    now = london(12, 0)
    accepted = (
        None if minutes_since_accept is None else now - timedelta(minutes=minutes_since_accept)
    )
    prompt = state(
        reply_by=now + timedelta(minutes=minutes_to_reply_by),
        recorded_value=3,
        consecutive_confirms=confirms,
        last_accepted_at=accepted,
        last_accepted_value=3 if accepted else None,
        pending_out_of_range=pending,
    )
    decision = decide(reply, prompt, now)
    if isinstance(decision, RecordNumber) and not (RANGE[0] <= decision.value <= RANGE[1]):
        assert decision.flag is OUT_OF_RANGE_TWICE
        assert decision.value == pending


@given(value=st.integers(min_value=0, max_value=999), minutes_late=st.integers(1, 600))
def test_closed_prompt_without_a_recent_report_refuses_every_number(
    value: int, minutes_late: int
) -> None:
    now = london(12, 0)
    closed = state(reply_by=now - timedelta(minutes=minutes_late), last_accepted_at=None)
    decision = decide(Number(value), closed, now)
    assert decision == RejectLate(now + timedelta(minutes=30))


@given(value=st.integers(min_value=0, max_value=999))
def test_number_in_open_prompt_is_recorded_only_inside_the_range(value: int) -> None:
    now = london(12, 0)
    open_prompt = state(reply_by=now + timedelta(minutes=5), pending_out_of_range=None)
    decision = decide(Number(value), open_prompt, now)
    if RANGE[0] <= value <= RANGE[1]:
        assert decision == RecordNumber(value, False, None)
    else:
        assert decision == AskRecheck(value)


# --- Tenant policy (TEN-021) ----------------------------------------------------------------

EIGHT_MINUTES: Final = timedelta(minutes=8)
ONE_TICK: Final = timedelta(microseconds=1)


def _accepted_at_ten(**overrides: object) -> PromptState:
    """An open prompt (reply by 10:30) with a figure accepted at 10:00."""
    return state(last_accepted_at=london(10, 0), last_accepted_value=3, **overrides)


# Test 17. The correction window: inclusive at its edge, read from the policy.


@pytest.mark.parametrize(
    ("window", "now", "correction"),
    [
        (timedelta(minutes=10), london(10, 8), True),
        (timedelta(minutes=15), london(10, 8), True),
        (timedelta(minutes=5), london(10, 8), False),
        (timedelta(minutes=8), london(10, 8), True),
        (timedelta(minutes=8), london(10, 8) + ONE_TICK, False),
    ],
    ids=["ten", "default", "five", "exactly-eight", "one-tick-past-eight"],
)
def test_a_figure_is_a_correction_inside_the_policy_window_only(
    window: timedelta, now: datetime, correction: bool
) -> None:
    result = decide_capacity_reply(
        Number(4), _accepted_at_ten(), now, policy(correction_window=window)
    )
    assert isinstance(result, RecordNumber)
    assert result.is_correction is correction


def test_the_default_correction_window_is_fifteen_minutes_and_the_edge_is_inclusive() -> None:
    at_edge = decide_capacity_reply(Number(4), _accepted_at_ten(), london(10, 15), DEFAULT_POLICY)
    past_edge = decide_capacity_reply(
        Number(4), _accepted_at_ten(), london(10, 15) + ONE_TICK, DEFAULT_POLICY
    )
    assert isinstance(at_edge, RecordNumber) and at_edge.is_correction
    assert isinstance(past_edge, RecordNumber) and not past_edge.is_correction


# Test 18. The confirm limit comes from the policy.


@pytest.mark.parametrize(
    ("confirms", "limit", "expected"),
    [
        (1, 1, RejectConfirmLimit),
        (1, 2, RecordConfirm),
        (2, 2, RejectConfirmLimit),
        (2, 3, RecordConfirm),
        (3, 3, RejectConfirmLimit),
    ],
)
def test_the_confirm_limit_is_the_policy_value(
    confirms: int, limit: int, expected: type[object]
) -> None:
    prompt = state(consecutive_confirms=confirms)
    result = decide_capacity_reply(
        Confirm(), prompt, london(10, 0), policy(max_consecutive_confirms=limit)
    )
    assert isinstance(result, expected)


# Test 19. RejectLate carries now plus the policy's reply window on both late paths.


def test_late_figure_gets_a_reply_by_of_now_plus_the_policy_window() -> None:
    now = london(11, 0)
    default = decide_capacity_reply(Number(4), state(), now, DEFAULT_POLICY)
    assert default == RejectLate(now + timedelta(minutes=30))
    longer = decide_capacity_reply(
        Number(4),
        state(),
        now,
        policy(reply_window=timedelta(minutes=45), reminder_after=timedelta(minutes=45)),
    )
    assert longer == RejectLate(now + timedelta(minutes=45))


def test_late_y_gets_a_reply_by_of_now_plus_the_policy_window() -> None:
    now = london(11, 0)
    default = decide_capacity_reply(Confirm(), state(), now, DEFAULT_POLICY)
    assert default == RejectLate(now + timedelta(minutes=30))
    longer = decide_capacity_reply(
        Confirm(),
        state(),
        now,
        policy(reply_window=timedelta(minutes=45), reminder_after=timedelta(minutes=45)),
    )
    assert longer == RejectLate(now + timedelta(minutes=45))


# Test 20. The existing sample states decide the same with the default policy passed explicitly.


SAMPLE_STATES: Final = (
    state(),
    state(consecutive_confirms=2),
    state(reply_by=None, recorded_value=None),
    state(reply_by=london(10, 30) - timedelta(hours=2)),
    state(last_accepted_at=london(10, 0), last_accepted_value=3),
    state(pending_out_of_range=9),
)
SAMPLE_REPLIES: Final = (Confirm(), Number(4), Number(9), Number(0))


@pytest.mark.parametrize("prompt", SAMPLE_STATES)
@pytest.mark.parametrize("reply", SAMPLE_REPLIES)
@pytest.mark.parametrize("now", [london(10, 0), london(10, 10), london(11, 0)])
def test_the_default_policy_decides_exactly_as_no_policy(
    prompt: PromptState, reply: Confirm | Number, now: datetime
) -> None:
    try:
        expected: object = decide_capacity_reply(reply, prompt, now)
    except ValidationFailed as refusal:
        expected = refusal
    try:
        actual: object = decide_capacity_reply(reply, prompt, now, DEFAULT_POLICY)
    except ValidationFailed as refusal:
        actual = refusal
    assert type(actual) is type(expected)
    assert actual == expected


# Test 21. Property: a letter mismatch is refused first; the decision reads only three fields.


@given(
    tenant=policies(),
    reply=st.one_of(st.just(Confirm()), st.integers(min_value=0, max_value=10).map(Number)),
    consecutive=st.integers(min_value=0, max_value=3),
    minutes_from_reply_by=st.integers(min_value=-90, max_value=90),
    accepted_minutes_before=st.one_of(st.none(), st.integers(min_value=0, max_value=60)),
)
def test_decision_depends_only_on_the_reply_window_correction_window_and_confirm_limit(
    tenant: TenantPolicy,
    reply: Confirm | Number,
    consecutive: int,
    minutes_from_reply_by: int,
    accepted_minutes_before: int | None,
) -> None:
    now = london(10, 30) + timedelta(minutes=minutes_from_reply_by)
    accepted = (
        None
        if accepted_minutes_before is None
        else now - timedelta(minutes=accepted_minutes_before)
    )
    prompt = PromptState(
        service_id=SERVICE,
        reply_by=london(10, 30),
        recorded_value=3,
        consecutive_confirms=consecutive,
        last_accepted_at=accepted,
        last_accepted_value=3 if accepted is not None else None,
        pending_out_of_range=None,
        usual_range=RANGE,
    )
    other = replace(
        tenant,
        pressure_watch_from=1,
        pressure_high_from=2,
        stale_warning_after=timedelta(hours=1),
        many_changes_count=10,
        alert_default_not_updated_hours=4,
    )
    assert decide_capacity_reply(reply, prompt, now, tenant) == decide_capacity_reply(
        reply, prompt, now, other
    )


@given(tenant=policies(), value=st.integers(min_value=0, max_value=10))
def test_a_letter_mismatch_is_refused_whatever_the_policy(tenant: TenantPolicy, value: int) -> None:
    with pytest.raises(ValidationFailed) as refusal:
        decide_capacity_reply(Number(value, letter="B"), state(letter="A"), london(10, 0), tenant)
    assert refusal.value.field == "letter"


# Test 23 (reply policy part). The module constants are the default policy's own values.


def test_the_reply_policy_constants_are_the_default_policy_values() -> None:
    assert timedelta(minutes=15) == CORRECTION_WINDOW
    assert MAX_CONSECUTIVE_CONFIRMS == 2
    assert reply_policy_rules.CORRECTION_WINDOW is DEFAULT_POLICY.correction_window
    assert DEFAULT_POLICY.max_consecutive_confirms == reply_policy_rules.MAX_CONSECUTIVE_CONFIRMS
