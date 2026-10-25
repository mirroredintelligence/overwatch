"""Service registration state machine and approval gate (D22).

Rules: docs/spec/domain-rules.md section 6. Names: docs/spec/contracts.md, rules/registration.py row.
Pure: no I/O. Time is passed in as an argument; nothing here reads the clock.

DEC-010 stub: the functions below hold no behaviour yet. They raise NotImplementedError so the
red run fails on assertions.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from diucs.domain.codes import RegistrationStatus, ScopeFlag

INVITATION_VALID_FOR = timedelta(hours=48)


@dataclass(frozen=True, slots=True)
class ApprovalChecks:
    automatic_ok: bool
    callback_confirmed: bool
    scope: ScopeFlag | None
    criteria_approved: bool


def transition_registration(
    current: RegistrationStatus, target: RegistrationStatus
) -> RegistrationStatus:
    raise NotImplementedError


def missing_for_approval(checks: ApprovalChecks) -> list[str]:
    raise NotImplementedError


def approve_registration(
    current: RegistrationStatus, checks: ApprovalChecks
) -> RegistrationStatus:
    raise NotImplementedError


def can_invite(flag: ScopeFlag) -> bool:
    raise NotImplementedError


def invitation_valid(sent_at: datetime, now: datetime) -> bool:
    raise NotImplementedError
