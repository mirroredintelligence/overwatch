"""Booking state machine and FHIR Task status mapping (D13). Red-commit stub: no behaviour yet.

Rules: docs/spec/domain-rules.md section 3.1 and 3.2.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from diucs.domain.codes import BookingStatus

ALLOWED: Mapping[BookingStatus, frozenset[BookingStatus]] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class FhirTaskStatus:
    status: str
    business_status: str
    status_reason: str | None


def allowed_targets(current: BookingStatus) -> frozenset[BookingStatus]:
    raise NotImplementedError


def is_open(status: BookingStatus) -> bool:
    raise NotImplementedError


def is_terminal(status: BookingStatus) -> bool:
    raise NotImplementedError


def transition(current: BookingStatus, target: BookingStatus) -> BookingStatus:
    raise NotImplementedError


def to_fhir(status: BookingStatus) -> FhirTaskStatus:
    raise NotImplementedError


def from_fhir(business_status: str) -> BookingStatus:
    raise NotImplementedError
