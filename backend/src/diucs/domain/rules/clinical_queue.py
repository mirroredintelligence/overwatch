"""Clinical advice queue and presence rules (D23).

Rules: docs/spec/domain-rules.md section 5. Names: docs/spec/contracts.md. Decision DEC-039 records
the choices the prompt leaves open: a lapsed lock refuses advice, a plain string is not a presence,
and an unknown presence or an unknown queue state fails closed.

Pure: no I/O and no clock. `now` is an argument. Every instant must be timezone-aware and is
compared in UTC.

The take timeout is tenant policy (TEN-064): `take`, `return_if_idle` and `give_advice` take a
`TenantPolicy` as their last argument, defaulting to `DEFAULT_POLICY`, and read
`clinical_take_timeout`. `TAKE_TIMEOUT` is an alias of the default policy.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy, require_policy

# Alias of the default policy (TEN-064): the number is defined once, in tenant_policy.py.
TAKE_TIMEOUT: Final = DEFAULT_POLICY.clinical_take_timeout
NOTE_MAX: Final = 280

URGENCY_NOW: Final = "now"
URGENCY_WITHIN_15_MIN: Final = "within-15-min"
_URGENCY_RANK: Final = {URGENCY_NOW: 0, URGENCY_WITHIN_15_MIN: 1}


class Presence(StrEnum):
    AVAILABLE = "available"
    BUSY = "busy"
    AWAY = "away"


def _utc(value: datetime, name: str) -> datetime:
    """Refuse naive datetimes and return the instant in UTC. Same-zone arithmetic is wall-clock
    arithmetic, so every instant is converted before it is compared or subtracted (lesson L4)."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(name, "must be timezone-aware")
    return value.astimezone(UTC)


def _clinician(clinician_id: str) -> str:
    if not isinstance(clinician_id, str) or not clinician_id.strip():
        raise ValidationFailed("clinician_id", "is required")
    return clinician_id


@dataclass(frozen=True, slots=True)
class ClinicalRequest:
    id: str
    case_id: str
    urgency: str
    requested_at: datetime
    taken_by: str | None = None
    taken_at: datetime | None = None
    advised_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.urgency not in _URGENCY_RANK:
            raise ValidationFailed("urgency", "must be 'now' or 'within-15-min'")
        _utc(self.requested_at, "requested_at")
        if (self.taken_by is None) != (self.taken_at is None):
            raise ValidationFailed("taken_by", "taken_by and taken_at are set together")
        if self.taken_at is not None:
            _utc(self.taken_at, "taken_at")
        if self.advised_at is not None:
            _utc(self.advised_at, "advised_at")
            if self.taken_by is None:
                raise ValidationFailed("advised_at", "an advised request has a taker")


def _is_idle(request: ClinicalRequest, now: datetime, policy: TenantPolicy) -> bool:
    return (
        request.taken_at is not None
        and now - _utc(request.taken_at, "taken_at") >= policy.clinical_take_timeout
    )


def take(
    request: ClinicalRequest,
    clinician_id: str,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> ClinicalRequest:
    """Lock the request to this clinician. A lock held by someone else is free once idle."""
    policy = require_policy(policy)
    clinician = _clinician(clinician_id)
    now = _utc(now, "now")
    if request.advised_at is not None:
        raise InvalidTransition("this request has already had advice")
    if request.taken_by is None or _is_idle(request, now, policy):
        return replace(request, taken_by=clinician, taken_at=now)
    if request.taken_by == clinician:
        return request
    raise Conflict("this request is taken by another clinical advisor")


def return_if_idle(
    request: ClinicalRequest,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> ClinicalRequest:
    """Clear an unadvised lock once it is as old as the take timeout (ten minutes by default).
    Advised requests are never released."""
    policy = require_policy(policy)
    now = _utc(now, "now")
    if request.advised_at is None and _is_idle(request, now, policy):
        return replace(request, taken_by=None, taken_at=None)
    return request


def give_advice(
    request: ClinicalRequest,
    clinician_id: str,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> ClinicalRequest:
    """Record advice by the taker, once, while the lock is still live."""
    policy = require_policy(policy)
    clinician = _clinician(clinician_id)
    now = _utc(now, "now")
    if request.advised_at is not None:
        raise InvalidTransition("advice has already been given for this request")
    if request.taken_by != clinician:
        raise NotAllowed("only the clinical advisor who took the request can give advice")
    if _is_idle(request, now, policy):
        raise NotAllowed("the lock has lapsed; take the request again")
    return replace(request, advised_at=now)


def release_for_away(
    requests: Iterable[ClinicalRequest], clinician_id: str
) -> list[ClinicalRequest]:
    """Released copies of this clinician's unadvised requests. Other requests are not returned."""
    clinician = _clinician(clinician_id)
    return [
        replace(request, taken_by=None, taken_at=None)
        for request in requests
        if request.taken_by == clinician and request.advised_at is None
    ]


def available_count(presences: Iterable[Presence]) -> int:
    """Count available clinical advisors. Anything that is not a Presence member is not counted."""
    return sum(
        1
        for presence in presences
        if isinstance(presence, Presence) and presence is Presence.AVAILABLE
    )


def advice_shown_as_available(available: int | None, queue_known: bool) -> bool:
    """Advice is offered only when the presence count and the queue are both known and non-empty."""
    return bool(queue_known) and type(available) is int and available > 0


def queue_order(requests: Iterable[ClinicalRequest]) -> list[ClinicalRequest]:
    """Untaken, unadvised requests: now first, then within-15-min, oldest first within each."""
    waiting = [r for r in requests if r.taken_by is None and r.advised_at is None]
    return sorted(
        waiting, key=lambda r: (_URGENCY_RANK[r.urgency], _utc(r.requested_at, "requested_at"))
    )


def validate_note(note: str) -> None:
    if not isinstance(note, str):
        raise ValidationFailed("note", "must be text")
    if len(note) > NOTE_MAX:
        raise ValidationFailed("note", f"must be at most {NOTE_MAX} characters")
