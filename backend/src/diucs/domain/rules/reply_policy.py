"""Capacity reply policy (D11): what happens to a capacity reply. Stub for the red commit (DEC-010).

Rules: docs/spec/domain-rules.md section 2.2. Names: docs/spec/contracts.md (rules/reply_policy.py).
Pure: no I/O and no clock; `now` is an argument.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from diucs.domain.codes import ReportFlagReason
from diucs.domain.rules.reply_parser import Confirm, Number

CORRECTION_WINDOW = timedelta(minutes=15)  # [ASSUMED] domain-rules 2.2
MAX_CONSECUTIVE_CONFIRMS = 2


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


def decide_capacity_reply(reply: Confirm | Number, state: PromptState, now: datetime) -> Decision:
    """Decide what happens to one capacity reply. Stub: behaviour is added in the green commit."""
    raise NotImplementedError
