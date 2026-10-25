"""Domain events the core raises, and how each maps to a Service Bus topic (D25).

STUB for the red commit (DEC-010): the classes carry their fields; behaviour raises NotImplementedError.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from diucs.domain.codes import AlertKind, BookingStatus, ReportSource, Status


@dataclass(frozen=True, slots=True)
class CapacityReported:
    event_type: ClassVar[str] = "CapacityReported"
    service_id: str
    report_id: str
    value: int
    source: ReportSource
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class StatusChanged:
    event_type: ClassVar[str] = "StatusChanged"
    service_id: str
    before: Status | None
    after: Status
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class BookingRequested:
    event_type: ClassVar[str] = "BookingRequested"
    booking_id: str
    service_id: str
    reference: str
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class BookingResponded:
    event_type: ClassVar[str] = "BookingResponded"
    booking_id: str
    service_id: str
    status: BookingStatus
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class BookingExpired:
    event_type: ClassVar[str] = "BookingExpired"
    booking_id: str
    service_id: str
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RegistrationSubmitted:
    event_type: ClassVar[str] = "RegistrationSubmitted"
    registration_id: str
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RegistrationApproved:
    event_type: ClassVar[str] = "RegistrationApproved"
    registration_id: str
    service_id: str
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class CriteriaApproved:
    event_type: ClassVar[str] = "CriteriaApproved"
    criteria_id: str
    service_id: str
    version: int
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class AlertRaised:
    event_type: ClassVar[str] = "AlertRaised"
    alert_id: str
    kind: AlertKind
    service_id: str
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class AlertAcknowledged:
    event_type: ClassVar[str] = "AlertAcknowledged"
    alert_id: str
    by: str
    at: datetime

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError


DomainEvent = (
    CapacityReported
    | StatusChanged
    | BookingRequested
    | BookingResponded
    | BookingExpired
    | RegistrationSubmitted
    | RegistrationApproved
    | CriteriaApproved
    | AlertRaised
    | AlertAcknowledged
)


def topic_for(event: DomainEvent) -> str:
    raise NotImplementedError


def session_id_for(event: DomainEvent) -> str | None:
    raise NotImplementedError


def from_payload(event_type: str, payload: dict[str, Any]) -> DomainEvent:
    raise NotImplementedError
