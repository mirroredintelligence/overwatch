"""Service registration state machine and approval gate (D22).

Rules: docs/spec/domain-rules.md section 6 (6.1 states, 6.2 rules, including the approval
checklist). Names: docs/spec/contracts.md, rules/registration.py row.
Pure: no I/O. Time is passed in as an argument; nothing here reads the clock.

Lookups are keyed by RegistrationStatus members only, and every incoming value is checked to be
a RegistrationStatus first. CriteriaStatus.DRAFT and RegistrationStatus.DRAFT are both "draft" and
compare equal, so a bare dictionary lookup would accept the wrong enum (see lesson L3).

Approval is fail closed: a registration reaches approved only from in-review, with all four checks
passing. The gate takes booleans, not actor identities, so it cannot check who approved; see
DEC-032 for where that check lives.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

from diucs.domain.codes import RegistrationStatus, ScopeFlag
from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed

INVITATION_VALID_FOR = timedelta(hours=48)

_R = RegistrationStatus

# domain-rules.md 6.1 and the brief: the only legal moves. Everything else is refused.
_ALLOWED: Mapping[RegistrationStatus, frozenset[RegistrationStatus]] = MappingProxyType(
    {
        _R.INVITED: frozenset({_R.DRAFT}),
        _R.DRAFT: frozenset({_R.SUBMITTED}),
        _R.SUBMITTED: frozenset({_R.IN_REVIEW}),
        _R.IN_REVIEW: frozenset({_R.NEEDS_CHANGES, _R.APPROVED, _R.NOT_APPROVED}),
        _R.NEEDS_CHANGES: frozenset({_R.SUBMITTED}),
        _R.APPROVED: frozenset({_R.LIVE}),
        _R.LIVE: frozenset({_R.PAUSED, _R.REVERIFY}),
        _R.PAUSED: frozenset({_R.LIVE}),
        _R.REVERIFY: frozenset({_R.LIVE}),
        _R.NOT_APPROVED: frozenset({_R.IN_REVIEW}),
    }
)

# Screen wording, ui-screens.md artboard "ApprovalStates", in the order the screen lists them.
_MISSING_AUTOMATIC = "Automatic checks passed or explained"
_MISSING_CALLBACK = "Call-back done"
_MISSING_SCOPE = "Scope decided: in pilot"
_MISSING_CRITERIA = "Criteria second approval"


@dataclass(frozen=True, slots=True)
class ApprovalChecks:
    automatic_ok: bool
    callback_confirmed: bool
    scope: ScopeFlag | None
    criteria_approved: bool


def _registration_status(status: object, field: str) -> RegistrationStatus:
    if not isinstance(status, RegistrationStatus):
        raise ValidationFailed(field, "not a registration status")
    return status


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be timezone-aware")
    return value


def transition_registration(
    current: RegistrationStatus, target: RegistrationStatus
) -> RegistrationStatus:
    checked_current = _registration_status(current, "current")
    checked_target = _registration_status(target, "target")
    if checked_target not in _ALLOWED[checked_current]:
        raise InvalidTransition(
            f"registration cannot move from {checked_current.value} to {checked_target.value}"
        )
    return checked_target


def missing_for_approval(checks: ApprovalChecks) -> list[str]:
    # `is not True` and `is not ScopeFlag.IN_PILOT` fail closed: anything other than the
    # exact passing value counts as missing.
    missing: list[str] = []
    if checks.automatic_ok is not True:
        missing.append(_MISSING_AUTOMATIC)
    if checks.callback_confirmed is not True:
        missing.append(_MISSING_CALLBACK)
    if checks.scope is not ScopeFlag.IN_PILOT:
        missing.append(_MISSING_SCOPE)
    if checks.criteria_approved is not True:
        missing.append(_MISSING_CRITERIA)
    return missing


def approve_registration(
    current: RegistrationStatus, checks: ApprovalChecks
) -> RegistrationStatus:
    # The state is checked first: approval is only a move from in-review.
    approved = transition_registration(current, _R.APPROVED)
    missing = missing_for_approval(checks)
    if missing:
        raise NotAllowed("Approve is unavailable until: " + "; ".join(missing))
    return approved


def can_invite(flag: ScopeFlag) -> bool:
    return flag is ScopeFlag.IN_PILOT


def invitation_valid(sent_at: datetime, now: datetime) -> bool:
    sent = _aware(sent_at, "sent_at")
    current = _aware(now, "now")
    return current < sent + INVITATION_VALID_FOR
