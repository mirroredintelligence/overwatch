"""The support-access ticket: a support person asks one tenant for access, the tenant's
administrator decides, an approval issues the one-time code of the cross-tenant guard (TEN-075,
TEN-084, DEC-134 item 5, DEC-136 item 6).

A ticket is not access. It is the request and the record of the decision. Access is what the guard
(`application/cross_tenant_guard.py`) opens when the support person presents the code the approval
issued, for one tenant and one hour. A ticket therefore moves like this, and nothing else moves:

    pending  -> approved  (the tenant's administrator; the approval issues the code)
    pending  -> refused   (the tenant's administrator)
    pending  -> cancelled (the support person who asked)
    approved -> opened    (the support person presents the code; the guard opens the access)
    approved -> revoked   (the tenant's administrator withdraws the code)
    opened   -> ended     (the support person ends the access)
    opened   -> revoked   (the tenant's administrator ends the access)

No standing access (DEC-134 item 5): every live state has a time it ends, and an elapsed time is
`expired` whatever was stored. `valid_until` is, for a pending ticket, when the request lapses (a
day, [ASSUMED]); for an approved one when its code lapses (the guard's four hours); for an opened
one when the access ends (the guard's hour). The state of a ticket as anyone sees it is
`effective_state(ticket, now)`: a stored `pending`, `approved` or `opened` whose time has come is
`expired`, so nothing has to run for an expiry to take effect.

The reason is a fixed code and a short plain sentence that names no one: letters, digits and a few
marks, and nothing with the shape of patient data. A reference is the support person's own ticket
number in the operator's help desk (letters, digits, hyphen).

Pure: no I/O and no clock. Every instant is an argument; every refusal names the field and never the
value.
"""

import dataclasses
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.network import ACCOUNT_REF_PATTERN
from diucs.domain.model.tenant import check_tenant_id

PENDING_VALID_FOR: Final = timedelta(hours=24)  # [ASSUMED]
"""How long a request waits for the tenant's administrator before it lapses."""

TICKET_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
REFERENCE_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,31}")
REASON_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,'&()+-]*")
REASON_MIN_LENGTH: Final = 10
REASON_MAX_DIGITS: Final = 6
"""A sentence with more digits than this is refused: a phone number or an NHS number is not a
reason, and the patient-data guard recognises the second but not the first."""
REASON_MAX_LENGTH: Final = 200
HASH_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
ACCESS_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")

TICKET_MESSAGE: Final = "is not a valid ticket"
REASON_TEXT_MESSAGE: Final = "must be a plain sentence of 10 to 200 characters naming no one"
AWARE_MESSAGE: Final = "must be a timezone-aware datetime"
ENDED_BY_MESSAGE: Final = "is not a valid way for an access to end"


class TicketState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    OPENED = "opened"
    ENDED = "ended"
    REVOKED = "revoked"
    EXPIRED = "expired"
    """Never stored: what a live ticket reads as once its time has come."""


class ReasonCode(StrEnum):
    """A fixed list; what a support person may ask for access for."""

    SECURITY_INCIDENT = "security-incident"
    CLINICAL_SAFETY = "clinical-safety"
    SERVICE_FAULT = "service-fault"
    CONFIGURATION = "configuration"
    USER_REQUEST = "user-request"
    OTHER = "other"


class EndedBy(StrEnum):
    SUPPORT = "support"
    TENANT_ADMIN = "tenant-admin"


STORED_STATES: Final = frozenset(state for state in TicketState if state is not TicketState.EXPIRED)
LIVE_STATES: Final = frozenset({TicketState.PENDING, TicketState.APPROVED, TicketState.OPENED})

_MOVES: Final = MappingProxyType(
    {
        TicketState.PENDING: frozenset(
            {TicketState.APPROVED, TicketState.REFUSED, TicketState.CANCELLED}
        ),
        TicketState.APPROVED: frozenset({TicketState.OPENED, TicketState.REVOKED}),
        TicketState.OPENED: frozenset({TicketState.ENDED, TicketState.REVOKED}),
        TicketState.REFUSED: frozenset(),
        TicketState.CANCELLED: frozenset(),
        TicketState.ENDED: frozenset(),
        TicketState.REVOKED: frozenset(),
    }
)


def _aware(field: str, value: object) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValidationFailed(field, AWARE_MESSAGE)
    return value.astimezone(UTC)


