"""Booking state machine and FHIR Task status mapping (D13).

Rules: docs/spec/domain-rules.md section 3.1 (states and the Task mapping) and 3.2 (transitions).
Pure: no I/O. Every move the rule book does not list raises InvalidTransition.

Lookups are keyed by BookingStatus members only, and every incoming value is checked to be a
BookingStatus first. StrEnum members from other enums with the same value compare equal to
these members (see lesson L3), so a bare dictionary lookup would accept them.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from diucs.domain.codes import BookingStatus, parse_code
from diucs.domain.errors import InvalidTransition, ValidationFailed

_R = BookingStatus.REQUESTED
_C = BookingStatus.CONFIRMED

ALLOWED: Mapping[BookingStatus, frozenset[BookingStatus]] = MappingProxyType(
    {
        _R: frozenset(
            {
                BookingStatus.CONFIRMED,
                BookingStatus.DECLINED,
                BookingStatus.EXPIRED,
                BookingStatus.CANCELLED_BEFORE,
            }
        ),
        _C: frozenset(
            {
                BookingStatus.CANCELLED_AFTER,
                BookingStatus.WITHDRAWN,
                BookingStatus.NOT_REACHED,
                BookingStatus.COMPLETED,
            }
        ),
        BookingStatus.DECLINED: frozenset(),
        BookingStatus.EXPIRED: frozenset(),
        BookingStatus.CANCELLED_BEFORE: frozenset(),
        BookingStatus.CANCELLED_AFTER: frozenset(),
        BookingStatus.WITHDRAWN: frozenset(),
        BookingStatus.NOT_REACHED: frozenset(),
        BookingStatus.COMPLETED: frozenset(),
    }
)


@dataclass(frozen=True, slots=True)
class FhirTaskStatus:
    status: str
    business_status: str
    status_reason: str | None


_FHIR: Mapping[BookingStatus, FhirTaskStatus] = MappingProxyType(
    {
        BookingStatus.REQUESTED: FhirTaskStatus("requested", "requested", None),
        BookingStatus.CONFIRMED: FhirTaskStatus("accepted", "confirmed", None),
        BookingStatus.DECLINED: FhirTaskStatus("rejected", "declined", None),
        BookingStatus.EXPIRED: FhirTaskStatus("cancelled", "expired", "expired"),
        BookingStatus.CANCELLED_BEFORE: FhirTaskStatus("cancelled", "cancelled-before", None),
        BookingStatus.CANCELLED_AFTER: FhirTaskStatus("cancelled", "cancelled-after", None),
        BookingStatus.WITHDRAWN: FhirTaskStatus("cancelled", "withdrawn", "withdrawn"),
        BookingStatus.NOT_REACHED: FhirTaskStatus("failed", "not-reached", None),
        BookingStatus.COMPLETED: FhirTaskStatus("completed", "completed", None),
    }
)


def _checked(status: BookingStatus) -> BookingStatus:
    if not isinstance(status, BookingStatus):
        raise ValidationFailed("status", "not a booking status")
    return status


def allowed_targets(current: BookingStatus) -> frozenset[BookingStatus]:
    return ALLOWED[_checked(current)]


def is_open(status: BookingStatus) -> bool:
    """Only a requested booking is open: one per service, awaiting a reply."""
    return _checked(status) is BookingStatus.REQUESTED


def is_terminal(status: BookingStatus) -> bool:
    return not allowed_targets(status)


def transition(current: BookingStatus, target: BookingStatus) -> BookingStatus:
    if not (isinstance(current, BookingStatus) and isinstance(target, BookingStatus)):
        raise InvalidTransition("a booking can only move between booking states")
    if target not in ALLOWED[current]:
        raise InvalidTransition(f"booking cannot move from {current.value} to {target.value}")
    return target


def to_fhir(status: BookingStatus) -> FhirTaskStatus:
    return _FHIR[_checked(status)]


def from_fhir(business_status: str) -> BookingStatus:
    return parse_code(BookingStatus, business_status)
