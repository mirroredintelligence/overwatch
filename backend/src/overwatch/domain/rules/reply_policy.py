"""Capacity reply policy (D11): what happens to a capacity reply.

Record it, record it as a correction, refuse it as late, refuse a third Y, or ask the reporter to
send an unusual number again. This is a pure decision; the use case acts on it later.

Rules: docs/spec/domain-rules.md section 2.2. Names: docs/spec/contracts.md (rules/reply_policy.py).
Pure: no I/O and no clock. `now` is an argument. Every datetime is converted to UTC before it is
compared, so the London clock change does not move a window (lesson L4). Points the rule book
leaves open are decided in DEC-031.

The correction window, the confirm limit and the reply window are tenant policy (TEN-021): the
decision takes a `TenantPolicy` as its last argument, defaulting to `DEFAULT_POLICY`.
CORRECTION_WINDOW and MAX_CONSECUTIVE_CONFIRMS are aliases of the default policy's values.

Caller contract (lesson L27): a use case must loop over every item of `parse_reply`'s tuple and
call this function once per item. It never reads `replies[0]` as the whole reply. A reply that
names another service's letter, or a bare figure on a lettered prompt, raises ValidationFailed
here; the policy does not rely on the caller to check letters.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from diucs.domain.codes import ReportFlagReason
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy, require_policy
from diucs.domain.rules.reply_parser import Confirm, Number

# Aliases of the default policy (TEN-021): the numbers are defined once, in tenant_policy.py.
CORRECTION_WINDOW = DEFAULT_POLICY.correction_window
MAX_CONSECUTIVE_CONFIRMS = DEFAULT_POLICY.max_consecutive_confirms


@dataclass(frozen=True, slots=True)
class PromptState:
    service_id: str
    reply_by: datetime | None
    recorded_value: int | None
    consecutive_confirms: int
    last_accepted_at: datetime | None
    last_accepted_value: int | None
    pending_out_of_range: int | None
    usual_range: tuple[int, int]
    letter: str | None = None  # the service letter of this prompt; None for one service


@dataclass(frozen=True, slots=True)
class RecordNumber:
    value: int
    is_correction: bool
    flag: ReportFlagReason | None


@dataclass(frozen=True, slots=True)
class RecordConfirm:
    pass


@dataclass(frozen=True, slots=True)
class RejectLate:
    new_reply_by: datetime


@dataclass(frozen=True, slots=True)
class RejectConfirmLimit:
    pass


@dataclass(frozen=True, slots=True)
class AskRecheck:
    value: int


@dataclass(frozen=True, slots=True)
class NeedNumber:
    pass


Decision = RecordNumber | RecordConfirm | RejectLate | RejectConfirmLimit | AskRecheck | NeedNumber


def decide_capacity_reply(
    reply: Confirm | Number,
    state: PromptState,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> Decision:
    """Decide what happens to one capacity reply. Only decides; `state` is not changed.

    Order: the service letter is checked first (ValidationFailed on a mismatch). Then a Y is judged
    against the open prompt only. A figure inside the correction window is a correction, whether or
    not the prompt is open. Otherwise a figure needs an open prompt. Anything else is late. A
    datetime without a UTC offset raises ValidationFailed.
    """
    policy = require_policy(policy)
    _check_letter(reply, state)
    now_utc = _instant("now", now)
    reply_by_utc = None if state.reply_by is None else _instant("reply_by", state.reply_by)
    accepted_utc = (
        None
        if state.last_accepted_at is None
        else _instant("last_accepted_at", state.last_accepted_at)
    )
    prompt_open = reply_by_utc is not None and now_utc <= reply_by_utc
    if isinstance(reply, Confirm):
        return _decide_confirm(state, now, prompt_open, policy)
    if accepted_utc is not None and _in_correction_window(
        now_utc, accepted_utc, policy.correction_window
    ):
        return _decide_figure(reply.value, state, is_correction=True)
    if prompt_open:
        return _decide_figure(reply.value, state, is_correction=False)
    return RejectLate(now + policy.reply_window)


def _check_letter(reply: Confirm | Number, state: PromptState) -> None:
    if reply.letter is not None and reply.letter != state.letter:
        raise ValidationFailed("letter", "the reply names a service this prompt is not for")
    if reply.letter is None and isinstance(reply, Number) and state.letter is not None:
        raise ValidationFailed("letter", "a figure for a lettered prompt must name its service")


def _decide_confirm(
    state: PromptState, now: datetime, prompt_open: bool, policy: TenantPolicy
) -> Decision:
    if not prompt_open:
        return RejectLate(now + policy.reply_window)
    if state.recorded_value is None:
        return NeedNumber()
    if state.consecutive_confirms >= policy.max_consecutive_confirms:
        return RejectConfirmLimit()
    return RecordConfirm()


def _decide_figure(value: int, state: PromptState, *, is_correction: bool) -> Decision:
    low, high = state.usual_range
    if low <= value <= high:
        return RecordNumber(value, is_correction, None)
    if state.pending_out_of_range == value:
        return RecordNumber(value, is_correction, ReportFlagReason.OUT_OF_RANGE_TWICE)
    return AskRecheck(value)


def _in_correction_window(now_utc: datetime, accepted_utc: datetime, window: timedelta) -> bool:
    elapsed = now_utc - accepted_utc
    return timedelta(0) <= elapsed <= window


def _instant(field: str, value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValidationFailed(field, "a timezone-aware datetime is needed")
    return value.astimezone(UTC)