def _optional_aware(field: str, value: object) -> None:
    if value is not None:
        _aware(field, value)


def _account_ref(field: str, value: object) -> str:
    if type(value) is not str or ACCOUNT_REF_PATTERN.fullmatch(value) is None:
        raise ValidationFailed(field, "is not a valid account reference")
    return value


def check_reason(value: object) -> str:
    """The sentence, when it is plain text of the right length with no patient-data shape."""
    if (
        type(value) is not str
        or not REASON_MIN_LENGTH <= len(value) <= REASON_MAX_LENGTH
        or REASON_PATTERN.fullmatch(value) is None
        or sum(character.isdigit() for character in value) > REASON_MAX_DIGITS
        or find_patient_data(value)
    ):
        raise ValidationFailed("reason", REASON_TEXT_MESSAGE)
    return value


def check_reference(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or REFERENCE_PATTERN.fullmatch(value) is None:
        raise ValidationFailed("reference", "must be letters, digits and hyphens, at most 32")
    return value


@dataclass(frozen=True, slots=True)
class SupportTicket:
    id: str
    tenant_id: str
    requested_by_ref: str
    reason_code: ReasonCode
    reason: str
    reference: str | None
    state: TicketState
    requested_at: datetime
    valid_until: datetime
    decided_by_ref: str | None = None
    decided_at: datetime | None = None
    grant_hash: str | None = None
    access_id: str | None = None
    opened_at: datetime | None = None
    ended_at: datetime | None = None
    ended_by: EndedBy | None = None

    def __post_init__(self) -> None:
        if type(self.id) is not str or TICKET_ID_PATTERN.fullmatch(self.id) is None:
            raise ValidationFailed("id", TICKET_MESSAGE)
        check_tenant_id(self.tenant_id)
        _account_ref("requested_by_ref", self.requested_by_ref)
        if type(self.reason_code) is not ReasonCode:
            raise ValidationFailed("reason_code", "is not a valid reason")
        check_reason(self.reason)
        check_reference(self.reference)
        if type(self.state) is not TicketState or self.state not in STORED_STATES:
            raise ValidationFailed("state", "is not a stored state")
        requested = _aware("requested_at", self.requested_at)
        valid = _aware("valid_until", self.valid_until)
        if valid <= requested:
            raise ValidationFailed("valid_until", "must be after the request")
        for name in ("decided_at", "opened_at", "ended_at"):
            _optional_aware(name, getattr(self, name))
        if self.decided_by_ref is not None and (
            type(self.decided_by_ref) is not str or not 1 <= len(self.decided_by_ref) <= 128
        ):
            raise ValidationFailed("decided_by_ref", "is not a valid reference")
        if self.grant_hash is not None and (
            type(self.grant_hash) is not str or HASH_PATTERN.fullmatch(self.grant_hash) is None
        ):
            raise ValidationFailed("grant_hash", "is not a hash")
        if self.access_id is not None and (
            type(self.access_id) is not str or ACCESS_ID_PATTERN.fullmatch(self.access_id) is None
        ):
            raise ValidationFailed("access_id", "is not an access id")
        if self.ended_by is not None and type(self.ended_by) is not EndedBy:
            raise ValidationFailed("ended_by", ENDED_BY_MESSAGE)
        self._check_state_fields()

    def _check_state_fields(self) -> None:
        """The fields a state needs, so a record that says `approved` with no code, or `opened` with
        no access, is not a record."""
        state = self.state
        decided = state is not TicketState.PENDING and state is not TicketState.CANCELLED
        if decided and (self.decided_by_ref is None or self.decided_at is None):
            raise ValidationFailed("decided_by_ref", "is required once the tenant has decided")
        if state in (TicketState.APPROVED, TicketState.OPENED) and self.grant_hash is None:
            raise ValidationFailed("grant_hash", "is required once a code has been issued")
        if state is TicketState.OPENED and (self.access_id is None or self.opened_at is None):
            raise ValidationFailed("access_id", "is required once the access is open")
        if state in (TicketState.ENDED, TicketState.REVOKED, TicketState.CANCELLED) and (
            self.ended_at is None
        ):
            raise ValidationFailed("ended_at", "is required once the ticket has ended")


# ---------------------------------------------------------------- the rules


def new_ticket(
    *,
    ticket_id: str,
    tenant_id: str,
    requested_by_ref: str,
    reason_code: ReasonCode,
    reason: str,
    reference: str | None,
    now: datetime,
) -> SupportTicket:
    """A pending request. It lapses `PENDING_VALID_FOR` after `now`."""
    requested = _aware("now", now)
    return SupportTicket(
        id=ticket_id,
        tenant_id=tenant_id,
        requested_by_ref=requested_by_ref,
        reason_code=reason_code,
        reason=reason,
        reference=reference,
        state=TicketState.PENDING,
        requested_at=requested,
        valid_until=requested + PENDING_VALID_FOR,
    )


def effective_state(ticket: SupportTicket, now: datetime) -> TicketState:
    """What the ticket reads as at `now`: a live ticket whose time has come is `expired`."""
    instant = _aware("now", now)
    if ticket.state in LIVE_STATES and instant >= ticket.valid_until:
        return TicketState.EXPIRED
    return ticket.state


def _move(ticket: SupportTicket, target: TicketState, now: datetime) -> None:
    """The move is legal and the ticket is still in its time. An expired ticket moves nowhere."""
    if type(ticket) is not SupportTicket:
        raise NotAllowed("not a ticket")
    if target not in _MOVES.get(ticket.state, frozenset()):
        raise InvalidTransition(f"a ticket cannot move from {ticket.state.value} to {target.value}")
    if effective_state(ticket, now) is TicketState.EXPIRED:
        raise InvalidTransition("the ticket has expired")


def approve(
    ticket: SupportTicket,
    *,
    decided_by_ref: str,
    grant_hash: str,
    grant_expires_at: datetime,
    now: datetime,
) -> SupportTicket:
    """Approve a pending ticket: the code the approval issued lapses at `grant_expires_at`, which is
    when the approved ticket lapses."""
    _move(ticket, TicketState.APPROVED, now)
    return dataclasses.replace(
        ticket,
        state=TicketState.APPROVED,
        decided_by_ref=decided_by_ref,
        decided_at=_aware("now", now),
        grant_hash=grant_hash,
        valid_until=_aware("grant_expires_at", grant_expires_at),
    )


def refuse(ticket: SupportTicket, *, decided_by_ref: str, now: datetime) -> SupportTicket:
    _move(ticket, TicketState.REFUSED, now)
    return dataclasses.replace(
        ticket,
        state=TicketState.REFUSED,
        decided_by_ref=decided_by_ref,
        decided_at=_aware("now", now),
    )


def cancel(ticket: SupportTicket, *, now: datetime) -> SupportTicket:
    """The support person withdraws a request that has not been decided."""
    _move(ticket, TicketState.CANCELLED, now)
    instant = _aware("now", now)
    return dataclasses.replace(
        ticket, state=TicketState.CANCELLED, ended_at=instant, ended_by=EndedBy.SUPPORT
    )


def open_access(
    ticket: SupportTicket,
    *,
    access_id: str,
    grant_hash: str,
    opened_at: datetime,
    expires_at: datetime,
) -> SupportTicket:
    """The access the guard opened for this ticket's code. `grant_hash` is the code the guard
    redeemed: it must be the one the approval issued, so a code that was issued for another ticket
    opens nothing under this one."""
    _move(ticket, TicketState.OPENED, opened_at)
    if ticket.grant_hash is None or grant_hash != ticket.grant_hash:
        raise NotAllowed("the code was not issued for this ticket")
    return dataclasses.replace(
        ticket,
        state=TicketState.OPENED,
        access_id=access_id,
        opened_at=_aware("opened_at", opened_at),
        valid_until=_aware("expires_at", expires_at),
    )


def end_access(ticket: SupportTicket, *, by: EndedBy, now: datetime) -> SupportTicket:
    """The support person ends the access (`SUPPORT`)."""
    _move(ticket, TicketState.ENDED, now)
    return dataclasses.replace(
        ticket, state=TicketState.ENDED, ended_at=_aware("now", now), ended_by=by
    )


def revoke(ticket: SupportTicket, *, now: datetime) -> SupportTicket:
    """The tenant's administrator withdraws the code or ends the access."""
    _move(ticket, TicketState.REVOKED, now)
    return dataclasses.replace(
        ticket,
        state=TicketState.REVOKED,
        ended_at=_aware("now", now),
        ended_by=EndedBy.TENANT_ADMIN,
    )
